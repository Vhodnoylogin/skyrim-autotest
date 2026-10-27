"""Interactive loop uses fake time/game and a real temporary durable bus."""
import json
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from skyrim_autotest import config, interactive
from skyrim_autotest.command_bus import CommandBus


class Clock:
    def __init__(self):
        self.now = 0
        self.callback = lambda: None
    def monotonic(self):
        return self.now
    def sleep(self, duration):
        self.now += duration
        self.callback()


class Session:
    def __init__(self, run_id='fresh-run'):
        self.state = {'id': run_id, 'game': {'pid': 123, 'birth': 456, 'path': 'owned-game.exe'},
            'configuration': {'game_edition': 'se'}, 'gameplayBootstrap': {'completed': True}}
        self.heartbeat_failed = threading.Event()
        self.logs, self.calls, self.phases = [], [], []
        self.actions, self.held = [], []
        self.keyboard_ready = True
        self.scene = {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}}
        self.menus = {'messageBoxOpen': False, 'openMenus': [], 'menuStates': []}
        self.on_save = lambda: None
        self.on_tool = lambda: {'observed': True}
    def save(self):
        self.on_save()
    def phase(self, name, seconds):
        self.phases.append((name, seconds))
    def log(self, kind, **details):
        self.logs.append((kind, details))
    def tool(self, name, args, timeout, deadline):
        self.calls.append((name, args, timeout, deadline))
        if name == 'inspect' and args == {'kind': 'scene'}: return self.scene
        if name == 'menu': return self.menus
        if name == 'input' and args.get('action') == 'capabilities':
            return {'contract': {'name': 'devbench.input', 'version': {'major': 2, 'minor': 0}},
                'capabilities': {'keyboard': {'version': 1, 'available': True, 'ready': self.keyboard_ready,
                    'injection': 'Skyrim.BSInputEventQueue', 'encoding': 'DirectInputScanCode',
                    'actions': ['down', 'up', 'status', 'releaseAll'],
                    'keys': [{'key': key.lower()} for key in ('W', 'A', 'S', 'D', 'SPACE')]}}}
        if name == 'input' and args.get('action') == 'releaseAll':
            self.held = [row for row in self.held if row['owner'] != args['owner']]
            return {'contract': dict(interactive.INPUT_CONTRACT), 'device': 'keyboard', 'action': 'releaseAll', 'owner': args['owner'], 'released': [], 'failed': [], 'pending': []}
        if name == 'input' and args.get('action') == 'status':
            return {'contract': dict(interactive.INPUT_CONTRACT), 'device': 'keyboard', 'ready': True, 'held': list(self.held)}
        if name == 'input' and args.get('action') == 'down':
            self.actions.append((name, args))
            self.held.append({'owner': args['owner'], 'key': args['key']})
        return self.on_tool()


class InteractiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'channel.json'
        self.path.write_text(json.dumps({'schemaVersion': 1, 'database': str(self.root / 'commands.sqlite3'),
            'tokenFile': str(self.root / 'channel.token'), 'claimTimeoutSeconds': 300}), encoding='utf-8')
        self.bus = CommandBus(self.root / 'commands.sqlite3')
        self.settings = {'channelConfig': str(self.path), 'maximumSeconds': 2,
                         'allowedTools': ['inspect', 'input', 'platform', 'papyrus'], 'sourceId': 'operator.actions'}
        self.session, self.clock = Session(), Clock()
        self.session.dir = self.root / 'run'
        self.session.dir.mkdir()
        self.sent = set()
    def tearDown(self):
        self.temp.cleanup()
    def send(self, event, request=None, source='operator.actions', kind='text', target=None):
        if event in self.sent:
            return
        self.sent.add(event)
        session_id = target or self.session.state['interactiveSession']['sessionId']
        payload = request or {'schemaVersion': 1, 'operation': 'finish'}
        return self.bus.submit(session_id, source, event, kind,
                               payload if isinstance(payload, str) else json.dumps(payload))
    def action(self):
        return {'schemaVersion': 1, 'operation': 'tool', 'tool': 'input',
            'args': {'device': 'keyboard', 'action': 'down', 'key': 'W',
                     'owner': 'autotest-' + self.session.state['id'], 'maxHoldMs': 200}, 'timeoutSeconds': .5}
    def binding_policy(self):
        return {'schemaVersion': 1, 'fixtureActorBases': ['0x00000456'], 'allowedRaceForms': ['0x00013746'],
            'bindings': [{'id': 'npc_race', 'script': 'Actor', 'function': 'SetRace', 'scope': 'member',
                'params': ['race'], 'returnType': 'none', 'effect': 'mutate', 'actorSelf': True,
                'actorArgs': [], 'raceArgs': [0], 'completion': 'actor-race'}]}
    def binding_request(self):
        return {'schemaVersion': 1, 'operation': 'binding', 'bindingId': 'npc_race',
            'args': ['0x00013746'], 'self': {'reference': '0xFF000123', 'base': '0x00000456'}, 'timeoutSeconds': 1}
    def fixture_request(self):
        return {'schemaVersion': 1, 'operation': 'fixture-create',
            'request': {'tag': 'ownedNpcOne', 'base': '0x00000456', 'forwardGameUnits': 150, 'rightGameUnits': 0}, 'timeoutSeconds': 1}
    def run_loop(self, alive=True):
        with patch.object(interactive.time, 'monotonic', self.clock.monotonic), \
             patch.object(interactive.time, 'sleep', self.clock.sleep), \
             patch.object(interactive.native, 'alive', alive if callable(alive) else lambda _: alive):
            return interactive.run(self.session, self.settings)

    def test_delayed_requests_use_same_owned_session_and_finish_normally(self):
        def schedule():
            if self.clock.now >= .3:
                self.send('observe', {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect',
                                     'args': {'kind': 'scene'}, 'timeoutSeconds': .5})
            if self.clock.now >= .6:
                self.send('finish')
        self.clock.callback = schedule
        result = self.run_loop()
        self.assertEqual(result['reason'], 'owner-finished')
        self.assertFalse(result['ready'])
        self.assertEqual(result['sessionId'], 'game-fresh-run')
        self.assertEqual(result['binding'], {'provider': 'skyrim-autotest', 'conversationId': 'fresh-run', 'agentId': 'owned-game-executor'})
        self.assertEqual(len(self.session.calls), 1)
        self.assertGreaterEqual(self.clock.now, .6)
        self.assertEqual(len(self.session.phases), 1)
        self.assertEqual(self.bus.status(result['sessionId'])['commands'], {'completed': 2})

    def test_se_observer_read_uses_existing_owned_transport_once(self):
        args = {'kind':'world_observer','refs':['0x14'],'actors':True,
            'skee':{'refs':['0x14'],'morphs':['Zero']},'obody':{'refs':['0x14']},'timeoutMs':100}
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('observer', {'schemaVersion':1,'operation':'tool','tool':'inspect',
                    'args':args,'timeoutSeconds':.5})
                self.send('finish')
        self.session.on_save = ready
        result = self.run_loop()
        self.assertEqual(result['reason'],'owner-finished')
        self.assertEqual(len(self.session.calls),1)
        self.assertEqual(self.session.calls[0][:2],('inspect',args))
        self.assertEqual(self.session.actions,[])
        self.assertEqual(self.bus.status(result['sessionId'])['commands'],{'completed':2})

    def test_se_observer_read_cannot_smuggle_mutation_or_vr_provider(self):
        for extra in ({'command':'save'},{'physics':{'captureAction':'start'}},{'skee':{'refs':[20],'morphs':['x'],'set':1}}):
            args = {'kind':'world_observer','timeoutMs':100,**extra}
            request = {'schemaVersion':1,'operation':'tool','tool':'inspect','args':args,'timeoutSeconds':1}
            with self.assertRaises(interactive.InteractiveError):
                interactive._request(json.dumps(request),self.settings,self.session)
        self.session.state['configuration']['game_edition'] = 'vr'
        with self.assertRaises(interactive.InteractiveError):
            interactive._request(json.dumps({'schemaVersion':1,'operation':'tool','tool':'inspect',
                'args':{'kind':'world_observer','action':'capabilities'},'timeoutSeconds':1}),self.settings,self.session)
        self.assertEqual(self.session.calls,[])

    def test_one_delivered_mutation_and_duplicate_event_never_executes_twice(self):
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('move', self.action())
                self.send('finish')
        self.session.on_save = ready
        self.session.on_tool = lambda: self.bus.submit('game-fresh-run', 'operator.actions', 'move', 'text', json.dumps(self.action()))
        self.run_loop()
        self.assertEqual(len(self.session.actions), 1)
        kinds = [kind for kind, _ in self.session.logs]
        self.assertLess(kinds.index('interactive-action-delivered'), kinds.index('interactive-action-result'))
        events = self.bus.events('game-fresh-run', limit=100)['events']
        self.assertEqual(sum(item['type'] == 'command.delivered' for item in events), 2)

    def test_lost_outcome_stops_once_and_preserves_uncertain_record(self):
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('move', self.action())
                self.send('finish')
        self.session.on_save = ready
        def mutate_then_lose_outcome():
            raise TimeoutError('reply lost after native action')
        self.session.on_tool = mutate_then_lose_outcome
        with self.assertRaisesRegex(interactive.InteractiveError, 'reply lost'):
            self.run_loop()
        self.assertEqual(len(self.session.actions), 1)
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'received': 1, 'uncertain': 1})
        with self.assertRaisesRegex(interactive.InteractiveError, 'fresh owned run'):
            self.run_loop()
        self.assertEqual(len(self.session.actions), 1)

    def test_wrong_source_and_raw_asr_are_never_interpreted(self):
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('voice', 'provisional human words, never parsed', source='voice.capture', kind='asr.final')
                self.send('finish')
        self.session.on_save = ready
        self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})
        rejected = [details for kind, details in self.session.logs if kind == 'interactive-action-rejected']
        self.assertEqual(len(rejected), 1)
        self.assertFalse(rejected[0]['executed'])
        self.assertIn('raw ASR', rejected[0]['reason'])

    def test_malformed_and_unsupported_requests_are_rejected_without_ending_hold(self):
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('bad-json', 'not a machine JSON request')
                self.send('bad-tool', {'schemaVersion': 1, 'operation': 'tool', 'tool': 'console',
                    'args': {'action': 'exec', 'command': 'coc QASmoke'}, 'timeoutSeconds': 1})
        self.session.on_save = ready
        self.clock.callback = lambda: self.send('finish') if self.clock.now >= .3 else None
        self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        self.assertGreaterEqual(self.clock.now, .3)
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 3})
        rejected = [details for kind, details in self.session.logs if kind == 'interactive-action-rejected']
        self.assertEqual(len(rejected), 2)
        self.assertTrue(all(item['outcome'] == 'rejected' and item['executed'] is False for item in rejected))

    def test_old_action_session_is_never_consumed_and_same_run_cannot_reconnect(self):
        old = {'provider': 'skyrim-autotest', 'conversationId': 'old-run', 'agentId': 'owned-game-executor'}
        self.bus.create_session('game-old-run')
        self.bus.bind('game-old-run', old)
        self.bus.submit('game-old-run', 'operator.actions', 'old-command', 'text', json.dumps(self.action()))
        self.session.on_save = lambda: self.send('finish') if self.session.state.get('interactiveSession') else None
        self.run_loop()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.bus.status('game-old-run')['commands'], {'received': 1})
        self.session = Session()
        with self.assertRaisesRegex(interactive.InteractiveError, 'already exists'):
            self.run_loop()

    def test_finite_expiry_does_not_extend_phase_or_relaunch(self):
        self.settings['maximumSeconds'] = 1
        with self.assertRaisesRegex(interactive.InteractiveError, 'maximumSeconds expired'):
            self.run_loop()
        self.assertLess(self.clock.now, 1.11)
        self.assertEqual(len(self.session.phases), 1)
        self.assertEqual(self.session.calls, [])
        self.assertFalse(self.session.state['interactiveSession']['ready'])

    def test_game_exit_and_heartbeat_failure_stop_waiting(self):
        with self.assertRaisesRegex(interactive.InteractiveError, 'exited or changed'):
            self.run_loop(alive=lambda _: self.clock.now < .2)
        self.assertEqual(self.session.calls, [])
        self.session = Session('other-run')
        self.clock.callback = lambda: self.session.heartbeat_failed.set()
        with self.assertRaisesRegex(interactive.InteractiveError, 'heartbeat failed'):
            self.run_loop()

    def test_return_after_deadline_is_uncertain_and_never_replayed(self):
        self.session.on_save = lambda: self.send('move', self.action()) if self.session.state.get('interactiveSession') else None
        def late():
            self.clock.now += 1
            return {'nativeResult': 'may-have-applied'}
        self.session.on_tool = late
        with self.assertRaisesRegex(interactive.InteractiveError, 'after its deadline'):
            self.run_loop()
        self.assertEqual(len(self.session.actions), 1)
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'uncertain': 1})
        self.assertTrue(any(kind == 'interactive-action-result' for kind, _ in self.session.logs))

    def test_settings_are_explicit_and_validation_does_not_create_storage(self):
        self.assertNotIn('interactive_session', config.template('se'))
        for change in ({'maximumSeconds': True}, {'maximumSeconds': 14401}, {'sourceId': 'voice'},
                       {'allowedTools': ['console']}, {'channelConfig': 'relative.json'}):
            with self.subTest(change=change), self.assertRaises(interactive.InteractiveError):
                interactive.validate(dict(self.settings, **change))
        with patch.object(interactive, 'CommandBus', side_effect=AssertionError('validation opened storage')):
            self.assertEqual(interactive.validate(self.settings), self.settings)

    def test_malformed_raw_text_world_load_and_race_are_rejected_before_tool(self):
        forbidden = ['Move the player now', {'schemaVersion': 1, 'operation': 'tool', 'tool': 'console',
            'args': {'action': 'exec', 'command': 'coc QASmoke'}, 'timeoutSeconds': 1},
            {'schemaVersion': 1, 'operation': 'tool', 'tool': 'papyrus', 'args': {'action': 'call', 'script': 'Game', 'function': 'LoadGame'}, 'timeoutSeconds': 1},
            {'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform', 'args': {'operation': 'input.perform', 'request': {'action': 'load_game', 'saveTag': 'x', 'scope': 'owned-disposable-profile'}}, 'timeoutSeconds': 1},
            {'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform', 'args': {'operation': 'object.perform', 'request': {'action': 'set-race', 'actor': {'reference': '0x00000014', 'base': '0x00000007'}, 'race': '0x00013746'}}, 'timeoutSeconds': 1}]
        for request in forbidden:
            with self.subTest(request=request), self.assertRaises(ValueError):
                interactive._request(request if isinstance(request, str) else json.dumps(request), self.settings, self.session)
        self.assertEqual(self.session.calls, [])

    def test_guarded_morph_preset_request_keeps_exact_actor_and_existing_validator(self):
        self.settings['nativeBindings'] = self.binding_policy()
        request = {'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform', 'args': {'operation': 'object.perform',
            'request': {'action': 'assign-morph-preset', 'actor': {'reference': '0x00000123', 'base': '0x00000456'}, 'presetName': 'Exact preset'}}, 'timeoutSeconds': 1}
        self.assertEqual(interactive._request(json.dumps(request), self.settings, self.session), request)
        del request['args']['request']['actor']['base']
        with self.assertRaisesRegex(ValueError, 'exact reference and base'):
            interactive._request(json.dumps(request), self.settings, self.session)

    def test_common_bootstrap_is_mandatory(self):
        self.session.state['gameplayBootstrap']['completed'] = False
        with self.assertRaisesRegex(interactive.InteractiveError, 'completed common bootstrap'):
            self.run_loop()
        self.assertNotIn('interactiveSession', self.session.state)

    def test_minimum_lease_and_activation_or_menu_keys_are_refused(self):
        for change in ({'maxHoldMs': 99}, {'key': 'E'}, {'key': 'TAB'}):
            request = self.action()
            request['args'].update(change)
            with self.subTest(change=change), self.assertRaises(interactive.InteractiveError):
                interactive._request(json.dumps(request), self.settings, self.session)

    def test_actual_end_window_rejects_a_lease_without_any_input(self):
        self.settings['maximumSeconds'] = 1
        self.clock.now = 0
        def schedule():
            if self.clock.now >= .8:
                request = self.action()
                request['timeoutSeconds'] = 1
                request['args']['maxHoldMs'] = 1000
                self.send('too-late', request)
                self.send('finish')
        self.clock.callback = schedule
        self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        self.assertEqual(self.session.actions, [])
        rejected = [row for kind, row in self.session.logs if kind == 'interactive-action-rejected']
        self.assertEqual(len(rejected), 1)
        self.assertIn('lease budget', rejected[0]['reason'])

    def test_open_menu_rejects_mutation_and_keeps_same_hold_until_finish(self):
        self.session.menus = {'messageBoxOpen': False, 'openMenus': ['InventoryMenu'], 'menuStates': [
            {'name': 'InventoryMenu', 'available': True, 'alwaysOpen': False, 'pausesGame': True,
             'modal': False, 'usesCursor': True, 'usesMenuContext': True, 'freezeFramePause': False}]}
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('blocked-move', self.action())
        self.session.on_save = ready
        self.clock.callback = lambda: self.send('finish') if self.clock.now >= .3 else None
        self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        self.assertGreaterEqual(self.clock.now, .3)
        self.assertEqual(self.session.actions, [])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})

    def test_owner_release_and_status_readback_preserve_foreign_keys_on_finish(self):
        self.session.held = [{'owner': 'foreign-owner', 'key': 'SPACE'}]
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('move', self.action())
                self.send('finish')
        self.session.on_save = ready
        result = self.run_loop()
        self.assertEqual(result['keyboardRelease'], {'verified': True, 'owner': 'autotest-fresh-run'})
        self.assertEqual(self.session.held, [{'owner': 'foreign-owner', 'key': 'SPACE'}])
        cleanup = [(name, args) for name, args, _, _ in self.session.calls if args.get('action') == 'releaseAll']
        self.assertEqual(cleanup, [('input', {'device': 'keyboard', 'action': 'releaseAll', 'owner': 'autotest-fresh-run'})])

    def test_lost_action_still_releases_only_owned_keys(self):
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('move', self.action())
        self.session.on_save = ready
        def lost():
            raise TimeoutError('mutation receipt unknown')
        self.session.on_tool = lost
        with self.assertRaisesRegex(interactive.InteractiveError, 'mutation receipt unknown'):
            self.run_loop()
        self.assertEqual(self.session.actions[0][1]['key'], 'W')
        self.assertEqual(self.session.held, [])
        self.assertTrue(self.session.state['interactiveSession']['keyboardRelease']['verified'])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'uncertain': 1})

    def test_advertised_but_not_ready_keyboard_is_rejected_without_input(self):
        self.session.keyboard_ready = False
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('move', self.action())
                self.send('finish')
        self.session.on_save = ready
        self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        self.assertEqual(self.session.actions, [])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})

    def test_native_binding_is_disabled_without_policy_and_raw_selectors_are_refused(self):
        request = self.binding_request()
        with self.assertRaisesRegex(interactive.InteractiveError, 'disabled, unlisted'):
            interactive._request(json.dumps(request), self.settings, self.session)
        no_papyrus = dict(self.settings, nativeBindings=self.binding_policy(), allowedTools=['inspect'])
        with self.assertRaisesRegex(interactive.InteractiveError, 'papyrus tool allowlist'):
            interactive._request(json.dumps(request), no_papyrus, self.session)
        request['script'] = 'Actor'
        request['function'] = 'SetRace'
        with self.assertRaisesRegex(interactive.InteractiveError, 'Binding request requires'):
            interactive._request(json.dumps(request), self.settings, self.session)

    def test_unlisted_binding_is_completed_rejected_before_guarded_call(self):
        self.settings['nativeBindings'] = self.binding_policy()
        request = self.binding_request()
        request['bindingId'] = 'unlisted'
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('unlisted', request)
                self.send('finish')
        self.session.on_save = ready
        with patch('skyrim_autotest.interactive_bindings.guarded_call') as guarded:
            self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        guarded.assert_not_called()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})

    def test_typed_binding_delegates_once_after_delivery_then_accepts_finish(self):
        self.settings['nativeBindings'] = self.binding_policy()
        self.session.state['configuration']['interactive_session'] = interactive.validate(self.settings)
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('race', self.binding_request())
                self.send('finish')
        self.session.on_save = ready
        def guarded(session, arguments, deadline, policy):
            self.assertIs(session, self.session)
            self.assertEqual(arguments, {'bindingId': 'npc_race', 'args': ['0x00013746'],
                'self': {'reference': '0xFF000123', 'base': '0x00000456'}})
            self.assertLessEqual(deadline, self.clock.now + 1)
            self.assertEqual(policy, self.session.state['configuration']['interactive_session']['nativeBindings'])
            self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'delivered': 1, 'received': 1})
            return {'returned': None, 'raceObserved': '0x00013746', 'liveQualified': False}
        with patch('skyrim_autotest.interactive_bindings.guarded_call', side_effect=guarded) as call:
            self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        call.assert_called_once()
        self.assertEqual([name for name, _, _, _ in self.session.calls], ['inspect', 'menu'])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})

    def test_uncertain_typed_binding_outcome_stops_once_without_retry(self):
        self.settings['nativeBindings'] = self.binding_policy()
        self.session.state['configuration']['interactive_session'] = interactive.validate(self.settings)
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('race', self.binding_request())
                self.send('finish')
        self.session.on_save = ready
        with patch('skyrim_autotest.interactive_bindings.guarded_call', side_effect=TimeoutError('native binding outcome unknown')) as call:
            with self.assertRaisesRegex(interactive.InteractiveError, 'native binding outcome unknown'):
                self.run_loop()
        call.assert_called_once()
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'received': 1, 'uncertain': 1})

    def test_large_catalog_is_exact_external_evidence_before_compact_completion(self):
        catalog = {'presets': ['Actual Russian имя ' + str(index) + 'x' * 100 for index in range(400)]}
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('catalog', {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect', 'args': {'kind': 'mods'}, 'timeoutSeconds': 1})
                self.send('finish')
        self.session.on_save, self.session.on_tool = ready, lambda: catalog
        self.run_loop()
        artifacts = self.session.state['interactiveArtifacts']
        self.assertEqual(len(artifacts), 1)
        artifact = artifacts[0]
        raw = Path(artifact['path']).read_bytes()
        expected = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(raw, expected)
        self.assertEqual((artifact['sha256'], artifact['bytes'], artifact['format']), (hashlib.sha256(raw).hexdigest(), len(raw), 'json'))
        self.assertTrue(Path(artifact['path']).is_relative_to(self.session.dir / 'interactive-results'))
        result = next(item['data']['result'] for item in self.bus.events('game-fresh-run')['events']
                      if item['type'] == 'command.completed' and item['data']['result'].get('outcome') == 'result-recorded')
        self.assertEqual(result['evidence'], {key: artifact[key] for key in ('path', 'sha256', 'bytes', 'format')})
        self.assertNotIn('presets', result)
        self.assertEqual(len(self.session.calls), 1)

    def test_large_result_write_loss_preserves_uncertainty_without_retry(self):
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('catalog', {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect', 'args': {'kind': 'mods'}, 'timeoutSeconds': 1})
                self.send('finish')
        self.session.on_save, self.session.on_tool = ready, lambda: {'catalog': 'x' * 20000}
        with patch.object(interactive.os, 'fsync', side_effect=OSError('evidence disk write failed')):
            with self.assertRaisesRegex(interactive.InteractiveError, 'evidence disk write failed'):
                self.run_loop()
        self.assertEqual(len(self.session.calls), 1)
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'received': 1, 'uncertain': 1})
        self.assertEqual(self.session.state['interactiveArtifacts'], [])
        self.assertEqual(list((self.session.dir / 'interactive-results').iterdir()), [])

    def test_large_evidence_duplicate_verifies_bytes_and_never_overwrites(self):
        command_id = 'a' * 32
        result = {'catalog': 'x' * 20000}
        first = interactive._completion_result(self.session, command_id, result)
        raw = Path(first['evidence']['path']).read_bytes()
        self.assertEqual(interactive._completion_result(self.session, command_id, result), first)
        self.assertEqual(len(self.session.state['interactiveArtifacts']), 1)
        with self.assertRaisesRegex(interactive.InteractiveError, 'changed|different bytes'):
            interactive._completion_result(self.session, command_id, {'catalog': 'y' * 20000})
        self.assertEqual(Path(first['evidence']['path']).read_bytes(), raw)
        small = {'native': True}
        self.assertIs(interactive._completion_result(self.session, 'b' * 32, small), small)

    def test_result_size_bound_refuses_truncation_without_artifact(self):
        with self.assertRaisesRegex(interactive.InteractiveError, '16MiB'):
            interactive._completion_result(self.session, 'a' * 32, {'oversize': 'x' * interactive.MAX_RESULT_BYTES})
        self.assertFalse((self.session.dir / 'interactive-results').exists())

    def test_fixture_creation_requires_explicit_policy_and_permitted_base(self):
        request = self.fixture_request()
        with self.assertRaisesRegex(interactive.InteractiveError, 'frozen nativeBindings policy'):
            interactive._request(json.dumps(request), self.settings, self.session)
        self.settings['nativeBindings'] = self.binding_policy()
        request['request']['base'] = '0x00000007'
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('forbidden-base', request)
                self.send('finish')
        self.session.on_save = ready
        with patch('skyrim_autotest.fixture_actors.create') as create:
            self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        create.assert_not_called()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})

    def test_fixture_creation_delegates_once_after_delivery_then_finish(self):
        self.settings['nativeBindings'] = self.binding_policy()
        self.session.state['configuration']['interactive_session'] = interactive.validate(self.settings)
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('spawn', self.fixture_request())
                self.send('finish')
        self.session.on_save = ready
        def create(session, request, deadline, policy):
            self.assertIs(session, self.session)
            self.assertEqual(request, self.fixture_request()['request'])
            self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'delivered': 1, 'received': 1})
            self.assertEqual(policy, self.session.state['configuration']['interactive_session']['nativeBindings'])
            self.assertLessEqual(deadline, self.clock.now + 1)
            return {'fixture': {'tag': 'ownedNpcOne', 'status': 'created', 'creationId': 'a' * 32},
                'actor': {'reference': '0xFF000123', 'base': '0x00000456'}}
        with patch('skyrim_autotest.fixture_actors.create', side_effect=create) as call:
            self.assertEqual(self.run_loop()['reason'], 'owner-finished')
        call.assert_called_once()
        self.assertEqual([name for name, _, _, _ in self.session.calls], ['inspect', 'menu'])
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'completed': 2})

    def test_uncertain_fixture_creation_is_not_replayed_or_replaced(self):
        self.settings['nativeBindings'] = self.binding_policy()
        self.session.state['configuration']['interactive_session'] = interactive.validate(self.settings)
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('spawn', self.fixture_request())
                self.send('finish')
        self.session.on_save = ready
        with patch('skyrim_autotest.fixture_actors.create', side_effect=TimeoutError('creation outcome unknown')) as call:
            with self.assertRaisesRegex(interactive.InteractiveError, 'creation outcome unknown'):
                self.run_loop()
        call.assert_called_once()
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'received': 1, 'uncertain': 1})

    def test_existing_npc_cannot_bypass_witness_through_preset_route(self):
        self.settings['nativeBindings'] = self.binding_policy()
        self.session.state['configuration']['interactive_session'] = interactive.validate(self.settings)
        request = {'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform', 'args': {'operation': 'object.perform',
            'request': {'action': 'assign-morph-preset', 'actor': {'reference': '0x00000123', 'base': '0x00000456'}, 'presetName': 'Exact preset'}}, 'timeoutSeconds': 1}
        self.session.on_save = lambda: self.send('unowned-preset', request) if self.session.state.get('interactiveSession') else None
        with self.assertRaisesRegex(interactive.InteractiveError, 'same-run creation witness'):
            self.run_loop()
        self.assertTrue(all(name != 'platform' for name, _, _, _ in self.session.calls))
        self.assertEqual(self.bus.status('game-fresh-run')['commands'], {'uncertain': 1})


if __name__ == '__main__':
    unittest.main()

