"""External companion transport with real durable bus, no game or microphone."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from skyrim_autotest.command_bus import CommandBus, dispatch
from tools import subject_companion as tool


class LocalClient:
    def __init__(self, fixture):
        self.fixture, self.calls = fixture, []
        self.mode = 'complete'
        self.result = {'array': ['Здравствуйте', None, True, [1, 2.25]], 'integer': 9007199254740993}

    def call(self, operation, arguments):
        self.calls.append((operation, copy.deepcopy(arguments)))
        result = dispatch(self.fixture.bus, operation, arguments)
        if operation != 'submit':
            return result
        if self.mode == 'ack-only':
            return result
        command = self.fixture.bus.next(self.fixture.session_id, self.fixture.binding)['command']
        self.fixture.bus.delivered(self.fixture.session_id, command['id'], command['claimId'], self.fixture.binding)
        envelope = json.loads(command['text'])
        if self.mode != 'no-native-row':
            with (self.fixture.run_dir / 'steps.jsonl').open('ab') as stream:
                stream.write(tool.encoded({'at': time.time(), 'kind': 'interactive-action-delivered',
                    'commandId': command['id'], 'request': envelope}) + b'\n')
        if self.mode == 'uncertain':
            self.fixture.bus.reconcile(self.fixture.session_id, command['id'], self.fixture.binding,
                                       'uncertain', 'Synthetic lost action result; never replay')
            return result
        value = {'outcome': 'owner-finished'} if envelope['operation'] == 'finish' else self.result
        if self.mode == 'large' and envelope['operation'] != 'finish':
            raw = tool.encoded(value)
            folder = self.fixture.run_dir / 'interactive-results'
            folder.mkdir(exist_ok=True)
            path = folder / (command['id'] + '.json')
            tool.exclusive(path, raw)
            evidence = {'path': str(path), 'sha256': tool.digest(raw), 'bytes': len(raw), 'format': 'json'}
            self.fixture.state.setdefault('interactiveArtifacts', []).append(dict(evidence, commandId=command['id']))
            self.fixture.write_state()
            value = {'outcome': 'result-recorded', 'evidence': evidence}
        self.fixture.bus.complete(self.fixture.session_id, command['id'], command['claimId'], self.fixture.binding, value)
        if self.mode == 'lost-ack':
            raise OSError('Synthetic lost HTTP ingress ACK')
        return result


class Fixture:
    def __init__(self, root, cases=('case-a', 'case-b')):
        self.root = root
        self.executor, self.runtime = root / 'executor', root / 'runtime'
        self.package = self.executor / 'skyrim_autotest'
        self.package.mkdir(parents=True)
        (self.executor / 'run.py').write_text('# offline frozen executor fixture\n', encoding='utf-8')
        hashes, files = {}, []
        for name in ('command_bus.py', 'command_bus_http.py', 'native.py', 'runner_monitor.py'):
            path = self.package / name
            path.write_text('# immutable offline module ' + name + '\n', encoding='utf-8')
            hashes[name] = tool.digest(path.read_bytes())
            files.append({'path': str(path), 'sha256': hashes[name]})
        self.manifest = root / 'executor-manifest.json'
        self.manifest.write_bytes(tool.encoded({'schemaVersion': 1, 'files': files}))
        self.plan = root / 'plan.json'
        self.plan.write_bytes(tool.encoded({'cases': [{'id': name} for name in cases],
            'fixture': {'cell': 'QASmoke'}, 'bounds': {'maximumSeconds': 20, 'maximumCommands': 20}}))
        self.sequencer = root / 'sequencer.py'
        self.sequencer.write_text('def run(exchange, emit):\n    return {}\n', encoding='utf-8')
        self.channel = root / 'channel.json'
        self.channel.write_text('{}', encoding='utf-8')
        self.run_id, self.order_id = 'new-run-123', 'order-123'
        self.session_id = 'game-' + self.run_id
        self.binding = {'provider': 'skyrim-autotest', 'conversationId': self.run_id, 'agentId': 'owned-game-executor'}
        self.worker = {'pid': 111, 'birth': 1001, 'path': str(Path(sys.executable).resolve())}
        self.game = {'pid': 112, 'birth': 1002, 'path': str(root / 'SkyrimSE.exe')}
        self.run_dir = self.runtime / 'runs' / self.run_id
        self.run_dir.mkdir(parents=True)
        (self.run_dir / 'steps.jsonl').write_bytes(b'')
        self.state = {'id': self.run_id, 'order': {'id': self.order_id}, 'runner': self.worker, 'game': self.game,
            'owned': [{'role': 'game', 'identity': self.game}], 'phase': 'interactive-session',
            'deadline': time.time() + 60, 'gameplayBootstrap': {'completed': True, 'cell': 'QASmoke', 'startMode': 'new-game'},
            'executorHashes': hashes,
            'configuration': {'game_edition': 'se', 'interactive_session': {'channelConfig': str(self.channel),
                'sourceId': 'operator.actions', 'maximumSeconds': 60}},
            'interactiveSession': {'sessionId': self.session_id, 'binding': self.binding,
                'sourceId': 'operator.actions', 'ready': True, 'maximumSeconds': 60}}
        self.write_state()
        self.bus = CommandBus(root / 'commands.sqlite3')
        self.bus.create_session(self.session_id)
        self.bus.bind(self.session_id, self.binding)
        self.client = LocalClient(self)
        self.live, self.pulse_age = True, 0
        self.backend = SimpleNamespace(client=lambda *args, **kwargs: self.client,
            alive=lambda ident: self.live and ident in (self.worker, self.game),
            heartbeat=lambda *args: {'healthy': True, 'at': time.time() - self.pulse_age},
            process_identity=lambda pid: {'pid': pid, 'birth': 1003, 'path': str(Path(sys.executable).resolve())})

    def write_state(self):
        (self.run_dir / 'state.json').write_bytes(tool.encoded(self.state))

    def args(self, suffix='report'):
        return SimpleNamespace(executor=str(self.executor), runtime=str(self.runtime), channel_config=str(self.channel),
            executor_manifest=str(self.manifest), executor_manifest_sha256=tool.digest(self.manifest.read_bytes()),
            plan=str(self.plan), plan_sha256=tool.digest(self.plan.read_bytes()),
            sequencer=str(self.sequencer), sequencer_sha256=tool.digest(self.sequencer.read_bytes()),
            order_id=self.order_id, attempt_id=self.order_id,
            worker_identity=self.worker, game_identity=self.game,
            output=str(self.root / suffix / 'report.json'), wait_seconds=.5, maximum_seconds=None)

    def companion(self, ready=True):
        value = tool.Companion(self.args(), backend=self.backend)
        if ready:
            value.wait_ready()
        return value


class CompanionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def intent(self, companion, envelope=None, case='case-a'):
        if case is not None and companion.active_case is None:
            companion.emit({'kind': 'check-start', 'caseId': case, 'role': 'subject'})
        envelope = envelope or {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect',
                                'args': {'kind': 'scene'}, 'timeoutSeconds': 5}
        companion.emit({'kind': 'measurement', 'caseId': case, 'sequence': companion.measurement_sequence + 1,
                        'request': envelope, 'delivery': 'intent'})
        return envelope

    def test_ack_is_not_subject_start_or_pass_but_actual_delivery_is(self):
        companion = self.fixture.companion()
        self.assertFalse(companion.report['subjectStarted'])
        envelope = self.intent(companion)
        self.assertFalse(companion.report['subjectStarted'])
        raw = companion.exchange(envelope)
        self.assertEqual(raw, self.fixture.client.result)
        start = companion.report['subjectStart']
        self.assertEqual(start['caseId'], 'case-a')
        self.assertEqual(tool.decoded(Path(start['deliveredEvidence']['path']).read_bytes())['kind'],
                         'interactive-action-delivered')
        with self.assertRaisesRegex(tool.CompanionError, 'requires pinned assertions'):
            companion.emit({'kind': 'check-result', 'caseId': 'case-a', 'outcome': 'passed', 'detail': 'ACK alone'})
        self.assertEqual(companion.case('case-a')['status'], 'not_run')

    def test_exact_raw_arrays_unicode_numbers_and_command_receipts_survive(self):
        companion = self.fixture.companion()
        envelope = self.intent(companion)
        raw = companion.exchange(envelope)
        self.assertEqual(raw['integer'], 9007199254740993)
        self.assertEqual(raw['array'], ['Здравствуйте', None, True, [1, 2.25]])
        action = companion.report['actions'][0]
        request = tool.decoded(Path(action['request']['path']).read_bytes())
        self.assertEqual(request['expectedBinding'], self.fixture.binding)
        self.assertEqual(request['metadata']['caseId'], 'case-a')
        self.assertEqual(action['status'], 'completed')
        self.assertEqual(tool.decoded(Path(action['rawResult']['path']).read_bytes()), raw)
        companion.emit({'kind': 'measurement', 'caseId': 'case-a', 'sequence': 1,
                        'request': envelope, 'delivery': 'completed', 'rawResult': raw})
        companion.emit({'kind': 'assertion', 'caseId': 'case-a', 'check': 'origin-owned',
                        'outcome': 'passed', 'actual': raw, 'expected': raw})
        companion.emit({'kind': 'check-result', 'caseId': 'case-a', 'outcome': 'passed', 'detail': 'origin assertion'})
        self.assertEqual(companion.case('case-a')['status'], 'passed')
        self.assertIn(action['rawResult'], companion.case('case-a')['evidence'])

    def test_uncertain_delivery_preserves_actual_start_and_never_replays(self):
        self.fixture.client.mode = 'uncertain'
        companion = self.fixture.companion()
        envelope = self.intent(companion)
        with self.assertRaisesRegex(tool.CompanionError, 'terminal'):
            companion.exchange(envelope)
        self.assertTrue(companion.report['subjectStarted'])
        self.assertTrue(companion.report['uncertain'])
        with self.assertRaises(tool.CompanionError):
            companion.exchange(envelope)
        self.assertEqual(sum(operation == 'submit' for operation, _ in self.fixture.client.calls), 1)
        self.assertEqual(companion.report['actions'][0]['status'], 'uncertain')

    def test_lost_ingress_ack_is_not_resubmitted_even_if_action_completed(self):
        self.fixture.client.mode = 'lost-ack'
        companion = self.fixture.companion()
        envelope = self.intent(companion)
        with self.assertRaisesRegex(OSError, 'lost HTTP'):
            companion.exchange(envelope)
        self.assertTrue(companion.report['uncertain'])
        self.assertTrue(companion.report['subjectStarted'])
        self.assertNotIn('ack', companion.report['actions'][0])
        self.assertEqual(sum(operation == 'submit' for operation, _ in self.fixture.client.calls), 1)
        with self.assertRaises(tool.CompanionError):
            companion.exchange(envelope)

    def test_large_result_requires_exact_run_registry_path_size_and_hash(self):
        self.fixture.client.mode = 'large'
        self.fixture.client.result = ['Ж' * 20000, [1, 2, 3], {'numeric': 1.125}]
        companion = self.fixture.companion()
        raw = companion.exchange(self.intent(companion))
        self.assertEqual(raw, self.fixture.client.result)
        action = companion.report['actions'][0]
        self.assertTrue(Path(action['artifact']['path']).is_relative_to(self.fixture.run_dir / 'interactive-results'))
        self.assertTrue(Path(action['artifactCopy']['path']).is_relative_to(companion.folder))
        self.assertEqual(Path(action['artifact']['path']).read_bytes(), Path(action['artifactCopy']['path']).read_bytes())
        Path(action['artifact']['path']).write_bytes(b'[]')
        with self.assertRaisesRegex(tool.CompanionError, 'hash'):
            companion.unwrap(action['commandId'], {'outcome': 'result-recorded', 'evidence': action['artifact']}, action)

    def test_foreign_large_result_path_and_missing_registry_are_refused(self):
        companion = self.fixture.companion()
        command_id = 'a' * 32
        foreign = self.fixture.root / 'foreign.json'
        foreign.write_bytes(b'[]')
        receipt = {'path': str(foreign), 'sha256': tool.digest(b'[]'), 'bytes': 2, 'format': 'json'}
        with self.assertRaisesRegex(tool.CompanionError, 'exact owned run'):
            companion.unwrap(command_id, {'outcome': 'result-recorded', 'evidence': receipt}, {})
        path = self.fixture.run_dir / 'interactive-results' / (command_id + '.json')
        path.parent.mkdir()
        path.write_bytes(b'[]')
        receipt['path'] = str(path)
        with self.assertRaisesRegex(tool.CompanionError, 'registry'):
            companion.unwrap(command_id, {'outcome': 'result-recorded', 'evidence': receipt}, {})

    def test_stale_bootstrap_changed_identity_and_heartbeat_fail_before_submit(self):
        companion = self.fixture.companion()
        envelope = self.intent(companion)
        original = copy.deepcopy(self.fixture.state)
        for alteration in ('world', 'birth', 'ownership', 'heartbeat'):
            with self.subTest(alteration=alteration):
                self.fixture.state = copy.deepcopy(original)
                self.fixture.pulse_age = 0
                if alteration == 'world': self.fixture.state['gameplayBootstrap']['cell'] = 'DifferentWorld'
                if alteration == 'birth': self.fixture.state['game']['birth'] += 1
                if alteration == 'ownership': self.fixture.state['owned'] = []
                if alteration == 'heartbeat': self.fixture.pulse_age = 11
                self.fixture.write_state()
                with self.assertRaises(tool.CompanionError):
                    companion.check_state()
        self.assertFalse(any(operation == 'submit' for operation, _ in self.fixture.client.calls))

    def test_binding_race_refuses_before_new_command_is_inserted(self):
        companion = self.fixture.companion()
        envelope = self.intent(companion)
        self.fixture.bus.bind(self.fixture.session_id, dict(self.fixture.binding, agentId='another-agent'))
        with self.assertRaises(Exception):
            companion.exchange(envelope)
        self.assertEqual(self.fixture.bus.status(self.fixture.session_id)['commands'], {})

    def test_existing_report_or_run_claim_prevents_reconnect_with_new_event_ids(self):
        self.fixture.companion()
        with self.assertRaisesRegex(tool.CompanionError, 'output exists'):
            tool.Companion(self.fixture.args(), backend=self.fixture.backend)
        args = self.fixture.args('second-output')
        second = tool.Companion(args, backend=self.fixture.backend)
        with self.assertRaises(FileExistsError):
            second.wait_ready()

    def test_duplicate_order_and_changed_pin_are_refused(self):
        companion = self.fixture.companion(ready=False)
        duplicate = self.fixture.runtime / 'runs' / 'old-run'
        duplicate.mkdir()
        (duplicate / 'state.json').write_bytes(tool.encoded(self.fixture.state))
        with self.assertRaisesRegex(tool.CompanionError, 'Multiple native runs'):
            companion.wait_ready()
        (self.fixture.package / 'native.py').write_text('# changed bytes', encoding='utf-8')
        with self.assertRaisesRegex(tool.CompanionError, 'changed'):
            companion.verify_inventory()

    def test_finish_is_once_and_can_complete_after_normal_game_exit(self):
        companion = self.fixture.companion()
        companion.active_case = None
        envelope = self.intent(companion, {'schemaVersion': 1, 'operation': 'finish'}, case=None)
        original = self.fixture.client.call

        def call(operation, arguments):
            result = original(operation, arguments)
            if operation == 'submit':
                self.fixture.live = False
                self.fixture.state['phase'] = 'stop-and-restore'
                self.fixture.state['interactiveSession']['ready'] = False
                self.fixture.write_state()
            return result

        self.fixture.client.call = call
        self.assertEqual(companion.exchange(envelope), {'outcome': 'owner-finished'})
        self.assertTrue(companion.finish_completed)
        with self.assertRaises(tool.CompanionError):
            companion.exchange(envelope)
        self.assertEqual(sum(operation == 'submit' for operation, _ in self.fixture.client.calls), 1)

    def test_evidence_and_origin_measurements_cannot_be_silently_rewritten(self):
        companion = self.fixture.companion()
        envelope = self.intent(companion)
        companion.exchange(envelope)
        with self.assertRaisesRegex(tool.CompanionError, 'verified raw result'):
            companion.emit({'kind': 'measurement', 'caseId': 'case-a', 'sequence': 1,
                            'request': envelope, 'delivery': 'completed', 'rawResult': {'forged': True}})
        companion.events_path.write_bytes(b'changed')
        with self.assertRaisesRegex(tool.CompanionError, 'changed externally'):
            companion.event('extra')

    def test_malformed_json_and_nonfinite_values_are_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(Exception): tool.decoded(raw)
        with self.assertRaises(ValueError): tool.encoded({'x': float('nan')})

    def test_current_execution_plan_checks_inventory_is_dynamic(self):
        self.fixture.plan.write_bytes(tool.encoded({'checks': [
            {'name': 'new-male-case', 'role': 'subject'}, {'name': 'new-female-case', 'role': 'subject'}],
            'bounds': {'maximumSeconds': 1200}, 'fixture': {'cell': 'QASmoke'}}))
        companion = self.fixture.companion(ready=False)
        self.assertEqual(companion.case_ids, ['new-male-case', 'new-female-case'])
        self.assertEqual(companion.maximum, 1200)

    def test_completed_bus_command_without_native_delivery_is_not_a_result(self):
        self.fixture.client.mode = 'no-native-row'
        companion = self.fixture.companion()
        with self.assertRaisesRegex(tool.CompanionError, 'native action-delivered'):
            companion.exchange(self.intent(companion))
        self.assertFalse(companion.report['subjectStarted'])
        self.assertTrue(companion.report['uncertain'])

    def test_ack_without_completion_times_out_without_replay_or_subject_start(self):
        self.fixture.client.mode = 'ack-only'
        companion = self.fixture.companion()
        tick = [0]

        def clock():
            tick[0] += 1
            return tick[0]

        companion.clock, companion.end, companion.pause = clock, 100, lambda seconds: None
        with self.assertRaisesRegex(tool.CompanionError, 'completion deadline'):
            companion.exchange(self.intent(companion))
        self.assertFalse(companion.report['subjectStarted'])
        self.assertTrue(companion.report['uncertain'])
        self.assertEqual(sum(operation == 'submit' for operation, _ in self.fixture.client.calls), 1)

    def test_frozen_modules_use_isolated_cache_and_create_no_bytecode(self):
        root = Path(__file__).resolve().parents[1] / 'skyrim_autotest'
        inventory = {}
        import skyrim_autotest.command_bus as existing
        for path in self.fixture.package.glob('*.py'):
            path.write_bytes((root / path.name).read_bytes())
            inventory[str(path)] = tool.digest(path.read_bytes())
        backend = tool.load_backend(self.fixture.executor, inventory)
        self.assertTrue(backend.client.__module__.startswith('_subject_rc6_'))
        self.assertIs(sys.modules['skyrim_autotest.command_bus'], existing)
        self.assertFalse((self.fixture.package / '__pycache__').exists())


class SequencerProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def source(self, mismatch=False, sleeping=False):
        if sleeping:
            return 'import time\ndef run(exchange, emit):\n emit({"kind":"check-start","caseId":"case-a","role":"subject"})\n time.sleep(60)\n'
        return '''def run(exchange, emit):
    emit({'kind':'check-start','caseId':'case-a','role':'subject'})
    req={'schemaVersion':1,'operation':'tool','tool':'inspect','args':{'kind':'scene'},'timeoutSeconds':5}
    emit({'kind':'measurement','caseId':'case-a','sequence':1,'request':req,'delivery':'intent'})
    raw=exchange(req)
    emit({'kind':'measurement','caseId':'case-a','sequence':1,'request':req,'delivery':'completed','rawResult':raw})
    emit({'kind':'assertion','caseId':'case-a','check':'origin-check','outcome':OUTCOME,'actual':raw,'expected':raw})
    emit({'kind':'check-result','caseId':'case-a','outcome':OUTCOME,'detail':'pinned origin verdict'})
    emit({'kind':'check-result','caseId':'case-b','outcome':'not_run','detail':'declared remainder'})
    req={'schemaVersion':1,'operation':'finish'}
    emit({'kind':'measurement','caseId':None,'sequence':2,'request':req,'delivery':'intent'})
    raw=exchange(req)
    emit({'kind':'measurement','caseId':None,'sequence':2,'request':req,'delivery':'completed','rawResult':raw})
    return {'originVerdict':OUTCOME}
'''.replace('OUTCOME', repr('mismatch' if mismatch else 'passed'))

    def test_completed_subject_mismatch_has_normal_finish_and_transport_exit_zero(self):
        self.fixture.sequencer.write_text(self.source(mismatch=True), encoding='utf-8')
        companion = self.fixture.companion(ready=False)
        self.assertEqual(companion.execute(), 0)
        self.assertEqual([row['status'] for row in companion.report['cases']], ['failed', 'not_run'])
        self.assertTrue(companion.report['completed'])
        self.assertFalse(companion.report['uncertain'])
        self.assertEqual(companion.report['actions'][-1]['envelope']['operation'], 'finish')
        self.assertEqual(companion.report['sequencerProcess']['returnCode'], 0)

    def test_returned_report_and_finish_cannot_mask_child_finalization_failure(self):
        source = ('import os\nfrom multiprocessing.util import Finalize\n'
                  'Finalize(None, os._exit, args=(7,), exitpriority=0)\n' + self.source(mismatch=True))
        self.fixture.sequencer.write_text(source, encoding='utf-8')
        companion = self.fixture.companion(ready=False)
        self.assertEqual(companion.execute(), 2)
        self.assertTrue(companion.finish_completed)
        self.assertIn('originResult', companion.report)
        self.assertEqual(companion.report['sequencerProcess']['returnCode'], 7)
        self.assertFalse(companion.report['completed'])
        self.assertEqual(companion.report['status'], 'stopped')

    def test_long_sleeping_origin_is_bounded_and_only_helper_child_is_stopped(self):
        self.fixture.sequencer.write_text(self.source(sleeping=True), encoding='utf-8')
        args = self.fixture.args()
        args.maximum_seconds = .6
        companion = tool.Companion(args, backend=self.fixture.backend)
        started = time.monotonic()
        self.assertEqual(companion.execute(), 2)
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(companion.report['sequencerProcess']['stoppedByClient'])
        self.assertIsNotNone(companion.report['sequencerProcess']['returnCode'])
        self.assertFalse(any(operation == 'submit' for operation, _ in self.fixture.client.calls))
        self.assertEqual(companion.case('case-a')['status'], 'unavailable')
        self.assertEqual(companion.case('case-a')['verdictSource'], 'transport')
        self.assertEqual(companion.case('case-b')['status'], 'not_run')


def export_fixture(root):
    """Retain one explicitly synthetic external report for collector contract QA."""
    root = Path(root)
    root.mkdir(parents=True)
    fixture = Fixture(root)
    fixture.sequencer.write_text(SequencerProcessTests.source(None, mismatch=True), encoding='utf-8')
    args = fixture.args()
    args.output = str(root / 'order' / 'subject-companion' / 'report.json')
    companion = tool.Companion(args, backend=fixture.backend)
    rc = companion.execute()
    order = {'id': fixture.order_id, 'subjectPlan': {'interface': 'polygon-file-plan/1',
        'plan': companion.report['plan'], 'sequencer': companion.report['sequencer'],
        'checks': companion.case_ids, 'maximumSeconds': 20},
        'testing': {'start': {'kind': 'check', 'name': companion.case_ids[0]},
                    'checks': [{'name': name, 'role': 'subject'} for name in companion.case_ids]},
        'inputs': [dict(companion.report[key], role='fixture') for key in ('plan', 'sequencer')]}
    (root / 'order.json').write_bytes(tool.encoded(order))
    (Path(args.output).parent / 'dispatch.json').write_bytes(tool.encoded({
        'schemaVersion': 1, 'orderId': fixture.order_id, 'worker': fixture.worker, 'returncode': rc}))
    return {'synthetic': True, 'report': args.output, 'order': str(root / 'order.json'),
            'run': str(fixture.run_dir), 'evidenceDirectory': str(root / 'order'), 'returncode': rc}


if __name__ == '__main__':
    unittest.main()
