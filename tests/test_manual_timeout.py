"""Manual uncertainty retains ownership and admits reads, never another setter."""
import copy
import json
import unittest
from unittest.mock import patch

from skyrim_autotest import interactive, manual_timeout
from skyrim_autotest.command_bus import BusError
from tests import test_interactive as baseline


class ManualLoopTests(baseline.InteractiveTests):
    # Inherit the baseline loop regression tests; explicit opt-in only here.
    def test_manual_timeout_reads_then_finish_without_replay(self):
        self.settings['timeoutPolicy'] = 'preserve-manual'
        def ready():
            if not self.session.state.get('interactiveSession'):
                return
            if not self.session.state['interactiveSession'].get('mutationsPaused'):
                self.send('first', self.action())
            else:
                self.send('duplicate-fresh-id', self.action())
                self.send('late-read', {'schemaVersion': 1, 'operation': 'tool', 'tool': 'inspect',
                    'args': {'kind': 'scene'}, 'timeoutSeconds': .5})
                self.send('finish')
        self.session.on_save = ready
        self.session.on_tool = lambda: (_ for _ in ()).throw(TimeoutError('delivered result lost'))
        with patch.object(manual_timeout, 'observe', return_value={'commandOutcome': 'unknown', 'replayed': False}) as observed:
            result = self.run_loop()
        observed.assert_called_once()
        self.assertEqual(result['reason'], 'owner-finished')
        self.assertTrue(result['mutationsPaused'])
        self.assertEqual(len(result['uncertainCommandIds']), 1)
        self.assertEqual(len(self.session.actions), 1)
        self.assertEqual(self.bus.status(result['sessionId'])['commands'], {'uncertain': 1, 'completed': 3})
        self.assertTrue(any(kind == 'interactive-action-rejected' for kind, _ in self.session.logs))
        self.assertEqual(len(self.session.phases), 1)  # No deadline renewal/new native session.

    def test_late_result_is_preserved_but_not_replayed_or_automatically_completed(self):
        self.settings['timeoutPolicy'] = 'preserve-manual'
        def ready():
            if self.session.state.get('interactiveSession'):
                self.send('first', self.action())
                if self.session.state['interactiveSession'].get('mutationsPaused'):
                    self.send('finish')
        self.session.on_save = ready
        def late():
            self.clock.now += .6
            return {'nativeCallback': 'late-result'}
        self.session.on_tool = late
        with patch.object(manual_timeout, 'observe', return_value={'commandOutcome': 'unknown'}):
            result = self.run_loop()
        self.assertEqual(len(self.session.actions), 1)
        self.assertEqual(self.bus.status(result['sessionId'])['commands'], {'uncertain': 1, 'completed': 1})
        self.assertTrue(any(kind == 'interactive-action-result' and row['result'] == {'nativeCallback': 'late-result'}
                            for kind, row in self.session.logs))

    def test_review_lane_never_reclaims_uncertain_or_not_delivered_command(self):
        session_id = 'review-session'
        binding = {'provider': 'test', 'conversationId': 'test', 'agentId': 'test'}
        self.bus.create_session(session_id)
        self.bus.bind(session_id, binding)
        submitted = self.bus.submit(session_id, 'operator.actions', 'review-first', 'text', '{}')['command']
        claimed = self.bus.next(session_id, binding)['command']
        self.bus.delivered(session_id, claimed['id'], claimed['claimId'], binding)
        self.bus.reconcile(session_id, claimed['id'], binding, 'uncertain', 'test lost result')
        self.assertEqual(self.bus.next(session_id, binding)['blocked']['state'], 'uncertain')
        followup = self.bus.submit(session_id, 'operator.actions', 'review-second', 'text', '{}')['command']
        self.assertEqual(self.bus.next(session_id, binding, reviewOf=[submitted['id']])['command']['id'], followup['id'])
        self.bus.reconcile(session_id, submitted['id'], binding, 'not_delivered', 'external unsafe reconciliation')
        self.assertEqual(self.bus.next(session_id, binding, reviewOf=[submitted['id']])['blocked']['state'], 'review-binding-changed')
        with self.assertRaises(BusError):
            self.bus.next(session_id, dict(binding, agentId='foreign'), reviewOf=[submitted['id']])


class NativeObservationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_interactive import Session
        self.session = Session()
        self.session.state['ownedWorldGeneration'] = 1
        self.game = copy.deepcopy(self.session.state['game'])
        self.entry = {'status': 'created', 'runId': 'fresh-run', 'game': self.game, 'worldGeneration': 1,
            'reference': '0xFF000123', 'base': '0x00000456',
            'incarnation': {'sessionId': 'native-123', 'loadGeneration': 2, 'runtimeHandle': 1234}}
        self.session.state['interactiveActorFixtures'] = {'FHeavy': self.entry}
        self.request = {'operation': 'tool', 'tool': 'platform', 'args': {'operation': 'object.perform',
            'request': {'domain': 'actor-race', 'action': 'change-current-race', 'race': '0x000CDD84',
                        'actor': {'fixtureTag': 'FHeavy'}}}}
        self.raw = {'ok': True, 'sessionId': 'native-123', 'loadGeneration': 2,
            'sampleId': 614, 'producerMonotonicNs': 7856632862000,
            'refs': [{'status': 'available', 'deleted': False, 'disabled': False, 'loaded3D': True,
                'baseForm': self.entry['base'], 'identity': {'form': self.entry['reference'],
                    'loadGeneration': 2, 'runtimeHandle': 1234},
                'actor': {'status': 'available', 'raceStatus': 'available', 'baseForm': self.entry['base'], 'race': '0x000CDD84'}}]}
        self.session.on_tool = lambda: copy.deepcopy(self.raw)
    def observe(self):
        with patch.object(manual_timeout.native, 'alive', return_value=True):
            return manual_timeout.observe(self.session, self.request, manual_timeout.time.monotonic() + 6)
    def test_late_target_state_observed_without_claiming_causal_completion(self):
        result = self.observe()
        self.assertTrue(result['effectObserved'])
        self.assertEqual(result['commandOutcome'], 'unknown')
        self.assertEqual([name for name, _, _, _ in self.session.calls], ['inspect', 'inspect'])
    def test_wrong_pid_base_epoch_handle_and_unavailable_remain_unknown(self):
        changes = [('sessionId', 'other'), ('loadGeneration', 99), ('sampleId', 0), ('producerMonotonicNs', 0)]
        for field, value in changes:
            with self.subTest(field=field):
                original = self.raw[field]; self.raw[field] = value
                self.assertIsNone(self.observe()['effectObserved'])
                self.raw[field] = original
        row = self.raw['refs'][0]
        for field, value in [('baseForm', '0x00000007'), ('loaded3D', False), ('status', 'unavailable')]:
            with self.subTest(field=field):
                original = row[field]; row[field] = value
                self.assertIsNone(self.observe()['effectObserved'])
                row[field] = original
    def test_observed_old_race_does_not_prove_not_executed(self):
        self.raw['refs'][0]['actor']['race'] = '0x00013746'
        result = self.observe()
        self.assertFalse(result['effectObserved'])
        self.assertEqual(result['commandOutcome'], 'unknown')
    def test_read_timeout_retained_and_no_second_observation(self):
        self.session.on_tool = lambda: (_ for _ in ()).throw(TimeoutError('still pending'))
        result = self.observe()
        self.assertEqual(result['commandOutcome'], 'unknown')
        self.assertEqual(len(self.session.calls), 2)
        self.assertIn('still pending', result['observationError'])


if __name__ == '__main__':
    unittest.main()
