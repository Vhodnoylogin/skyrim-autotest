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
from skyrim_autotest.scenarios import validate, resolve_args, check

class PortabilityTests(unittest.TestCase):
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

if __name__ == '__main__':
    unittest.main()
