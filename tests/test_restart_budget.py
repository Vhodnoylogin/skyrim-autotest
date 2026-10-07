"""Frozen restart slots and collection preserve all segments without live processes."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from skyrim_autotest import restart_budget as budget, game_restart, native, runner
import test_game_restart as restart_fixture
import test_audit_recovery as collection_fixture


def scenario(count):
    return {'schemaVersion':1, 'steps':[
        {'name':f'restart-{i}', 'tool':'platform', 'args':{'operation':'input.perform',
          'request':{'action':'restart_game', 'saveTag':'fixture', 'scope':'owned-disposable-profile'}}}
        for i in range(count)]}


def state(count):
    value={'scenario':scenario(count)}
    value['ownedGameRestartBudget']=budget.plan(value['scenario'])
    return value


class BudgetTests(unittest.TestCase):
    def test_seven_exact_slots_then_eighth_and_same_step_replay_rejected(self):
        s=state(7)
        for i,step in enumerate(s['scenario']['steps']):
            s['activeScenarioStep']=budget.step_identity('steps',i,step)
            ordinal,slot=budget.next_slot(s)
            self.assertEqual(ordinal,i+1)
            s['ownedGameRestartCount']=ordinal
            s.setdefault('gameRestartHistory',[]).append({'ordinal':ordinal,'completed':True})
            with self.assertRaisesRegex(ValueError,'next declared|exhausted'):budget.next_slot(s)
        with self.assertRaisesRegex(ValueError,'exhausted'):budget.next_slot(s)

    def test_changed_scenario_budget_wrong_step_count_and_incomplete_fail_closed(self):
        for mutate in (
            lambda s:s['scenario']['steps'][0].update(name='changed'),
            lambda s:s['ownedGameRestartBudget'].update(maximum=99),
            lambda s:s.update(activeScenarioStep={}),
            lambda s:s.update(ownedGameRestartCount=True),
            lambda s:s.update(ownedGameRestartCount=1,gameRestartHistory=[]),
            lambda s:s.update(ownedGameRestartCount=1,gameRestartHistory=[{'completed':False}]),
        ):
            s=state(2);s['activeScenarioStep']=s['ownedGameRestartBudget']['slots'][1]
            mutate(s)
            with self.subTest(s=s),self.assertRaises(ValueError):budget.next_slot(s)

    def test_future_settings_slots_do_not_implement_action_and_poststeps_keep_identity(self):
        s=scenario(1)
        s['postSteps']=[{'name':'variant','tool':'platform','args':{'operation':'object.perform',
            'request':{'action':'restart_with_fixture_subject_settings'}}}]
        p=budget.plan(s)
        self.assertEqual(p['maximum'],2);self.assertEqual(p['slots'][1]['section'],'postSteps')
        from skyrim_autotest.platform import validate
        with self.assertRaises(ValueError):validate(s['postSteps'][0]['args'])
        s['steps'][0]['poll']=True
        with self.assertRaisesRegex(ValueError,'cannot poll'):budget.plan(s)

    def test_zero_restart_scenario_grants_no_restart(self):
        with self.assertRaisesRegex(ValueError,'exhausted'):budget.next_slot(state(0))

    def test_seventh_actual_start_retains_one_exit_launch_and_distinct_history(self):
        fixture=restart_fixture.RestartTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            b,new,request=fixture.backend(Path(tmp))
            s=b.s.state;s.update(state(7));s['ownedGameRestartCount']=6
            s['gameRestartHistory']=[{'ordinal':i,'completed':True} for i in range(1,7)]
            s['activeScenarioStep']=s['ownedGameRestartBudget']['slots'][6]
            with patch.object(native,'alive',side_effect=lambda i:fixture.old_live if i['pid']==17 else True), \
                 patch.object(native,'processes',return_value=[]),patch.object(runner,'request',side_effect=request):
                game_restart.start(b)
            self.assertEqual(fixture.segments,['before-restart-7'])
            self.assertEqual(sum(route=='run' for route,args in fixture.calls),1)
            self.assertEqual(sum(route=='console' for route,args in fixture.calls),1)
            self.assertEqual(s['gameRestartHistory'][-1]['afterGame'],new)
            self.assertFalse(s['gameRestartHistory'][-1]['completed'])
            budget.update(s,completed=True,stage='completed')
            self.assertTrue(s['gameRestartHistory'][-1]['completed'])


class SegmentTests(unittest.TestCase):
    def fixture(self):
        f=collection_fixture.CollectionRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        f.session.state.update(state(7));return f

    def test_all_seven_segment_bytes_are_flat_manifest_pinned(self):
        f=self.fixture()
        for i in range(1,8):
            f.session.state['ownedGameRestartCount']=i
            (f.steam/'vrserver.txt').write_text(f'segment{i}')
            self.assertTrue(f.session.collect(f'before-restart-{i}'))
        self.assertTrue(f.session.collect())
        manifest=runner.read_json(f.directory/'evidence/manifest.json')
        for i in range(1,8):
            row=next(v for v in manifest if v['name']==f'before-restart-{i}--vrserver.txt')
            path=f.directory/'evidence'/row['name']
            self.assertEqual(path.read_text(),f'segment{i}');self.assertEqual(runner.sha(path),row['sha256'])

    def test_segment_cannot_replay_traverse_or_exceed_reservation(self):
        f=self.fixture();f.session.state['ownedGameRestartCount']=1
        self.assertTrue(f.session.collect('before-restart-1'))
        for name in ('before-restart-1','before-restart-2','before-restart-0','before-restart-01','../escape'):
            with self.subTest(name=name),self.assertRaises(ValueError):f.session.collect(name)

    def test_missing_reserved_segment_fails_collection_but_cleanup_restores(self):
        f=self.fixture();f.session.state['ownedGameRestartCount']=7
        f.session.cleanup()
        self.assertTrue(f.session.state['restored']);self.assertFalse(f.session.state['collectionComplete'])
        self.assertEqual(len(f.session.state['collectionErrors']),7)
        self.assertEqual(f.file.read_bytes(),b'original')
