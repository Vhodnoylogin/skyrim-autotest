"""External companion transport with real durable bus, no game or microphone."""
import copy
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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

        def pause(seconds):
            tick[0] += 1

        companion.clock, companion.end, companion.pause = lambda: tick[0], 100, pause
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

    def captured_heartbeat_backend(self):
        from skyrim_autotest import runner_monitor
        f=self.fixture;source=Path(__file__).resolve().parents[1]/'skyrim_autotest'
        inventory={}
        for path in f.package.glob('*.py'):
            path.write_bytes((source/path.name).read_bytes());inventory[str(path)]=tool.digest(path.read_bytes())
        f.manifest.write_bytes(tool.encoded({'schemaVersion':1,'files':[
            {'path':path,'sha256':sha} for path,sha in inventory.items()]}))
        f.state['executorHashes']={Path(path).name:sha for path,sha in inventory.items()}
        debugger={'pid':113,'birth':1003,'path':str(f.root/'cdb.exe')}
        f.state['configuration']['crash_capture']={'provider':'cdb','executable':debugger['path']}
        f.state['crashCapture']={'schemaVersion':1,'provider':'cdb','debugger':debugger,'target':copy.deepcopy(f.game)}
        f.state['owned'].append({'role':'crash-capture','identity':copy.deepcopy(debugger)})
        f.state['heartbeat']=time.time()-100
        f.write_state()
        pulse=runner_monitor.snapshot(f.state)
        (f.run_dir/'heartbeat.json').write_bytes(tool.encoded(pulse))
        f.backend.heartbeat=tool.load_backend(f.executor,inventory).heartbeat
        return pulse

    def test_prebinding_client_uses_the_pinned_reader_for_exact_crash_capture_heartbeat(self):
        self.captured_heartbeat_backend()
        self.assertTrue(self.fixture.backend.heartbeat.__module__.startswith('_subject_rc6_'))
        companion=self.fixture.companion()
        self.assertEqual(companion.report['runId'],self.fixture.run_id)
        self.assertEqual(companion.report['sessionId'],self.fixture.session_id)
        self.assertFalse(companion.report['subjectStarted'])
        self.assertEqual(companion.report['actions'],[])
        self.assertFalse(any(operation=='submit' for operation,_ in self.fixture.client.calls))

    def test_prebinding_foreign_capture_or_11_second_pulse_never_adopts_session(self):
        pulse=self.captured_heartbeat_backend();original=copy.deepcopy(self.fixture.state)
        for name in ('debugger','target','stale','runner'):
            self.fixture.state=copy.deepcopy(original);current=copy.deepcopy(pulse)
            if name=='debugger':self.fixture.state['crashCapture']['debugger']['birth']+=1
            if name=='target':self.fixture.state['crashCapture']['target']['birth']+=1
            if name=='stale':current['at']=time.time()-11
            if name=='runner':current['runner']['birth']+=1
            self.fixture.write_state()
            (self.fixture.run_dir/'heartbeat.json').write_bytes(tool.encoded(current))
            companion=tool.Companion(self.fixture.args(suffix=name),backend=self.fixture.backend)
            with self.subTest(name=name),self.assertRaisesRegex(tool.CompanionError,'heartbeat'):
                companion.wait_ready()
            self.assertNotIn('runId',companion.report)
            self.assertNotIn('sessionId',companion.report)
            self.assertNotIn('binding',companion.report)
            self.assertEqual(companion.report['actions'],[])
        self.assertFalse(any(operation=='submit' for operation,_ in self.fixture.client.calls))


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
        self.assertEqual(companion.report['primaryError']['stage'], 'sequencer-cleanup')
        self.assertIn('code zero', companion.report['reason'])

    def test_guard_failure_survives_terminating_the_owned_sleeping_child(self):
        ready = self.fixture.root / 'child-ready.txt'
        self.fixture.sequencer.write_text('import time\nfrom pathlib import Path\ndef run(exchange, emit):\n'
            ' Path(' + repr(str(ready)) + ').write_text("ready")\n time.sleep(60)\n', encoding='utf-8')
        companion = self.fixture.companion(ready=False)
        original = companion.check_state

        def check(*args, **kwargs):
            if ready.exists():
                raise tool.CompanionError('Synthetic exact worker guard failed before another command')
            return original(*args, **kwargs)

        with patch.object(companion, 'check_state', side_effect=check):
            self.assertEqual(companion.execute(), 2)
        saved = tool.decoded(companion.output.read_bytes())
        self.assertEqual(saved['reason'], 'Synthetic exact worker guard failed before another command')
        self.assertEqual(saved['primaryError']['stage'], 'execute')
        self.assertIn('raise tool.CompanionError', saved['primaryError']['traceback'])
        self.assertTrue(saved['sequencerProcess']['stoppedByClient'])
        self.assertEqual(saved['sequencerProcess']['cleanupError']['stage'], 'sequencer-cleanup')
        self.assertFalse(any(operation == 'submit' for operation, _ in self.fixture.client.calls))

    def test_callback_failure_stays_primary_after_the_origin_reports_its_error(self):
        self.fixture.sequencer.write_text(self.source(), encoding='utf-8')
        self.fixture.client.mode = 'uncertain'
        companion = self.fixture.companion(ready=False)
        self.assertEqual(companion.execute(), 2)
        self.assertEqual(companion.report['primaryError']['stage'], 'callback-exchange')
        self.assertIn('terminal', companion.report['reason'])
        self.assertNotIn('Pinned sequencer stopped', companion.report['reason'])
        self.assertIn('Companion callback refused', companion.report['sequencerError']['error'])
        self.assertIn('callback', companion.report['sequencerError']['traceback'])
        self.assertTrue(companion.report['uncertain'])
        self.assertEqual(sum(operation == 'submit' for operation, _ in self.fixture.client.calls), 1)

    def test_original_sequencer_exception_type_and_traceback_are_retained(self):
        self.fixture.sequencer.write_text('def run(exchange, emit):\n raise ValueError("distinct origin failure")\n',
                                          encoding='utf-8')
        companion = self.fixture.companion(ready=False)
        self.assertEqual(companion.execute(), 2)
        self.assertEqual(companion.report['sequencerError']['errorType'], 'ValueError')
        self.assertEqual(companion.report['sequencerError']['error'], 'distinct origin failure')
        self.assertIn('raise ValueError', companion.report['sequencerError']['traceback'])
        self.assertIn('distinct origin failure', companion.report['reason'])

    def test_cli_stderr_keeps_primary_error_when_a_later_exception_escapes(self):
        companion = self.fixture.companion()
        companion.stop(ValueError('original callback failure'), 'callback-exchange')
        argv = []
        for name, value in vars(self.fixture.args()).items():
            if name in ('maximum_seconds', 'wait_seconds'):
                continue
            argv.extend(['--' + name.replace('_', '-'), str(value)])
        stderr = io.StringIO()
        with patch.object(tool, 'Companion', return_value=companion), \
             patch.object(companion, 'execute', side_effect=OSError('secondary terminal failure')), \
             patch.object(sys, 'stderr', stderr):
            self.assertEqual(tool.main(argv), 2)
        diagnostic = json.loads(stderr.getvalue())
        self.assertEqual(diagnostic['reason'], 'original callback failure')
        self.assertEqual(diagnostic['errorType'], 'ValueError')
        self.assertEqual(diagnostic['terminalError']['reason'], 'secondary terminal failure')

    def test_manual_inbox_waits_over_180_logical_seconds_for_one_owner_command(self):
        from skyrim_autotest.manual_scene import directory_commands
        folder = self.fixture.root / 'operator-commands'
        folder.mkdir()
        tick = [0.0]
        observed = []

        def pause(_):
            tick[0] += 60
            observed.append(tick[0])
            if tick[0] == 240:
                (folder / '000001.json').write_text('{"sequence":1,"action":"inspect"}', encoding='utf-8')

        with patch('skyrim_autotest.manual_scene.time.monotonic', side_effect=lambda: tick[0]), \
             patch('skyrim_autotest.manual_scene.time.sleep', side_effect=pause):
            command = next(directory_commands(folder, 600))
        self.assertEqual(observed, [60, 120, 180, 240])
        self.assertEqual(command, {'sequence': 1, 'action': 'inspect'})
        self.assertEqual(self.fixture.client.calls, [])

    def test_companion_remains_attached_during_240_logical_seconds_without_commands(self):
        ready, release = self.fixture.root / 'waiting.txt', self.fixture.root / 'owner-command.txt'
        source = self.source().replace('def run(exchange, emit):',
            'import time\nfrom pathlib import Path\ndef run(exchange, emit):\n'
            '    Path(' + repr(str(ready)) + ').write_text("waiting")\n'
            '    while not Path(' + repr(str(release)) + ').exists(): time.sleep(.01)')
        self.fixture.sequencer.write_text(source, encoding='utf-8')
        self.fixture.plan.write_bytes(tool.encoded({'cases': [{'id': name} for name in ('case-a', 'case-b')],
            'fixture': {'cell': 'QASmoke'}, 'bounds': {'maximumSeconds': 600, 'maximumCommands': 20}}))
        self.fixture.state['configuration']['interactive_session']['maximumSeconds'] = 600
        self.fixture.state['interactiveSession']['maximumSeconds'] = 600
        self.fixture.state['deadline'] = time.time() + 600
        self.fixture.write_state()
        offset, released = [0], []
        companion = tool.Companion(self.fixture.args(), backend=self.fixture.backend,
                                   clock=lambda: time.monotonic() + offset[0])
        original = companion.check_state

        def check(*args, **kwargs):
            if ready.exists() and not released:
                self.assertFalse(any(operation == 'submit' for operation, _ in self.fixture.client.calls))
                offset[0] = 240
                original(*args, **kwargs)
                released.append(True)
                release.write_text('actual test owner command', encoding='utf-8')
            return original(*args, **kwargs)

        with patch.object(companion, 'check_state', side_effect=check):
            self.assertEqual(companion.execute(), 0)
        self.assertEqual(released, [True])
        self.assertTrue(companion.report['completed'])
        self.assertNotIn('primaryError', companion.report)
        self.assertEqual(sum(operation == 'submit' for operation, _ in self.fixture.client.calls), 2)

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
        self.assertIn('deadline expired', companion.report['reason'])
        self.assertEqual(companion.report['sequencerProcess']['cleanupError']['stage'], 'sequencer-cleanup')


class LiveStateReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))
        self.path = self.fixture.run_dir / 'state.json'

    def denying_reader(self, failures=1, after=None):
        original = tool.read_bytes
        calls = []
        def read(path, *args, **kwargs):
            if Path(path) == self.path:
                calls.append(str(path))
                if len(calls) <= failures:
                    raise PermissionError(errno.EACCES, 'synthetic state sharing denial', str(path))
                if after is not None:
                    return after
            return original(path, *args, **kwargs)
        return read, calls

    def virtual_time(self, companion):
        now = [0.0]
        companion.clock = lambda: now[0]
        companion.pause = lambda duration: now.__setitem__(0, now[0] + duration)
        companion.end = None
        return now

    def test_startup_transient_denial_recovers_without_starting_subject_or_submitting(self):
        companion = self.fixture.companion(ready=False)
        reader, calls = self.denying_reader(2)
        with patch.object(tool, 'read_bytes', side_effect=reader):
            companion.wait_ready()
        self.assertGreaterEqual(len(calls), 3)
        events = [json.loads(x) for x in companion.events_path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(sum(x['kind'] == 'live-state-read-denied' for x in events), 2)
        self.assertEqual(sum(x['kind'] == 'live-state-read-recovered' for x in events), 1)
        self.assertFalse(companion.report['subjectStarted'])
        self.assertFalse(any(op == 'submit' for op, _ in self.fixture.client.calls))

    def test_persistent_denial_obeys_original_startup_deadline_without_claim_or_commands(self):
        companion = self.fixture.companion(ready=False)
        now = self.virtual_time(companion)
        reader, calls = self.denying_reader(1000)
        with patch.object(tool, 'read_bytes', side_effect=reader), self.assertRaises(PermissionError):
            companion.wait_ready()
        self.assertLessEqual(now[0], companion.wait_seconds)
        self.assertLessEqual(len(calls), tool.STATE_READ_ATTEMPTS)
        self.assertFalse((self.fixture.run_dir / 'subject-companion.claim.json').exists())
        self.assertEqual(self.fixture.client.calls, [])

    def test_reads_never_extend_shared_or_action_deadline(self):
        for shared, action in ((.08, .4), (.4, .08)):
            companion = tool.Companion(self.fixture.args('deadline-' + str(shared)), backend=self.fixture.backend)
            now = self.virtual_time(companion)
            companion.end = shared
            reader, _ = self.denying_reader(1000)
            with patch.object(tool, 'read_bytes', side_effect=reader), self.assertRaises(PermissionError):
                companion.read_live_state(self.path, deadline=action)
            self.assertLessEqual(now[0], min(shared, action))

    def test_malformed_or_wrong_owned_identity_after_denial_is_not_retried_or_accepted(self):
        companion = self.fixture.companion()
        bad = copy.deepcopy(self.fixture.state)
        bad['game']['birth'] += 1
        for raw, expected in ((b'{invalid', json.JSONDecodeError), (tool.encoded(bad), tool.CompanionError)):
            reader, calls = self.denying_reader(after=raw)
            with patch.object(tool, 'read_bytes', side_effect=reader), self.assertRaises(expected):
                companion.check_state()
            self.assertEqual(len(calls), 2)
        self.assertFalse(any(op == 'submit' for op, _ in self.fixture.client.calls))

    def test_ended_but_still_ready_state_after_denial_never_enters_session(self):
        companion = self.fixture.companion(ready=False)
        ended = dict(self.fixture.state, done=True)
        reader, calls = self.denying_reader(after=tool.encoded(ended))
        with patch.object(tool, 'read_bytes', side_effect=reader), self.assertRaisesRegex(tool.CompanionError, 'already ended'):
            companion.wait_ready()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.fixture.client.calls, [])

    def test_unclassified_or_missing_file_errors_and_nonruntime_paths_remain_immediate(self):
        companion = self.fixture.companion(ready=False)
        for error in (PermissionError(errno.EPERM, 'not a sharing denial'), FileNotFoundError('missing state')):
            with patch.object(tool, 'read_bytes', side_effect=error) as reader, self.assertRaises(type(error)):
                companion.read_live_state(self.path)
            reader.assert_called_once()
        with patch.object(tool, 'read_bytes') as reader, self.assertRaisesRegex(tool.CompanionError, 'exact runtime'):
            companion.read_live_state(self.fixture.plan)
        reader.assert_not_called()

    def test_pinned_input_denial_remains_single_strict_read(self):
        with patch.object(tool, 'read_bytes', side_effect=PermissionError(errno.EACCES, 'plan ACL')) as reader:
            with self.assertRaises(PermissionError):
                tool.pinned(self.fixture.plan, tool.digest(self.fixture.plan.read_bytes()))
        reader.assert_called_once()

    def test_completed_artifact_registry_read_retries_without_repeating_ingress(self):
        self.fixture.client.mode = 'large'
        companion = self.fixture.companion()
        original = companion.unwrap
        denied = []
        def unwrap(*args, **kwargs):
            reader, calls = self.denying_reader()
            with patch.object(tool, 'read_bytes', side_effect=reader):
                result = original(*args, **kwargs)
            denied.extend(calls)
            return result
        with patch.object(companion, 'unwrap', side_effect=unwrap):
            companion.emit({'kind': 'check-start', 'caseId': 'case-a', 'role': 'subject'})
            envelope = {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect',
                        'args': {'kind': 'scene'}, 'timeoutSeconds': 5}
            companion.emit({'kind': 'measurement', 'caseId': 'case-a', 'sequence': 1,
                            'request': envelope, 'delivery': 'intent'})
            self.assertEqual(companion.exchange(envelope), self.fixture.client.result)
        self.assertEqual(len(denied), 2)
        self.assertEqual(sum(op == 'submit' for op, _ in self.fixture.client.calls), 1)
        self.assertFalse(companion.report['actionsRetried'])
        self.assertEqual(companion.report['actions'][0]['status'], 'completed')

    def test_changed_registry_owner_after_denial_cannot_supply_completed_result_or_replay(self):
        self.fixture.client.mode = 'large'
        companion = self.fixture.companion()
        original = companion.unwrap
        def unwrap(*args, **kwargs):
            changed = copy.deepcopy(self.fixture.state)
            changed['runner']['birth'] += 1
            reader, _ = self.denying_reader(after=tool.encoded(changed))
            with patch.object(tool, 'read_bytes', side_effect=reader):
                return original(*args, **kwargs)
        envelope = {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect',
                    'args': {'kind': 'scene'}, 'timeoutSeconds': 5}
        companion.emit({'kind': 'check-start', 'caseId': 'case-a', 'role': 'subject'})
        companion.emit({'kind': 'measurement', 'caseId': 'case-a', 'sequence': 1,
                        'request': envelope, 'delivery': 'intent'})
        with patch.object(companion, 'unwrap', side_effect=unwrap), self.assertRaisesRegex(tool.CompanionError, 'pins changed'):
            companion.exchange(envelope)
        self.assertTrue(companion.poisoned and companion.report['uncertain'])
        self.assertNotIn('rawResult', companion.report['actions'][0])
        with self.assertRaisesRegex(tool.CompanionError, 'no replay'):
            companion.exchange(envelope)
        self.assertEqual(sum(op == 'submit' for op, _ in self.fixture.client.calls), 1)

    def test_supplied_state_validation_cannot_cross_original_action_deadline(self):
        companion = self.fixture.companion()
        now = self.virtual_time(companion)
        companion.end = 100
        def heartbeat(*args):
            now[0] = 2
            return {'healthy': True, 'at': time.time()}
        self.fixture.backend.heartbeat = heartbeat
        with self.assertRaisesRegex(tool.CompanionError, 'completion deadline'):
            companion.check_state(state=self.fixture.state, deadline=1)

    def test_recovery_log_cannot_admit_state_after_original_read_or_startup_bound(self):
        companion = self.fixture.companion(ready=False)
        now = self.virtual_time(companion)
        reader, _ = self.denying_reader()
        original = companion.event
        def event(kind, **fields):
            original(kind, **fields)
            if kind == 'live-state-read-recovered':
                now[0] = companion.wait_seconds + .01
        with (patch.object(tool, 'read_bytes', side_effect=reader),
              patch.object(companion, 'event', side_effect=event),
              self.assertRaisesRegex(tool.CompanionError, 'read deadline')):
            companion.wait_ready()
        self.assertFalse((self.fixture.run_dir / 'subject-companion.claim.json').exists())
        self.assertEqual(self.fixture.client.calls, [])

    def test_channel_status_cannot_admit_client_claim_after_startup_bound(self):
        companion = self.fixture.companion(ready=False)
        now = self.virtual_time(companion)
        original = self.fixture.client.call
        def call(operation, arguments):
            result = original(operation, arguments)
            if operation == 'status':
                now[0] = companion.wait_seconds + .01
            return result
        self.fixture.client.call = call
        with self.assertRaisesRegex(tool.CompanionError, 'startup deadline'):
            companion.wait_ready()
        self.assertFalse((self.fixture.run_dir / 'subject-companion.claim.json').exists())
        self.assertFalse(any(op == 'submit' for op, _ in self.fixture.client.calls))

    def test_result_retention_crossing_action_deadline_does_not_mark_completion_or_replay(self):
        companion = self.fixture.companion()
        now = self.virtual_time(companion)
        companion.end = 100
        original = companion.unwrap
        def unwrap(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = kwargs['deadline'] + .01
            return result
        envelope = {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect',
                    'args': {'kind': 'scene'}, 'timeoutSeconds': 5}
        companion.emit({'kind': 'check-start', 'caseId': 'case-a', 'role': 'subject'})
        companion.emit({'kind': 'measurement', 'caseId': 'case-a', 'sequence': 1,
                        'request': envelope, 'delivery': 'intent'})
        with patch.object(companion, 'unwrap', side_effect=unwrap), self.assertRaisesRegex(tool.CompanionError, 'completion deadline'):
            companion.exchange(envelope)
        self.assertNotEqual(companion.report['actions'][0]['status'], 'completed')
        self.assertTrue(companion.poisoned and companion.report['uncertain'])
        self.assertEqual(sum(op == 'submit' for op, _ in self.fixture.client.calls), 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows file-sharing behavior')
    def test_actual_windows_exclusive_handle_denial_recovers_without_game(self):
        import ctypes
        from ctypes import wintypes
        companion = self.fixture.companion(ready=False)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(self.path), 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        denied, released = threading.Event(), threading.Event()
        def unlock():
            denied.wait(2)
            kernel.CloseHandle(handle)
            released.set()
        thread = threading.Thread(target=unlock)
        thread.start()
        original = companion.event
        def event(kind, **fields):
            original(kind, **fields)
            if kind == 'live-state-read-denied':
                denied.set()
        try:
            with patch.object(companion, 'event', side_effect=event):
                self.assertEqual(companion.read_live_state(self.path)['id'], self.fixture.run_id)
        finally:
            denied.set()
            thread.join(3)
        self.assertTrue(denied.is_set() and released.is_set())
        self.assertFalse(any(op == 'submit' for op, _ in self.fixture.client.calls))


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


class OwnedLoadClient(LocalClient):
    """Real durable bus with explicit incomplete/world-ready/rebound producer states."""
    def __init__(self,fixture):
        super().__init__(fixture)
        self.pending_load,self.load_stage=None,0
        self.complete_load=True
        self.load_fault=lambda state:None
        self.lose_ack=False

    def call(self,operation,arguments):
        if operation=='events' and self.pending_load is not None and self.complete_load:
            self.advance_load()
        if operation!='submit':
            return super().call(operation,arguments)
        envelope=json.loads(arguments['text'])
        if tool.Companion.owned_load_request(envelope) is None:
            return super().call(operation,arguments)
        self.calls.append((operation,copy.deepcopy(arguments)))
        ack=dispatch(self.fixture.bus,operation,arguments)
        command=self.fixture.bus.next(self.fixture.session_id,self.fixture.binding)['command']
        self.fixture.bus.delivered(self.fixture.session_id,command['id'],command['claimId'],self.fixture.binding)
        with (self.fixture.run_dir/'steps.jsonl').open('ab') as stream:
            stream.write(tool.encoded({'kind':'interactive-action-delivered','commandId':command['id'],'request':envelope})+b'\n')
        state=self.fixture.state
        record=state['npcPersistence']['saved-six']
        record.update(status='load-intent',loadAttempted=True,loadCommandId=command['id'],ownedLoadOrdinal=1,
                      interactiveWindow={'phase':'interactive-session','deadline':state['deadline']})
        state['phase']='interactive-owned-npc-load'
        state['gameplayBootstrap']['completed']=False
        state['ownedLoadTransition']={'saveTag':'saved-six','completed':False,'beforeGame':copy.deepcopy(self.fixture.game),'ordinal':1}
        state['ownedLoadHistory']=[copy.deepcopy(state['ownedLoadTransition'])]
        for entry in state['interactiveActorFixtures'].values():entry['status']='load-pending'
        self.pending_load=command
        self.load_fault(state)
        self.fixture.write_state()
        if self.lose_ack:raise OSError('Synthetic lost owned-load ingress ACK')
        return ack

    def advance_load(self):
        state=self.fixture.state
        record=state['npcPersistence']['saved-six']
        scene={'playerLoaded':True,'cell':{'editorId':'QASmoke'}}
        menus={'messageBoxOpen':False,'openMenus':[],'menuStates':[]}
        if self.load_stage==0:
            state['ownedWorldGeneration']=2
            state['gameplayBootstrap'].update(completed=True,loadedOwnedSave='saved-six',scene=scene,menus=menus)
            state['ownedLoadTransition'].update(completed=True,afterGame=copy.deepcopy(self.fixture.game),worldGeneration=2,scene=scene,
                events=[{'seq':1,'topic':'lifecycle','data':{'event':'preLoadGame'}},
                        {'seq':2,'topic':'lifecycle','data':{'event':'postLoadGame'}}],cursor=2)
            state['ownedLoadHistory'][-1]=copy.deepcopy(state['ownedLoadTransition'])
            self.load_stage=1
        else:
            receipt=copy.deepcopy(record['savedReceipt'])
            receipt.update(phase='loaded',loadOrdinal=1)
            rebindings,replacements={},{}
            for index,row in enumerate(receipt['actors']):
                old=record['fixtures'][row['tag']]
                ref,vm=f'0xFF100{index:03X}',str(19000+index)
                row.update(currentReference=ref,resolvedReference=ref,currentVmHandle=vm,resolvedVmHandle=vm,
                           formResolved=True,handleResolved=True,runtimeHandle=1700+index)
                actor=dict(old['actor'],reference=ref)
                incarnation={'sessionId':'observer','loadGeneration':2,'runtimeHandle':1700+index}
                witness={'saveTag':'saved-six','bindingId':record['bindingId'],'native':copy.deepcopy(row),'worldGeneration':2}
                rebindings[row['tag']]={'actor':actor,'incarnation':incarnation,'restorationWitness':copy.deepcopy(witness)}
                replacement=copy.deepcopy(old)
                replacement.update(status='created',reference=ref,actor=copy.deepcopy(actor),incarnation=copy.deepcopy(incarnation),
                                   restorationWitness=copy.deepcopy(witness),worldGeneration=2)
                replacements[row['tag']]=replacement
            record.update(status='loaded',loadedReceipt=receipt,rebindings=rebindings,afterWorldGeneration=2)
            state['interactiveActorFixtures']=replacements
            state['phase']='interactive-session'
            state['deadline']=record['interactiveWindow']['deadline']
            self.load_fault(state)
            command=self.pending_load
            self.fixture.bus.complete(self.fixture.session_id,command['id'],command['claimId'],self.fixture.binding,
                {'save':{'loadedOwnedPairCount':1,'actorRemapWitnessCount':6,'worldReady':True}})
            self.pending_load=None
        self.fixture.write_state()


class OwnedLoadCompanionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.fixture=Fixture(Path(temporary.name))
        state=self.fixture.state
        settings=state['configuration']['interactive_session']
        settings.update(npcPersistence=True,morphSession={'bindings':{'reviewed':'native-role'},'testKeys':['Fixture.Test.One']},maximumSeconds=180)
        state['configuration']['allow_owned_save_load']=True
        state['interactiveSession']['maximumSeconds']=180
        state['deadline']=time.time()+180
        state['ownedWorldGeneration']=1
        state['ownedLoadHistory']=[]
        fixtures,rows={},[]
        for index in range(6):
            tag,ref,creation=f'Actor{index}',f'0xFF000{index:03X}',f'{index+1:032x}'
            actor={'reference':ref,'base':'0x00013475','sex':'male','race':'0x00013746','weight':50,'loaded3D':True}
            inc={'sessionId':'observer','loadGeneration':1,'runtimeHandle':700+index}
            entry={'tag':tag,'status':'created','runId':self.fixture.run_id,'creationId':creation,'reference':ref,'createdReference':ref,
                'base':actor['base'],'game':copy.deepcopy(self.fixture.game),'worldGeneration':1,'actor':actor,'incarnation':inc,
                'creationWitness':{'reference':ref,'creationId':creation,'forcePersist':True},
                'savedObservation':{'actor':copy.deepcopy(actor),'incarnation':copy.deepcopy(inc)}}
            fixtures[tag]=entry
            rows.append({'tag':tag,'creationId':creation,'base':actor['base'],'savedReference':ref,'currentReference':ref,
                'savedVmHandle':str(9000+index),'currentVmHandle':str(9000+index),'runtimeHandle':700+index,'persistent':True})
        state['interactiveActorFixtures']=copy.deepcopy(fixtures)
        receipt={'schemaVersion':1,'protocol':'npc-persistence/1','pid':self.fixture.game['pid'],'providerSession':'native',
            'bindingId':'b'*32,'runId':self.fixture.run_id,'saveTag':'saved-six','phase':'saved','saveOrdinal':1,'loadOrdinal':0,'actors':rows}
        state['npcPersistence']={'saved-six':{'status':'saved','saveTag':'saved-six','bindingId':'b'*32,'runId':self.fixture.run_id,
            'game':copy.deepcopy(self.fixture.game),'worldGeneration':1,'loadAttempted':False,'fixtures':fixtures,'savedReceipt':receipt}}
        state['ownedSaves']={'saved-six':{'completed':True,'ownedByAttempt':True,'stem':'Autotest_saved_six',
            'files':{'ess':{'sha256':'1'*64,'bytes':100},'skse':{'sha256':'2'*64,'bytes':100}}}}
        plan=tool.decoded(self.fixture.plan.read_bytes());plan['bounds']['maximumSeconds']=120
        self.fixture.plan.write_bytes(tool.encoded(plan))
        self.fixture.client=OwnedLoadClient(self.fixture)
        self.fixture.write_state()

    def envelope(self,timeout=60,tag='saved-six'):
        return {'schemaVersion':1,'operation':'tool','tool':'platform','timeoutSeconds':timeout,
            'args':{'operation':'object.perform','request':{'domain':'save-state','action':'load-owned-disposable-once',
                'saveLabel':tag,'maximumLoads':1,'processRestart':False}}}

    def intent(self,companion,envelope):
        companion.emit({'kind':'check-start','caseId':'case-a','role':'subject'})
        companion.emit({'kind':'measurement','caseId':'case-a','sequence':1,'request':envelope,'delivery':'intent'})
        return envelope

    def test_one_legitimate_frozen_same_process_load_adopts_bootstrap_only_after_all_six_native_remaps_and_bus_completion(self):
        companion=self.fixture.companion()
        original_end,original_deadline=companion.end,companion.native_deadline
        old_bootstrap=copy.deepcopy(companion.bootstrap)
        result=companion.exchange(self.intent(companion,self.envelope()))
        self.assertTrue(result['save']['worldReady'])
        self.assertEqual(companion.end,original_end)
        self.assertEqual(companion.native_deadline,original_deadline)
        self.assertNotEqual(companion.bootstrap,old_bootstrap)
        self.assertEqual(companion.bootstrap['loadedOwnedSave'],'saved-six')
        self.assertEqual(companion.world_generation,2)
        self.assertEqual(companion.owned_load_attempts,1)
        self.assertEqual(len(companion.report['ownedLoads']),1)
        self.assertEqual(companion.report['ownedLoads'][0]['actorWitnessCount'],6)
        self.assertTrue(companion.report['actions'][0]['ownedLoad']['adopted'])
        companion.check_state()
        self.assertEqual(len(companion.report['ownedLoads']),1)
        self.assertEqual(sum(op=='submit' for op,args in self.fixture.client.calls),1)
        envelope=self.envelope()
        companion.emit({'kind':'measurement','caseId':'case-a','sequence':2,'request':envelope,'delivery':'intent'})
        with self.assertRaises(tool.CompanionError):companion.exchange(envelope)
        self.assertEqual(sum(op=='submit' for op,args in self.fixture.client.calls),1)

    def test_wrong_tag_refuses_before_submit(self):
        companion=self.fixture.companion()
        with self.assertRaises(tool.CompanionError):
            companion.exchange(self.intent(companion,self.envelope(tag='unowned')))
        self.assertFalse(any(op=='submit' for op,args in self.fixture.client.calls))

    def test_disabled_load_refuses_before_submit(self):
        self.fixture.state['configuration']['interactive_session']['npcPersistence']=False;self.fixture.write_state()
        companion=self.fixture.companion()
        with self.assertRaises(tool.CompanionError):companion.exchange(self.intent(companion,self.envelope()))
        self.assertFalse(any(op=='submit' for op,args in self.fixture.client.calls))

    def test_changed_frozen_configuration_refuses_before_submit(self):
        companion=self.fixture.companion()
        self.fixture.state['configuration']['interactive_session']['morphSession']['extra']=True;self.fixture.write_state()
        with self.assertRaises(tool.CompanionError):companion.exchange(self.intent(companion,self.envelope()))
        self.assertFalse(any(op=='submit' for op,args in self.fixture.client.calls))

    def test_unexpected_bootstrap_change_has_no_generic_exception(self):
        companion=self.fixture.companion()
        self.fixture.state['gameplayBootstrap']['completed']=False;self.fixture.write_state()
        with self.assertRaisesRegex(tool.CompanionError,'outstanding delivered owned load'):companion.check_state()

    def test_pending_load_with_wrong_actual_command_or_tag_provenance_is_terminal(self):
        companion=self.fixture.companion()
        self.fixture.client.load_fault=lambda state:state['npcPersistence']['saved-six'].update(loadCommandId='a'*32)
        with self.assertRaisesRegex(tool.CompanionError,'provenance changed'):
            companion.exchange(self.intent(companion,self.envelope()))
        self.assertTrue(companion.poisoned)
        self.assertNotIn('ownedLoads',companion.report)
        self.assertEqual(sum(op=='submit' for op,args in self.fixture.client.calls),1)

    def test_completed_native_record_with_wrong_vm_never_adopts_or_replays(self):
        companion=self.fixture.companion()
        def corrupt(state):
            record=state['npcPersistence']['saved-six']
            if record['status']=='loaded':record['loadedReceipt']['actors'][-1]['resolvedVmHandle']='42'
        self.fixture.client.load_fault=corrupt
        envelope=self.intent(companion,self.envelope())
        with self.assertRaisesRegex(tool.CompanionError,'saved VM/form'):companion.exchange(envelope)
        with self.assertRaises(tool.CompanionError):companion.exchange(envelope)
        self.assertNotIn('ownedLoads',companion.report)
        self.assertEqual(sum(op=='submit' for op,args in self.fixture.client.calls),1)

    def test_lost_load_ack_keeps_delivery_and_uncertainty_without_bootstrap_adoption_or_replay(self):
        companion=self.fixture.companion();self.fixture.client.lose_ack=True
        envelope=self.intent(companion,self.envelope())
        with self.assertRaises(OSError):companion.exchange(envelope)
        self.assertTrue(companion.report['subjectStarted'])
        self.assertTrue(companion.report['uncertain'])
        self.assertEqual(companion.owned_load_attempts,1)
        self.assertNotIn('ownedLoads',companion.report)
        with self.assertRaises(tool.CompanionError):companion.exchange(envelope)
        self.assertEqual(sum(op=='submit' for op,args in self.fixture.client.calls),1)

    def test_unchanged_shared_deadline_and_timed_out_load_are_terminal(self):
        companion=self.fixture.companion();self.fixture.client.complete_load=False
        original_end=companion.end
        envelope=self.intent(companion,self.envelope(timeout=.1))
        with self.assertRaisesRegex(tool.CompanionError,'completion deadline'):companion.exchange(envelope)
        self.assertEqual(companion.end,original_end)
        self.assertTrue(companion.report['uncertain'])
        with self.assertRaises(tool.CompanionError):companion.exchange(envelope)
        self.assertEqual(sum(op=='submit' for op,args in self.fixture.client.calls),1)

    def test_only_exact_owned_load_receives_long_timeout_and_never_a_restart_or_changed_deadline(self):
        companion=self.fixture.companion()
        envelope=self.envelope();envelope['args']['request']['processRestart']=True
        with self.assertRaises(tool.CompanionError):companion.exchange(self.intent(companion,envelope))
        self.assertFalse(any(op=='submit' for op,args in self.fixture.client.calls))

    def test_native_deadline_extension_during_owned_load_is_rejected(self):
        companion=self.fixture.companion()
        self.fixture.client.load_fault=lambda state:state.update(deadline=state['deadline']+1)
        with self.assertRaisesRegex(tool.CompanionError,'provenance changed'):
            companion.exchange(self.intent(companion,self.envelope()))
        self.assertNotIn('ownedLoads',companion.report)

    def test_postload_heartbeat_failure_prevents_bootstrap_adoption(self):
        companion=self.fixture.companion()
        def stale(state):
            if state['npcPersistence']['saved-six']['status']=='loaded':self.fixture.pulse_age=999
        self.fixture.client.load_fault=stale
        with self.assertRaisesRegex(tool.CompanionError,'heartbeat'):
            companion.exchange(self.intent(companion,self.envelope()))
        self.assertNotIn('ownedLoads',companion.report)

    def test_missing_serialized_saved_vm_is_refused_before_delivery(self):
        self.fixture.state['npcPersistence']['saved-six']['savedReceipt']['actors'][0].pop('savedVmHandle')
        self.fixture.write_state()
        companion=self.fixture.companion()
        with self.assertRaisesRegex(tool.CompanionError,'serialized reference/VM'):
            companion.exchange(self.intent(companion,self.envelope()))
        self.assertFalse(any(op=='submit' for op,args in self.fixture.client.calls))


if __name__ == '__main__':
    unittest.main()
