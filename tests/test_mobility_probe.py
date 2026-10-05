import unittest
from unittest.mock import patch

from skyrim_autotest import mobility_probe, scenarios


class MobilityProbeTests(unittest.TestCase):
    def test_minimal_probe_does_not_require_higgs_or_a_save(self):
        scenarios.validate({'schemaVersion': 1, 'kind': 'vr-mobility-probe',
                            'cell': 'RealmLorkhan', 'physicalGrab': False,
                            'allowBackgroundVR': True})

    def test_invalid_scope_parameters_fail_before_launch(self):
        for key, value in [('cell', 'QASmoke;qqq'), ('physicalGrab', 1),
                           ('observer', 'yes'), ('keyboardDiagnostics', []), ('allowBackgroundVR', 1)]:
            scenario = {'schemaVersion': 1, 'kind': 'vr-mobility-probe', 'cell': 'RealmLorkhan', key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                scenarios.validate(scenario)

    def test_published_frame_is_not_accepted_as_observed_tracking(self):
        with self.assertRaises(AssertionError):
            mobility_probe.tracked_xyz({'published': True, 'acknowledgedByDriver': False})

    def test_unavailable_or_malformed_tracking_fails(self):
        for device in [{'valid': False}, {'valid': True, 'matrix': [0] * 11},
                       {'valid': True, 'matrix': [float('nan')] * 12},
                       {'valid': True, 'matrix': [True] * 12}]:
            with self.subTest(device=device), self.assertRaises(AssertionError):
                mobility_probe.tracked_xyz(device)

    def test_sampling_failure_still_releases_exact_owned_key(self):
        class Session:
            state = {'id': 'test-owner'}
            def __init__(self): self.calls = []
            def tool(self, name, args): self.calls.append((name, args))
        session = Session()
        def fail(): raise RuntimeError('read failed')
        with self.assertRaisesRegex(RuntimeError, 'read failed'):
            mobility_probe.keyboard_hold(session, 'W', 1, fail)
        self.assertEqual([args['action'] for _, args in session.calls], ['down', 'up'])
        self.assertEqual(session.calls[-1][1]['owner'], 'autotest-test-owner')
        self.assertEqual(session.calls[-1][1]['key'], 'W')
        self.assertNotIn('force', session.calls[-1][1])
        self.assertEqual(session.calls[0][1]['maxHoldMs'], 4000)

    def test_failed_acquire_does_not_release_another_owner(self):
        class Session:
            state = {'id': 'test-owner'}
            def __init__(self): self.calls = []
            def tool(self, name, args):
                self.calls.append(args)
                raise RuntimeError('conflicting owner')
        session = Session()
        with self.assertRaisesRegex(RuntimeError, 'conflicting owner'):
            mobility_probe.keyboard_hold(session, 'SPACE', .1)
        self.assertEqual(len(session.calls), 1)

    def test_probe_rejects_diagnostic_backend_before_any_mutation(self):
        class Session:
            state = {'inputBackend': 'devbench', 'driverBackend': 'file'}
        with self.assertRaisesRegex(ValueError, 'physical file adapter'):
            mobility_probe.execute(Session(), {'kind': 'vr-mobility-probe'})
