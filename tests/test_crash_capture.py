"""Owned fake processes exercise the capture lifecycle without a game/debug attach."""
import copy
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import crash_capture as capture


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        for name in ('cdb.exe', 'dbgeng.dll', 'dbghelp.dll'):
            (self.tools / name).write_bytes(name.encode())
        def pin(name):
            path = self.tools / name
            return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        executable = pin('cdb.exe')
        self.config = {'provider': 'cdb', 'executable': executable['path'], 'sha256': executable['sha256'],
            'supportFiles': [pin('dbgeng.dll'), pin('dbghelp.dll')], 'maximumAttachSeconds': .1}
        self.game = {'pid': 101, 'birth': 1234, 'path': str(self.root / 'SkyrimSE.exe')}
        self.debugger = {'pid': 202, 'birth': 5678, 'path': executable['path']}
        self.live = {101: self.game, 202: self.debugger}
        self.process = SimpleNamespace(pid=202, poll=Mock(return_value=None))
        self.session = SimpleNamespace(dir=self.root, save=Mock(), log=Mock(),
            state={'configuration': {'game_edition': 'se', 'crash_capture': self.config},
                'game': copy.deepcopy(self.game), 'port': 8920,
                'owned': [{'role': 'game', 'identity': copy.deepcopy(self.game)}]})
        self.health = {'ok': True, 'pid': 101, 'exe': 'SkyrimSE.exe', 'vr': False, 'frame': 70}
        self.ready = True
        def spawn(*_, **kwargs):
            self.assertEqual(self.session.state['crashCapture']['status'], 'attach-intent')
            self.assertTrue(self.session.save.called)
            if self.ready:
                (Path(kwargs['cwd']) / 'debugger.log').write_bytes(capture.READY + b'\n')
            return self.process
        patches = [patch.object(capture.subprocess, 'Popen', side_effect=spawn),
            patch.object(capture.native, 'identity', side_effect=lambda pid: self.live.get(pid)),
            patch.object(capture.native, 'processes', side_effect=lambda:
                [{'pid': 999, 'parent': 0, 'name': 'offline-owner.exe'}] +
                [{'pid': pid, 'parent': 999, 'name': Path(identity['path']).name}
                 for pid, identity in self.live.items()]),
            patch.object(capture.native, 'terminate'),
            patch('skyrim_autotest.runner.request', return_value=self.health)]
        self.spawn, self.identity, self.inventory, self.terminate, self.request = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def test_disabled_is_noop_and_strict_configuration_rejects_arbitrary_arguments(self):
        self.session.state['configuration'].pop('crash_capture')
        self.assertIsNone(capture.start(self.session))
        self.assertIsNone(capture.stop(self.session))
        self.spawn.assert_not_called()
        for update in ({'arguments': ['-pn', 'SkyrimSE.exe']}, {'maximumAttachSeconds': True},
                       {'maximumAttachSeconds': 16}, {'sha256': 'bad'}, {'provider': 'other'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                capture.validate_config({**self.config, **update})
        bad = copy.deepcopy(self.config)
        bad['supportFiles'][1] = bad['supportFiles'][0]
        with self.assertRaises(ValueError):
            capture.validate_config(bad)

    def test_ready_has_exact_process_fresh_health_fixed_commands_and_no_shell(self):
        value = capture.start(self.session)
        self.assertEqual(value['status'], 'ready')
        self.assertEqual(value['attachRequests'], 1)
        self.assertEqual(value['debugger'], self.debugger)
        self.assertIn({'role': 'crash-capture', 'identity': self.debugger}, self.session.state['owned'])
        args, kwargs = self.spawn.call_args
        argv = args[0]
        self.assertEqual(argv[-2:], ['-p', '101'])
        self.assertTrue({'-pd', '-G', '-sins', '-netsyms:no', '-noshell', '-nosqm'} <= set(argv))
        self.assertFalse(kwargs['shell'])
        self.assertEqual(kwargs['stdin'], capture.subprocess.DEVNULL)
        if capture.os.name == 'nt':
            self.assertEqual(kwargs['creationflags'], capture.subprocess.CREATE_NO_WINDOW)
        self.assertFalse({'-pn', '-o', '-iae', '-g'} & set(argv))
        self.request.assert_called_once()
        self.assertEqual(self.request.call_args.args, (8920, 'api/health'))
        script = Path(value['script']['path']).read_text()
        self.assertIn('sxd -c "" -c2', script)
        self.assertIn('.dump /mA second-chance.dmp', script)
        self.assertIn('; gn" av', script)
        # Named built-in filters override wildcard commands: C0000409 must
        # explicitly retain its own second-chance capture, without handling it.
        self.assertIn('; gn" sbo', script)
        self.assertGreater(script.index('; gn" sbo'), script.index('; gn" *'))
        self.assertNotIn('gh', script)
        self.assertTrue(script.endswith('g\n'))
        self.terminate.assert_not_called()

    def test_tool_pin_failure_and_unowned_or_vr_target_never_spawn(self):
        (self.tools / 'dbgeng.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'pin changed'):
            capture.start(self.session)
        self.spawn.assert_not_called()
        self.session.state['configuration']['game_edition'] = 'vr'
        with self.assertRaises(ValueError):
            capture.start(self.session)
        self.spawn.assert_not_called()

    def test_lost_ready_times_out_once_without_health_or_reattach(self):
        self.ready = False
        self.config['maximumAttachSeconds'] = .015
        with self.assertRaises(TimeoutError):
            capture.start(self.session)
        self.assertEqual(self.spawn.call_count, 1)
        self.assertEqual(self.session.state['crashCapture']['status'], 'attach-failed')
        self.request.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'no reattach'):
            capture.start(self.session)
        self.assertEqual(self.spawn.call_count, 1)
        self.terminate.assert_not_called()

    def test_debugger_exits_or_foreign_identity_never_admitted_or_killed(self):
        self.process.poll.return_value = 2
        with self.assertRaisesRegex(RuntimeError, 'exited before'):
            capture.start(self.session)
        self.request.assert_not_called()
        self.terminate.assert_not_called()

    def test_game_identity_change_during_health_is_terminal(self):
        def health(*_, **__):
            self.live[101] = {**self.game, 'birth': 9999}
            return self.health
        self.request.side_effect = health
        with self.assertRaisesRegex(RuntimeError, 'exact already owned'):
            capture.start(self.session)
        self.assertFalse(self.session.state['crashCapture']['ready'])
        self.terminate.assert_not_called()

    def test_health_wrong_pid_is_unavailable_not_success(self):
        self.request.return_value = {**self.health, 'pid': 999}
        with self.assertRaisesRegex(RuntimeError, 'Fresh DevBench'):
            capture.start(self.session)
        self.terminate.assert_not_called()

    def test_stop_refuses_live_game_and_never_kills_target(self):
        capture.start(self.session)
        with self.assertRaisesRegex(RuntimeError, 'confirmed owned game end'):
            capture.stop(self.session)
        self.terminate.assert_not_called()

    def test_normal_debugger_exit_preserves_logs_and_actual_dump_hash(self):
        value = capture.start(self.session)
        dump = Path(value['directory']) / 'second-chance.dmp'
        dump.write_bytes(b'offline fake dump bytes')
        self.live.clear()
        self.process.poll.return_value = 0
        result = capture.stop(self.session)
        self.assertEqual(result['status'], 'stopped')
        self.assertTrue(result['dumpObserved'])
        self.assertFalse(result['debuggerForcedStop'])
        self.assertEqual(next(x for x in result['artifacts'] if x['path'] == str(dump))['sha256'],
                         hashlib.sha256(dump.read_bytes()).hexdigest())
        self.assertIn('debugger-output.log', [Path(x['path']).name for x in result['artifacts']])
        self.assertEqual(capture.stop(self.session), result)
        self.terminate.assert_not_called()

    def test_only_exact_debugger_can_be_closed_after_game_end(self):
        capture.start(self.session)
        del self.live[101]
        def terminate(identity):
            self.assertEqual(identity, self.debugger)
            del self.live[202]
        self.terminate.side_effect = terminate
        with patch.object(capture.time, 'monotonic', side_effect=[0, 3, 3, 3]):
            result = capture.stop(self.session)
        self.assertTrue(result['debuggerForcedStop'])
        self.terminate.assert_called_once_with(self.debugger)

    def test_reused_debugger_pid_is_foreign_and_left_untouched(self):
        capture.start(self.session)
        del self.live[101]
        self.live[202] = {**self.debugger, 'birth': 9999}
        capture.stop(self.session)
        self.terminate.assert_not_called()

    def test_unavailable_process_inventory_never_proves_game_death(self):
        capture.start(self.session)
        del self.live[101]
        for invalid in ([], None, [{'pid': 999}], [{'pid': True, 'name': 'bad', 'parent': 0}]):
            self.inventory.side_effect = None
            self.inventory.return_value = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(RuntimeError, 'inventory unavailable'):
                capture.stop(self.session)
        self.terminate.assert_not_called()

    def test_unowned_game_and_duplicate_helper_ownership_are_refused(self):
        self.session.state['owned'] = []
        with self.assertRaisesRegex(RuntimeError, 'exact already owned'):
            capture.start(self.session)
        self.spawn.assert_not_called()
        self.session.state['owned'] = [{'role': 'game', 'identity': self.game},
                                     {'role': 'crash-capture', 'identity': self.debugger}]
        with self.assertRaisesRegex(RuntimeError, 'duplicate process ownership'):
            capture.start(self.session)
        self.terminate.assert_not_called()

    def test_missing_debugger_identity_cannot_authorize_cleanup(self):
        self.live[202] = {**self.debugger, 'path': str(self.root / 'foreign.exe')}
        with self.assertRaisesRegex(RuntimeError, 'executable identity mismatch'):
            capture.start(self.session)
        del self.live[101]
        with self.assertRaisesRegex(RuntimeError, 'ownership unavailable'):
            capture.stop(self.session)
        self.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
