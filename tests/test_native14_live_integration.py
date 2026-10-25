import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from skyrim_autotest import config, runner, scenarios, cli


def policy(root):
    return {'maxAgeMicros': 2000000, 'modules': [
        {'path': str(root / name), 'sha256': 'a' * 64}
        for name in ('devbench.dll', 'VRIK.dll', 'BodySlots.dll')], 'absentModules': []}


def scenario(args=None, **fields):
    return {'schemaVersion': 1, 'steps': [dict(name='Observe copied native14 facts',
        tool='native14', args=args or {'select': {'enabled': 'frame.holstersEnabled'}},
        **fields)]}


class Native14LiveIntegrationTests(unittest.TestCase):
    def test_policy_normalizes_without_requiring_prelaunch_targets_to_exist(self):
        before = config.P.snapshot()
        self.addCleanup(lambda: setattr(config.P, 'value', before))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = config.template('vr')
            value['native14_live'] = policy(root)
            configured = config.configure(value)
            self.assertEqual(configured['native14_live']['maxAgeMicros'], 2000000)
            self.assertFalse((root / 'VRIK.dll').exists())
            value['game_edition'] = 'se'
            with self.assertRaisesRegex(config.ConfigurationError, 'VR target'):
                config.configure(value)

    def test_missing_hash_or_conflicting_identity_rejects_configuration(self):
        before = config.P.snapshot()
        self.addCleanup(lambda: setattr(config.P, 'value', before))
        with tempfile.TemporaryDirectory() as folder:
            value = config.template('vr')
            value['native14_live'] = policy(Path(folder))
            del value['native14_live']['modules'][0]['sha256']
            with self.assertRaises(config.ConfigurationError):
                config.configure(value)

    def test_scenario_accepts_bounded_read_but_rejects_polling_tag_or_transition(self):
        value = scenario()
        step = value['steps'][0]
        step['assert'] = [{'path': 'observations.enabled', 'equals': True}]
        scenarios.validate(value)
        step['poll'] = True
        scenarios.validate(value)
        for change in ({'tag': 'before'}, {'baseline': 'before'}, {'haptics': True},
                       {'transition': 'new-body', 'baseline': 'before'}):
            modified = copy.deepcopy(value)
            modified['steps'][0]['args'].update(change)
            with self.assertRaises(ValueError):
                scenarios.validate(modified)

    def test_local_dispatch_keeps_original_deadline_and_does_not_use_a_new_endpoint(self):
        session = runner.Session.__new__(runner.Session)
        session.state = {'phase': 'subject'}
        session.heartbeat_failed = threading.Event()
        session.log = Mock()
        deadline = time.monotonic() + 5
        args = {'select': {'enabled': 'frame.holstersEnabled'}}
        result = {'observations': {'enabled': True}}
        with patch('skyrim_autotest.native14_live.execute', return_value=result) as execute:
            with patch.object(runner, 'request') as request:
                self.assertEqual(session.tool('native14', args, deadline=deadline), result)
                execute.assert_called_once_with(session, args, deadline)
                request.assert_not_called()

    def test_missing_policy_or_se_target_is_refused_before_recovery_setup_and_launch(self):
        before = config.P.snapshot()
        self.addCleanup(lambda: setattr(config.P, 'value', before))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scenario.json'
            test = scenario()
            test['steps'][0]['assert'] = [{'path': 'available', 'equals': True}]
            path.write_text(json.dumps(test), encoding='utf-8')
            for edition in ('vr', 'se'):
                for section in ('steps', 'postSteps'):
                    with self.subTest(edition=edition, section=section):
                        chosen = copy.deepcopy(test)
                        if section == 'postSteps':
                            chosen['postSteps'] = chosen['steps']
                            chosen['steps'] = [{'name': 'Unreached generic read', 'tool': 'inspect',
                                               'args': {'kind': 'scene'}, 'assert': [
                                                   {'path': 'playerLoaded', 'equals': True}]}]
                        path.write_text(json.dumps(chosen), encoding='utf-8')
                        config.P.value = config.configure(config.template(edition))
                        with patch.object(runner, 'recover') as recover:
                            with patch.object(runner, 'preflight') as preflight:
                                with patch.object(runner.Session, 'setup') as setup:
                                    with patch.object(runner.Session, 'launch') as launch:
                                        with self.assertRaises(ValueError):
                                            runner.run('not-used', path)
                                        recover.assert_not_called()
                                        preflight.assert_not_called()
                                        setup.assert_not_called()
                                        launch.assert_not_called()

    def test_combined_config_scenario_check_is_offline_and_checks_policy(self):
        before = config.P.snapshot()
        self.addCleanup(lambda: setattr(config.P, 'value', before))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_path, scenario_path = root / 'config.json', root / 'scenario.json'
            value = config.template('vr')
            test = scenario()
            test['steps'][0]['assert'] = [{'path': 'available', 'equals': True}]
            scenario_path.write_text(json.dumps(test), encoding='utf-8')
            config_path.write_text(json.dumps(value), encoding='utf-8')
            output = io.StringIO()
            with patch.object(runner, 'recover') as recover:
                with patch.object(runner, 'preflight') as preflight:
                    with contextlib.redirect_stdout(output):
                        code = cli.main(['--config', str(config_path), 'config-check',
                                         '--scenario', str(scenario_path)])
                    self.assertEqual(code, 2)
                    value['native14_live'] = policy(root)
                    config_path.write_text(json.dumps(value), encoding='utf-8')
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = cli.main(['--config', str(config_path), 'config-check',
                                         '--scenario', str(scenario_path)])
                    result = json.loads(output.getvalue())
                    self.assertEqual(code, 0)
                    self.assertIs(result['scenarioValid'], True)
                    self.assertEqual(result['reservedRestarts'], 0)
                    recover.assert_not_called()
                    preflight.assert_not_called()


if __name__ == '__main__':
    unittest.main()
