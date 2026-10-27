"""Real temporary loopback endpoints; no game, live database or child process."""
from contextlib import ExitStack, closing, nullcontext
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import interactive, runner
from skyrim_autotest.command_bus import APPLICATION_ID, BusError, CommandBus, dispatch
from skyrim_autotest.command_bus_http import CommandHTTPClient, CommandHTTPServer
from skyrim_autotest.command_endpoint import ManagedCommandEndpoint, managed_endpoint


TOKEN = 'offline-endpoint-token-with-at-least-32-characters'


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.config = self.root / 'channel.json'
        (self.root / 'token').write_text(TOKEN, encoding='ascii')
        self.config.write_text(json.dumps({'schemaVersion': 1, 'database': str(self.root / 'bus.sqlite3'),
            'tokenFile': str(self.root / 'token'), 'host': '127.0.0.1', 'port': self.port}), encoding='utf-8')
        self.settings = {'channelConfig': str(self.config), 'maximumSeconds': 2,
            'allowedTools': ['inspect'], 'sourceId': 'operator.actions', 'manageCommandEndpoint': True}

    def external_server(self, database=None, token=TOKEN):
        bus = CommandBus(database or self.root / 'bus.sqlite3')
        server = CommandHTTPServer(('127.0.0.1', self.port), bus, token)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join(3)
        self.addCleanup(stop)
        return server

    def test_owned_server_has_durable_identity_and_closes_only_after_context(self):
        with managed_endpoint(self.settings) as endpoint:
            self.assertEqual(endpoint.mode, 'owned')
            proof = CommandHTTPClient(self.config).call('identity', {})
            self.assertEqual(proof, endpoint.bus.identity())
            self.assertEqual(proof, CommandBus(self.root / 'bus.sqlite3').identity())
            self.assertEqual(set(endpoint.metadata()), {'mode', 'host', 'port', 'channelId', 'ready'})
            self.assertNotIn(TOKEN, json.dumps(endpoint.metadata()))
            thread = endpoint.thread
        self.assertFalse(thread.is_alive())
        with self.assertRaises(OSError):
            CommandHTTPClient(self.config, timeout=.2).call('identity', {})

    def test_same_database_adoption_survives_context_close(self):
        server = self.external_server()
        with managed_endpoint(self.settings) as endpoint:
            self.assertEqual(endpoint.mode, 'adopted')
            self.assertIsNone(endpoint.server)
            expected = endpoint.identity
        self.assertEqual(CommandHTTPClient(self.config).call('identity', {}), expected)
        self.assertEqual(server.bus.status()['sessions'], [])

    def test_foreign_database_occupied_port_is_refused_and_server_survives(self):
        server = self.external_server(self.root / 'foreign.sqlite3')
        with self.assertRaisesRegex(BusError, 'identity/readiness'):
            with managed_endpoint(self.settings):
                self.fail('foreign receiver admitted')
        self.assertEqual(CommandHTTPClient(self.config).call('identity', {}), server.bus.identity())
        self.assertNotEqual(server.bus.identity(), CommandBus(self.root / 'bus.sqlite3').identity())

    def test_copied_database_same_uuid_and_token_is_not_selected_database(self):
        original = CommandBus(self.root / 'bus.sqlite3')
        clone = self.root / 'clone.sqlite3'
        with closing(sqlite3.connect(original.database)) as source, closing(sqlite3.connect(clone)) as destination:
            source.backup(destination)
        server = self.external_server(clone)
        self.assertEqual(server.bus.identity()['channelId'], original.identity()['channelId'])
        self.assertNotEqual(server.bus.identity()['databaseLocationSha256'], original.identity()['databaseLocationSha256'])
        with self.assertRaisesRegex(BusError, 'identity/readiness'):
            with managed_endpoint(self.settings): self.fail('copied database admitted')
        self.assertEqual(CommandHTTPClient(self.config).call('identity', {}), server.bus.identity())

    def test_authentication_and_unsupported_old_receiver_refused_without_stop(self):
        server = self.external_server(token='other-endpoint-token-with-at-least-32-characters')
        with self.assertRaises(BusError):
            with managed_endpoint(self.settings):
                self.fail('wrong token admitted')
        server.token = TOKEN
        import skyrim_autotest.command_bus_http as http_module
        original = http_module.dispatch
        def legacy(bus, operation, arguments):
            if operation == 'identity': raise BusError('Unknown operation', 'not_found', 404)
            return original(bus, operation, arguments)
        with patch.object(http_module, 'dispatch', side_effect=legacy), self.assertRaises(BusError):
            with managed_endpoint(self.settings): self.fail('unsupported receiver admitted')
        self.assertEqual(CommandHTTPClient(self.config).call('status', {}), server.bus.status())

    def test_dead_endpoint_stops_before_interactive_ready_without_restart(self):
        with managed_endpoint(self.settings) as endpoint:
            endpoint.close()
            session = Mock()
            session.state = {'id': 'owned', 'gameplayBootstrap': {'completed': True}}
            session.command_endpoint = endpoint
            with self.assertRaises(BusError): interactive.run(session, self.settings)
            self.assertNotIn('interactiveSession', session.state)
            session.phase.assert_not_called()
            self.assertIsNone(endpoint.server)

    def test_ready_action_session_accepts_http_finish_on_managed_endpoint(self):
        with managed_endpoint(self.settings) as endpoint:
            session = Mock()
            session.state = {'id': 'owned', 'gameplayBootstrap': {'completed': True}, 'game': {'pid': 123}}
            session.command_endpoint = endpoint
            session.heartbeat_failed = threading.Event()
            submitted = []
            def deliver():
                if session.state.get('interactiveSession', {}).get('ready') and not submitted:
                    submitted.append(CommandHTTPClient(self.config).call('submit', {
                        'sessionId': session.state['interactiveSession']['sessionId'],
                        'sourceId': 'operator.actions', 'sourceEventId': 'offline-one-finish',
                        'kind': 'text', 'text': json.dumps({'schemaVersion': 1, 'operation': 'finish'})}))
            session.save.side_effect = deliver
            with patch.object(interactive.native, 'alive', return_value=True):
                result = interactive.run(session, self.settings)
            self.assertEqual(result['reason'], 'owner-finished')
            self.assertEqual(result['commandEndpoint'], endpoint.metadata())
            self.assertEqual(len(submitted), 1)
            self.assertEqual(endpoint.bus.status('game-owned')['commands'], {'completed': 1})

    def test_channel_change_is_refused(self):
        with managed_endpoint(self.settings) as endpoint:
            (self.root / 'token').write_text('replacement-token-with-at-least-32-characters', encoding='ascii')
            with self.assertRaises(BusError): endpoint.check()

    def test_schema1_extension_preserves_existing_queue_and_foreign_guard(self):
        bus = CommandBus(self.root / 'bus.sqlite3')
        bus.create_session('existing')
        bus.bind('existing', {'provider': 'offline', 'conversationId': 'existing', 'agentId': 'test'})
        bus.submit('existing', 'operator.actions', 'one', 'text', 'read')
        with closing(sqlite3.connect(bus.database)) as con:
            con.execute('DROP TABLE channel_metadata')
            con.commit()
        reopened = CommandBus(bus.database)
        self.assertEqual(reopened.status('existing')['commands'], {'received': 1})
        self.assertEqual(dispatch(reopened, 'identity', {}), CommandBus(bus.database).identity())
        with closing(sqlite3.connect(bus.database)) as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(con.execute('PRAGMA application_id').fetchone()[0], APPLICATION_ID)
        foreign = self.root / 'unowned.sqlite3'
        with closing(sqlite3.connect(foreign)) as con:
            con.execute('CREATE TABLE important(value TEXT)')
            con.commit()
        with self.assertRaises(BusError): CommandBus(foreign)
        with closing(sqlite3.connect(foreign)) as con:
            self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('important',)])

    def test_explicit_boolean_and_legacy_no_flag_never_reads_channel(self):
        for value in (1, 'true', None):
            with self.assertRaises(interactive.InteractiveError): interactive.validate(dict(self.settings, manageCommandEndpoint=value))
        for settings in (None, {}, dict(self.settings, manageCommandEndpoint=False)):
            with patch('skyrim_autotest.command_endpoint.load_config') as read:
                with managed_endpoint(settings) as endpoint: self.assertIsNone(endpoint)
                read.assert_not_called()

    def runner_patches(self, settings):
        stack = ExitStack()
        self.addCleanup(stack.close)
        scenario = self.root / 'scenario.json'
        scenario.write_text(json.dumps({'schemaVersion': 1, 'cell': 'QASmoke', 'steps': []}), encoding='utf-8')
        value = {'schemaVersion': 1, 'game_edition': 'se', 'runtime': str(self.root / 'runtime'), 'interactive_session': settings}
        stack.enter_context(patch.object(runner.P, 'value', value))
        stack.enter_context(patch.object(runner, 'configure'))
        stack.enter_context(patch.object(runner, 'recover'))
        stack.enter_context(patch.object(runner.native, 'SessionMutex', return_value=nullcontext()))
        stack.enter_context(patch('skyrim_autotest.scenarios.validate'))
        stack.enter_context(patch('skyrim_autotest.editions.validate_scenario'))
        stack.enter_context(patch.object(runner, 'RUNS', self.root / 'runs'))
        stack.enter_context(patch.object(runner.native, 'identity', return_value={'pid': 123}))
        preflight = stack.enter_context(patch.object(runner, 'preflight', return_value={}))
        launch = stack.enter_context(patch.object(runner.Session, 'launch'))
        return scenario, preflight, launch

    def test_runner_refuses_foreign_receiver_before_preflight_setup_or_launch(self):
        self.external_server(self.root / 'foreign.sqlite3')
        scenario, preflight, launch = self.runner_patches(self.settings)
        with patch.object(runner.Session, 'setup') as setup, patch.object(runner.subprocess, 'Popen') as child:
            with self.assertRaises(BusError): runner.run('Fixture', scenario)
            preflight.assert_not_called()
            setup.assert_not_called()
            launch.assert_not_called()
            child.assert_not_called()

    def test_runner_retains_owned_endpoint_through_cleanup_finish_and_report(self):
        scenario, _, _ = self.runner_patches(self.settings)
        stages = []
        client = CommandHTTPClient(self.config)
        def proof(stage):
            stages.append(stage)
            self.assertEqual(client.call('identity', {})['schemaVersion'], 1)
        class FakeSession:
            def __init__(self, directory, state): self.state, self.dir = state, directory
            def save(self): pass
            def log(self, *args, **kwargs): pass
            def heartbeat(self): pass
            def setup(self): proof('setup')
            def launch(self):
                proof('launch')
                raise runner.Blocked('offline stop before game')
            def cleanup(self):
                proof('cleanup')
                self.state['restored'] = True
            def finish_heartbeat(self, thread):
                thread.join(1)
                proof('finish')
            def report(self): proof('report')
            def reopen_mo2(self): proof('reopen')
        with patch.object(runner, 'Session', FakeSession), patch.object(runner.subprocess, 'Popen'), patch('builtins.print'):
            self.assertEqual(runner.run('Fixture', scenario), 1)
        self.assertEqual(stages, ['setup', 'launch', 'cleanup', 'finish', 'report', 'reopen'])
        with self.assertRaises(OSError): client.call('identity', {})

    def test_endpoint_loss_during_setup_prevents_runner_launch_and_cleanup_runs(self):
        scenario, _, _ = self.runner_patches(self.settings)
        stages = []
        class FakeSession:
            def __init__(self, directory, state): self.state, self.dir = state, directory
            def save(self): pass
            def log(self, *args, **kwargs): pass
            def heartbeat(self): pass
            def setup(self): self.command_endpoint.close()
            def launch(self): stages.append('UNEXPECTED-launch')
            def cleanup(self):
                stages.append('cleanup')
                self.state['restored'] = True
            def finish_heartbeat(self, thread): thread.join(1)
            def report(self): pass
            def reopen_mo2(self): pass
        with patch.object(runner, 'Session', FakeSession), patch.object(runner.subprocess, 'Popen'), patch('builtins.print'):
            self.assertEqual(runner.run('Fixture', scenario), 1)
        self.assertEqual(stages, ['cleanup'])


if __name__ == '__main__': unittest.main()
