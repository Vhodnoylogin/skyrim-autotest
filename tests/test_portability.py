"""Portability and independent process recovery contracts, without starting the game."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import config, runner, hardware, queue
from skyrim_autotest.scenarios import validate, resolve_args, check, execute

class PortabilityTests(unittest.TestCase):
    def test_actor_fixture_allowlist_is_explicit_bounded_and_unique(self):
        spec={'plugin':'fixture.esp','localId':'000900'}
        selected=config.configure(dict(self.value,fixture_actor_allowlist=[spec]))
        self.assertEqual(selected['fixture_actor_allowlist'],[spec])
        for values in (True,[spec,spec],[{'plugin':'fixture.esp','localId':'0'}],
                       [{'plugin':'../fixture.esp','localId':'900'}],[spec]*17):
            with self.subTest(values=values),self.assertRaises(config.ConfigurationError):
                config.configure(dict(self.value,fixture_actor_allowlist=values))

    def test_subject_write_binding_snapshots_only_declared_overwrite_targets_and_temps(self):
        binding={'inspectKind':'any_state','settingsDestination':'SKSE/Plugins/any.json',
                 'handednessProfileIni':'skyrimprefs.ini','bodySlotsDestination':'SKSE/Plugins/slots.ini',
                 'bodySlotsSource':{'path':str(self.root/'pinned-baseline.ini'),'sha256':'0'*64}}
        value=config.configure(dict(self.value,subject_state_bindings={'Any Subject':binding}))
        self.assertEqual(len(value['extra_files']),4)
        self.assertTrue(all(Path(p).is_relative_to(Path(value['overwrite'])) for p in value['extra_files']))
        for change in ({'settingsDestination':'../escape.json'},{'handednessProfileIni':'../skyrimprefs.ini'},
                       {'bodySlotsSource':{'path':str(Path(value['mods'])/'mutable.ini'),'sha256':'0'*64}}):
            with self.assertRaises(config.ConfigurationError):config.configure(dict(self.value,subject_state_bindings={'Any Subject':dict(binding,**change)}))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = config.P.snapshot()
        self.value = config.template()
        for key in config.REQUIRED:
            self.value[key] = str(self.root / key)
        self.value['fixture_dir'] = str(self.root / 'fixture')
        runner.configure(self.value)
    def tearDown(self):
        config.P.value = self.old
        runner.ROOT = config.P.runtime
        runner.RUNS = runner.ROOT / 'runs'
        self.temp.cleanup()
    def test_relative_paths_resolve_against_config_not_working_directory(self):
        value = dict(self.value, runtime='runtime', game='game')
        file = self.root / 'config.json'
        file.write_text(json.dumps(value), encoding='utf-8')
        loaded = config.load(file)
        self.assertEqual(Path(loaded['runtime']), self.root / 'runtime')
        self.assertEqual(Path(loaded['game']), self.root / 'game')
    def test_staged_plugins_cannot_escape_overwrite(self):
        for destination in ('../outside.dll', '/outside.dll', 'C:\\outside.dll', 'SKSE/../../outside.dll', 'C:outside.dll'):
            value = dict(self.value, staged_plugins=[{'source':'observer.dll','destination':destination,'sha256':'0'*64}])
            with self.subTest(destination=destination), self.assertRaises(config.ConfigurationError):
                config.configure(value)
    def test_collection_exposes_only_explicit_unique_restore_targets(self):
        path=str(self.root/'output.json')
        with self.assertRaisesRegex(config.ConfigurationError,'snapshotted'):
            config.configure(dict(self.value,collected_files=[path]))
        with self.assertRaisesRegex(config.ConfigurationError,'Duplicate'):
            config.configure(dict(self.value,extra_files=[path],collected_files=[path,path]))
        selected=config.configure(dict(self.value,extra_files=[path],collected_files=[path]))
        self.assertEqual(selected['collected_files'],[path])
    def test_runtime_must_be_outside_live_directories_and_git(self):
        with self.assertRaises(config.ConfigurationError):
            config.configure(dict(self.value, runtime=str(Path(self.value['mods']) / 'runs')))
        (self.root / '.git').mkdir()
        with self.assertRaises(config.ConfigurationError):
            config.configure(self.value)
    def test_guardian_imports_portable_package_from_empty_cwd_without_config_file(self):
        directory = runner.RUNS / 'finished'
        directory.mkdir(parents=True)
        runner.atomic_json(directory / 'state.json', {'done':True,'configuration':config.P.snapshot()})
        cwd = self.root / 'unrelated'
        cwd.mkdir()
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        child = subprocess.run(runner.guardian_command(directory), cwd=cwd, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
    def test_session_recovery_uses_durable_config_snapshot(self):
        snapshot = config.P.snapshot()
        config.configure(dict(self.value, bridge_port=9000, mods=str(self.root/'anothermods')))
        runner.Session(self.root, {'configuration':snapshot})
        self.assertEqual(config.P.bridge_port, 8930)
        self.assertEqual(config.P.mods, Path(snapshot['mods']))
    def test_bad_fixture_is_rejected_before_recovery_or_mutation(self):
        scenario = self.root / 'scenario.json'
        scenario.write_text(json.dumps({'schemaVersion':1,'fixture':{'saveStem':'safe','essSha256':'0'*64,'skseSha256':'0'*64},'steps':[{'name':'world','tool':'inspect','assert':[{'exists':True}]}]}),encoding='utf-8')
        with patch.object(runner, 'recover') as recover:
            with self.assertRaisesRegex(runner.Blocked, 'fixture'):
                runner.run('Test', scenario)
            recover.assert_not_called()
    def test_queue_events_are_local_and_need_no_project_ledger(self):
        order = self.root / 'order.json'
        scenario = self.root / 'scenario.json'
        scenario.write_text('{"schemaVersion":1,"steps":[]}',encoding='utf-8')
        order.write_text(json.dumps({'schemaVersion':1,'id':'portable-test','owner':'owner','subject':'fixture','profile':'Test','scenario':'scenario.json'}),encoding='utf-8')
        import contextlib
        with patch.object(queue.native, 'SessionMutex', return_value=contextlib.nullcontext()):
            self.assertEqual(queue.main(['add','--order',str(order)]), 0)
        self.assertEqual(queue.read()[0]['scenarioHash'], runner.sha(scenario))
        events = [json.loads(line) for line in (runner.ROOT/'queue-events.jsonl').read_text().splitlines()]
        self.assertEqual(events[0]['status'],'ordered')
    def test_driver_publishing_is_bounded_and_cannot_alone_prove_a_test(self):
        step = {'name':'publish','tool':'driver','args':{'action':'publish','frame':hardware.neutral(),'holdSeconds':1},'assert':[{'path':'published','equals':True}]}
        scenario = {'schemaVersion':1,'steps':[step]}
        with self.assertRaisesRegex(ValueError, 'publication-only'):
            validate(scenario)
        scenario['steps'].append({'name':'game outcome','tool':'inspect','args':{'kind':'state'},'assert':[{'exists':True}]})
        validate(scenario)
        for duration in (0, 31, float('inf'), True):
            step['args']['holdSeconds'] = duration
            with self.assertRaisesRegex(ValueError, 'holdSeconds'):
                validate(scenario)
    def test_explicit_probe_reference_and_post_steps_keep_assertions(self):
        args = {'physics':{'refs':[{'$state':'probeObject'}]}}
        self.assertEqual(resolve_args(args, {'probeObject':'0xFF001234'}), {'physics':{'refs':['0xFF001234']}})
        scenario = {'schemaVersion':1,'kind':'vr-hand-probe','cell':'QASmoke','postSteps':[{'name':'physics','tool':'inspect','args':args,'assert':[{'path':'physics.available','equals':True}]}]}
        validate(scenario)
        scenario['postSteps'][0]['args'] = {'$state':'snapshots.0.backup'}
        with self.assertRaises(ValueError):
            validate(scenario)
    def test_numeric_bounds_cannot_accept_bool_or_nan(self):
        for value in (True,float('nan'),float('inf'),'1'):
            self.assertFalse(check(value, {'min':0}))
            self.assertFalse(check(value, {'max':2}))
        self.assertTrue(check(1, {'min':0}))
        self.assertTrue(check(1, {'max':2}))

class RecoveryConfigurationTests(unittest.TestCase):
    setUp = PortabilityTests.setUp
    tearDown = PortabilityTests.tearDown
    # Do not inherit the other test cases twice; their own class covers them.
    def state_file(self, name, done, value):
        directory = runner.RUNS / name
        directory.mkdir(parents=True)
        runner.atomic_json(directory / 'state.json', {'id':name,'done':done,'configuration':value,'owned':[],'runner':None})
        return directory
    def selected_configuration(self):
        value = config.P.snapshot()
        value['bridge_token'] = str(self.root / 'new-token-file')
        value['staged_plugins'] = [{'source':str(self.root/'observer.dll'),'destination':'SKSE/Plugins/WorldObserver.dll','sha256':'a'*64}]
        runner.configure(value)
        return config.P.snapshot()
    def test_completed_historical_run_cannot_replace_new_staging_configuration(self):
        import contextlib
        old = config.P.snapshot()
        self.state_file('old-complete', True, old)
        caller = self.selected_configuration()
        original_root = runner.ROOT
        original_runs = runner.RUNS
        with patch.object(runner.native,'SessionMutex',return_value=contextlib.nullcontext()),patch.object(runner,'Session') as session:
            runner.recover()
            session.assert_not_called()
        self.assertEqual(config.P.snapshot(),caller)
        self.assertEqual(runner.ROOT,original_root)
        self.assertEqual(runner.RUNS,original_runs)
    def test_abandoned_runs_use_own_environment_but_scan_original_runtime(self):
        import contextlib
        old = config.P.snapshot()
        old['runtime'] = str(self.root / 'old-runtime')
        old['bridge_token'] = str(self.root/'old-token-file')
        self.state_file('abandoned-a',False,old)
        self.state_file('abandoned-b',False,old)
        caller = self.selected_configuration()
        observations=[]
        def cleanup(session):
            observations.append((session.dir.name,config.P.snapshot()))
        with patch.object(runner.native,'SessionMutex',return_value=contextlib.nullcontext()),patch.object(runner.native,'alive',return_value=False),patch.object(runner.Session,'cleanup',autospec=True,side_effect=cleanup),patch.object(runner.Session,'report'),patch.object(runner.Session,'reopen_mo2'):
            runner.recover()
        self.assertEqual([name for name,value in observations],['abandoned-a','abandoned-b'])
        self.assertTrue(all(value['bridge_token']==old['bridge_token'] and value['runtime']==old['runtime'] for name,value in observations))
        self.assertEqual(config.P.snapshot(),caller)
        self.assertEqual(runner.RUNS,Path(caller['runtime'])/'runs')
    def test_recovery_exception_does_not_leak_abandoned_configuration(self):
        import contextlib
        old=config.P.snapshot()
        old['runtime']=str(self.root/'old-runtime')
        self.state_file('abandoned',False,old)
        caller=self.selected_configuration()
        with patch.object(runner.native,'SessionMutex',return_value=contextlib.nullcontext()),patch.object(runner.native,'alive',return_value=False),patch.object(runner.Session,'cleanup',side_effect=RuntimeError('Restoration failed')):
            with self.assertRaisesRegex(RuntimeError,'Restoration failed'):
                runner.recover()
        self.assertEqual(config.P.snapshot(),caller)
        self.assertEqual(runner.ROOT,Path(caller['runtime']))
    def test_live_owner_blocks_recovery_without_activating_old_environment(self):
        import contextlib
        old = config.P.snapshot()
        old['runtime'] = str(self.root/'old-runtime')
        self.state_file('live-owner',False,old)
        caller = self.selected_configuration()
        with patch.object(runner.native,'SessionMutex',return_value=contextlib.nullcontext()),patch.object(runner.native,'alive',return_value=True),patch.object(runner,'Session') as session:
            with self.assertRaisesRegex(runner.Blocked,'Runner is still alive'):
                runner.recover()
            session.assert_not_called()
        self.assertEqual(config.P.snapshot(),caller)
        self.assertEqual(runner.RUNS,Path(caller['runtime'])/'runs')


class DeadlineTests(unittest.TestCase):
    class Session:
        def __init__(self, directory):
            self.dir = Path(directory)
            self.state = {'checks':[]}
            self.calls = []
        def phase(self, *args):
            pass
        def save(self):
            pass
        def tool(self, name, args, timeout, deadline=None):
            self.calls.append(timeout)
            return {'ok':True}
    def test_late_passing_response_fails_and_records_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.Session(directory)
            scenario = {'steps':[{'name':'bounded state','tool':'inspect','args':{},'timeout':1,'assert':[{'path':'ok','equals':True}]}]}
            with patch('skyrim_autotest.scenarios.time.monotonic', side_effect=[0,0,2]):
                with self.assertRaisesRegex(TimeoutError, 'after deadline'):
                    execute(session, scenario)
            self.assertEqual(session.calls,[1])
            self.assertEqual(session.state['checks'],[{'name':'bounded state','result':'failed','observation':{'ok':True},'reason':'Step response arrived after deadline'}])
    def test_no_tool_call_starts_after_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.Session(directory)
            scenario = {'steps':[{'name':'expired state','tool':'inspect','args':{},'timeout':1,'poll':True,'assert':[{'path':'ok','equals':True}]}]}
            with patch('skyrim_autotest.scenarios.time.monotonic', side_effect=[0,2]):
                with self.assertRaisesRegex(TimeoutError, 'deadline exceeded'):
                    execute(session, scenario)
            self.assertEqual(session.calls,[])
            self.assertEqual(session.state['checks'][0]['result'],'failed')

if __name__ == '__main__':
    unittest.main()
