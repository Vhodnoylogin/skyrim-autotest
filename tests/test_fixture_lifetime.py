"""Continuation observes the live fixture; old FormIDs never drive later cleanup."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from skyrim_autotest import fixture_actors, scenarios, runner, vr_probe

class FixtureLifetimeTests(unittest.TestCase):
    class Session:
        def __init__(self,directory):
            self.dir=Path(directory)
            self.state={'probeObject':'0xFF001234','probeObjectLive':True,'checks':[]}
            self.tools=[]
        def save(self):pass
        def log(self,*args,**kwargs):pass
        def phase(self,*args):pass
        def validate_probe_reference(self,timeout=3):
            if self.state.get("probeObjectLive") is not True:raise runner.Blocked("Invalid reference")
        def tool(self,name,args,timeout=12,deadline=None):
            self.tools.append(args)
            return {'live':self.state.get('probeObjectLive') is True}
    def test_post_step_observes_retained_live_exact_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.Session(directory)
            calls=[]
            def probe(session,scenario):
                vr_probe.finish_probe_reference(session,scenario,lambda *a,**k:calls.append((a,k)),'0xFF001234')
            scenario={'kind':'vr-hand-probe','postSteps':[{'name':'live-body','tool':'inspect','args':{'ref':{'$state':'probeObject'}},'assert':[{'path':'live','equals':True}]}]}
            with patch.object(vr_probe,'execute',side_effect=probe):
                scenarios.execute(session,scenario)
            self.assertEqual(calls,[])
            self.assertEqual(session.tools,[{'ref':'0xFF001234'}])
            self.assertEqual(session.state['checks'][0]['result'],'passed')
            self.assertFalse(session.state['postStepsActive'])
    def test_no_post_step_keeps_original_immediate_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.Session(directory)
            calls=[]
            vr_probe.finish_probe_reference(session,{},lambda *a,**k:calls.append((a,k)),'0xFF001234')
            self.assertEqual([call[0][1] for call in calls],['Disable','Delete'])
            self.assertFalse(session.state['probeObjectLive'])
    def test_world_change_invalidates_typed_reference_before_reused_form_can_be_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            session=runner.Session(directory,{'probeObject':'0xFF001234','probeObjectLive':True,'postStepsActive':True,'port':1,'game':{'pid':42}})
            with patch.object(runner,'request',side_effect=[{'pid':42},{'queued':True}]),patch.object(runner.native,'alive',return_value=True):
                session.tool('game',{'action':'load','name':'another'})
            with self.assertRaisesRegex(ValueError,'invalidated'):
                scenarios.resolve_args({'self':{'form':{'$state':'probeObject'}}},session.state)
            calls=[]
            vr_probe.finish_probe_reference(session,{'postSteps':[{}]},lambda *a,**k:calls.append((a,k)),'0xFF001234')
            self.assertEqual(calls,[]) # no late Disable/Delete of a possibly reused ID
            self.assertFalse(session.state['probeObjectLive'])
    def test_default_cleanup_cannot_delete_an_invalidated_form_id(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.Session(directory)
            session.state['probeObjectLive']=False
            calls=[]
            with self.assertRaisesRegex(runner.Blocked,'Invalid reference'):
                vr_probe.finish_probe_reference(session,{},lambda *a,**k:calls.append((a,k)),'0xFF001234')
            self.assertEqual(calls,[])

    def test_impulse_is_not_a_world_change_but_arbitrary_console_is(self):
        self.assertFalse(runner.changes_reference_world('papyrus',{'action':'call','script':'ObjectReference','function':'ApplyHavokImpulse'}))
        self.assertTrue(runner.changes_reference_world('console',{'action':'exec','command':'bat unknown-script'}))
        self.assertTrue(runner.changes_reference_world('papyrus',{'action':'call','script':'Game','function':'LoadGame'}))

class PersistentFixtureAdmissionTests(unittest.TestCase):
    def test_live_missing_or_malformed_identity_api_refuses_before_fixture_intent(self):
        base = '0x000A2C91'
        policy = {'schemaVersion': 1, 'fixtureActorBases': [base], 'allowedRaceForms': [],
                  'bindings': [{'id': 'read-race', 'script': 'Actor', 'function': 'GetRace',
                                'scope': 'member', 'params': [], 'returnType': 'race', 'effect': 'read',
                                'actorSelf': True, 'actorArgs': [], 'raceArgs': [], 'completion': 'native-return'}]}
        types = {'action': 'string', 'reference': 'string', 'base': 'string', 'timeoutMs': 'integer'}
        valid = {'name': 'npc_persistence', 'inputSchema': {'type': 'object',
                 'properties': {key: {'type': kind} for key, kind in types.items()}}}
        invalid = {'name': 'npc_persistence', 'inputSchema': {'type': 'object',
                   'properties': {**valid['inputSchema']['properties'], 'reference': {'type': 'integer'}}}}
        cases = [(True, [], False), (True, [invalid], False), (True, [valid, valid], False),
                 (True, [valid], True), (False, [], True)]
        for persistent, tools, admitted in cases:
            with self.subTest(persistent=persistent, tools=tools):
                session = Mock()
                session.state = {'id': 'current-run', 'port': 8920, 'game': {'pid': 41}, 'configuration': {
                    'native_session': {'nativeBindings': policy, 'npcPersistence': True}}}
                session.tool.side_effect = [
                    {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}},
                    {'messageBoxOpen': False, 'openMenus': [], 'menuStates': []}]
                request = {'tag': 'wolf', 'base': base, 'forwardGameUnits': 100, 'rightGameUnits': 0,
                           'persistentForOwnedSave': persistent}
                with (patch.object(fixture_actors, '_owned'),
                      patch.object(fixture_actors, '_qualify', side_effect=RuntimeError('fixture metadata reached')),
                      patch.object(fixture_actors, '_native_call') as mutation,
                      patch.object(runner, 'request', return_value={'tools': tools}) as registry):
                    error = RuntimeError if admitted else fixture_actors.BindingError
                    message = 'fixture metadata reached' if admitted else 'npc_persistence.*identity'
                    with self.assertRaisesRegex(error, message):
                        fixture_actors.create(session, request, time.monotonic() + 10, policy)
                if persistent:
                    registry.assert_called_once_with(8920, 'api/tools', timeout=3)
                else:
                    registry.assert_not_called()
                mutation.assert_not_called()
                session.save.assert_not_called()
                self.assertFalse(session.state.get('interactiveActorFixtures'))


if __name__=='__main__':unittest.main()
