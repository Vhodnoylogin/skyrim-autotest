"""Exact-client shutdown/reopen and interrupted recovery; no programs launched."""
import contextlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from skyrim_autotest import native, steam_restore as steam, config


class SteamRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root/'steam.exe'; self.exe.write_bytes(b'client')
        self.before = {'pid': 10, 'birth': 100, 'path': str(self.exe)}
        self.after = dict(self.before, pid=20, birth=200)
        self.runtime = self.root/'steamvr'
        self.driver = self.runtime/'drivers/null/bin/win64/driver_null.dll'
        self.driver.parent.mkdir(parents=True); self.driver.write_bytes(b'owned-driver')
        self.backup = self.root/'driver-original'; self.backup.write_bytes(b'original')
        self.session = SimpleNamespace(state={
            'preflight': {'runtime': str(self.runtime), 'steamClientRestart': {
                'identity': self.before, 'executableSha256': steam.digest(self.exe)}},
            'snapshots': [{'path':str(self.driver),'exists':True,'backup':str(self.backup),'sha256':steam.digest(self.backup)}],
            'driverBackend':'file','driverManifest':{'dllSha256':steam.digest(self.driver)}}, save=Mock(), log=Mock())
        self.current = [self.before]
        self.commands = []
        def launch(cmd):
            self.commands.append(cmd)
            self.current[:] = [] if '-shutdown' in cmd else [self.after]
        self.launcher = Mock(side_effect=launch)
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(steam, 'clients', side_effect=lambda _: list(self.current)))
        self.stack.enter_context(patch.object(native, 'alive', side_effect=lambda ident: ident in self.current))
        self.stack.enter_context(patch.object(native, 'modules', return_value=[str(self.driver)]))
        self.stack.enter_context(patch.object(steam, 'observe_module', return_value={'observed':True,'modulePath':str(self.driver),'elapsedSeconds':0}))
        self.stack.enter_context(patch.object(steam, 'idle_inventory', return_value={'helpers':[], 'runningAppHints':[]}))
        self.stack.enter_context(patch.object(steam, 'launch', self.launcher))
        self.stack.enter_context(patch.object(steam.time, 'sleep'))

    def test_opt_out_never_queries_or_closes_client(self):
        self.session.state['preflight'].pop('steamClientRestart')
        with patch.object(native, 'modules') as modules:
            steam.prepare(self.session); steam.reopen(self.session)
        modules.assert_not_called(); self.launcher.assert_not_called()

    def test_exact_loaded_owned_driver_shutdown_then_reopen_once_with_durable_intents(self):
        original_save=self.session.save
        def save():
            if self.commands:
                self.assertTrue(self.session.state['steamClientRestore']['shutdownRequested'])
            return original_save()
        self.session.save=save
        steam.prepare(self.session)
        self.assertEqual(self.commands, [[str(self.exe),'-shutdown']])
        state=self.session.state['steamClientRestore']
        self.assertTrue(state['shutdownObserved']); self.assertFalse(state['forced'])
        self.driver.write_bytes(b'original') # Ordinary verified file restoration.
        steam.reopen(self.session); steam.prepare(self.session); steam.reopen(self.session)
        self.assertEqual(self.commands, [[str(self.exe),'-shutdown'],[str(self.exe),'-silent']])
        self.assertEqual(state['after'],self.after)

    def test_same_driver_bytes_need_no_client_restart(self):
        self.driver.write_bytes(b'original')
        steam.prepare(self.session); self.launcher.assert_not_called()

    def test_issued_shutdown_waits_within_original_window_for_unidentified_exit_rows(self):
        with patch.object(steam, 'clients', side_effect=[[self.before], [self.before],
                steam.ClientInventoryUnavailable('teardown'), []]):
            steam.prepare(self.session)
        self.assertTrue(self.session.state['steamClientRestore']['shutdownObserved'])
        self.assertEqual(self.commands, [[str(self.exe), '-shutdown']])
        self.assertTrue(any(call.kwargs.get('absenceObserved') is False for call in self.session.log.call_args_list))

    def test_reopen_waits_for_available_new_identity_without_relaunch(self):
        steam.prepare(self.session)
        with patch.object(steam, 'clients', side_effect=[[], steam.ClientInventoryUnavailable('starting'), [self.after]]):
            steam.reopen(self.session)
        self.assertTrue(self.session.state['steamClientRestore']['reopened'])
        self.assertEqual(self.commands, [[str(self.exe), '-shutdown'], [str(self.exe), '-silent']])

    def test_client_without_observed_owned_module_is_left_alone(self):
        with patch.object(steam,'observe_module',return_value={'observed':False}):steam.prepare(self.session)
        self.launcher.assert_not_called()

    def test_unavailable_module_inventory_never_closes_client(self):
        with patch.object(steam,'observe_module',side_effect=OSError('access denied')):
            with self.assertRaises(OSError):steam.prepare(self.session)
        self.launcher.assert_not_called()

    def test_changed_preflight_client_and_driver_and_backup_refuse_shutdown(self):
        for change in ['client','driver','backup','exe']:
            with self.subTest(change=change):
                self.current[:]=[self.after] if change=='client' else [self.before]
                self.driver.write_bytes(b'foreign' if change=='driver' else b'owned-driver')
                self.backup.write_bytes(b'corrupt' if change=='backup' else b'original')
                self.exe.write_bytes(b'changed-client' if change=='exe' else b'client')
                with self.assertRaises(RuntimeError):steam.prepare(self.session)
        self.launcher.assert_not_called()

    def test_shutdown_intent_is_never_replayed_after_interruption(self):
        self.session.state['steamClientRestore']={'shutdownRequested':True,'shutdownObserved':False}
        with self.assertRaisesRegex(RuntimeError,'never replay'):steam.prepare(self.session)
        self.launcher.assert_not_called()
        self.current[:]=[];steam.prepare(self.session)
        self.assertTrue(self.session.state['steamClientRestore']['shutdownObserved'])
        self.launcher.assert_not_called()

    def test_shutdown_timeout_preserves_request_and_never_force_kills(self):
        self.launcher.side_effect=None
        with patch.object(steam.time,'monotonic',side_effect=[0,46]),patch.object(native,'terminate') as terminate:
            with self.assertRaisesRegex(RuntimeError,'no force'):steam.prepare(self.session)
        self.assertTrue(self.session.state['steamClientRestore']['shutdownRequested'])
        self.assertFalse(self.session.state['steamClientRestore']['shutdownObserved'])
        terminate.assert_not_called();self.assertEqual(len(self.commands),0)
        self.assertEqual(self.launcher.call_count,1)

    def test_foreign_new_client_during_shutdown_recovery_blocks_writes(self):
        steam.prepare(self.session);self.current[:]=[self.after]
        with self.assertRaisesRegex(RuntimeError,'foreign client'):steam.prepare(self.session)

    def test_reopen_intent_observes_presence_without_replaying_launch(self):
        steam.prepare(self.session)
        self.session.state['steamClientRestore']['reopenRequested']=True
        self.current[:]=[self.after]
        steam.reopen(self.session)
        self.assertEqual(len(self.commands),1)
        self.assertTrue(self.session.state['steamClientRestore']['reopened'])

    def test_late_driver_sharing_violation_retries_only_after_observed_shutdown_once(self):
        error=PermissionError('mapped driver');error.winerror=32
        self.assertTrue(steam.retry_locked_driver(self.session,self.driver,error))
        self.assertTrue(self.session.state['steamClientRestore']['shutdownObserved'])
        self.assertFalse(steam.retry_locked_driver(self.session,self.driver,error))
        self.assertEqual(len(self.commands),1)

    def test_unrelated_file_error_or_unobserved_module_cannot_trigger_retry(self):
        error=PermissionError('mapped file');error.winerror=32
        self.assertFalse(steam.retry_locked_driver(self.session,self.backup,error))
        with patch.object(steam,'observe_module',return_value={'observed':False}):
            self.assertFalse(steam.retry_locked_driver(self.session,self.driver,error))
        self.launcher.assert_not_called()

    def test_interrupted_reopen_intent_with_no_client_never_replays(self):
        steam.prepare(self.session)
        self.session.state['steamClientRestore']['reopenRequested']=True
        with patch.object(steam.time,'monotonic',side_effect=[0,26]):
            with self.assertRaisesRegex(RuntimeError,'no launch replay'):steam.reopen(self.session)
        self.assertEqual(len(self.commands),1)


class IdleClientTests(unittest.TestCase):
    def setUp(self):
        self.exe=Path('C:/Steam/steam.exe').resolve()
        self.parent={'pid':10,'birth':100,'path':str(self.exe)}
        self.helper={'pid':11,'birth':101,'path':str(self.exe.parent/'bin/cef/steamwebhelper.exe')}

    def inventory(self, child=None, apps=None, extra=None):
        identities={10:self.parent,11:child or self.helper}
        rows=[{'pid':10,'parent':1,'name':'steam.exe'},{'pid':11,'parent':10,'name':'steamwebhelper.exe'}]+(extra or [])
        with patch.object(native,'processes',return_value=rows),patch.object(native,'identity',side_effect=identities.get), \
             patch.object(native,'alive',return_value=True),patch.object(steam,'running_apps',return_value=apps or []):
            return steam.idle_inventory(self.parent)

    def test_helper_requires_exact_directory_and_current_parent_birth(self):
        self.assertEqual(len(self.inventory()['helpers']),1)
        for child in [dict(self.helper,birth=99),dict(self.helper,path=str(self.exe.parent/'unrelated-game.exe')),
                      dict(self.helper,path=str(Path('C:/Elsewhere/steamwebhelper.exe').resolve()))]:
            with self.subTest(child=child),self.assertRaises(RuntimeError):self.inventory(child)

    def test_running_app_or_any_game_vr_blocks_graceful_request(self):
        with self.assertRaisesRegex(RuntimeError,'running applications'):self.inventory(apps=['1234'])
        with self.assertRaisesRegex(RuntimeError,'Game/VR'):self.inventory(extra=[{'pid':99,'parent':1,'name':'vrserver.exe'}])

    def test_opt_out_preflight_needs_no_steam_or_registry(self):
        with patch.object(steam,'clients') as clients:self.assertIsNone(steam.preflight({}))
        clients.assert_not_called()

    def test_vanished_client_row_requires_fresh_absent_inventory(self):
        row = {'pid': 10, 'name': 'steam.exe'}
        with patch.object(native, 'processes', side_effect=[[row], []]) as rows, \
             patch.object(native, 'identity', return_value=None), patch.object(steam.time, 'sleep'):
            self.assertEqual(steam.clients(self.exe), [])
        self.assertEqual(rows.call_count, 2)

    def test_persistently_unidentified_client_never_counts_as_absence(self):
        row = {'pid': 10, 'name': 'steam.exe'}
        with patch.object(native, 'processes', return_value=[row]) as rows, \
             patch.object(native, 'identity', return_value=None), patch.object(steam.time, 'sleep'), \
             self.assertRaisesRegex(RuntimeError, 'persisted'):
            steam.clients(self.exe)
        self.assertEqual(rows.call_count, 3)

    def test_resampled_client_still_requires_exact_executable_and_unique_identity(self):
        row = {'pid': 10, 'name': 'steam.exe'}
        foreign = dict(self.parent, path=str(self.exe.parent/'elsewhere/steam.exe'))
        with patch.object(native, 'processes', return_value=[row]), \
             patch.object(native, 'identity', side_effect=[None, foreign]), patch.object(steam.time, 'sleep'), \
             self.assertRaisesRegex(RuntimeError, 'Different'):
            steam.clients(self.exe)
        with patch.object(native, 'processes', return_value=[row, dict(row, pid=11)]), \
             patch.object(native, 'identity', side_effect=[self.parent, dict(self.parent, pid=11, birth=101)]), \
             self.assertRaisesRegex(RuntimeError, 'Multiple'):
            steam.clients(self.exe)

    def test_option_requires_explicit_path_and_boolean(self):
        base=config.template()
        for option in [{'allow_steam_client_restart':1},{'allow_steam_client_restart':True},
                       {'allow_steam_client_restart':True,'steam_exe':'some-other.exe'}]:
            with self.subTest(option=option),self.assertRaises(config.ConfigurationError):config.configure(dict(base,**option))

    def test_delayed_watchdog_module_is_observed_within_one_bounded_window(self):
        target=Path('C:/Steam/driver_null.dll')
        with patch.object(native,'modules',side_effect=[[],[str(target)]]), \
             patch.object(steam.time,'monotonic',side_effect=[0,.1,.25]),patch.object(steam.time,'sleep'):
            value=steam.observe_module(self.parent,target)
        self.assertTrue(value['observed']);self.assertEqual(value['elapsedSeconds'],.25)

    def test_absent_watchdog_module_observation_stops_without_shutdown(self):
        with patch.object(native,'modules',return_value=[]), \
             patch.object(steam.time,'monotonic',side_effect=[0,9,9]),patch.object(steam.time,'sleep') as sleep:
            value=steam.observe_module(self.parent,Path('C:/Steam/driver_null.dll'))
        self.assertFalse(value['observed']);sleep.assert_not_called()


if __name__=='__main__':unittest.main()
