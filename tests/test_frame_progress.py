import unittest
from unittest.mock import patch

from skyrim_autotest import frame_progress, platform
from skyrim_autotest.platform_mapping import operations


REQUEST = {'domain': 'game-frame-progress', 'observationSeconds': .05, 'minimumAdvance': 1}


class Backend:
    def __init__(self):
        self.s = self
        self.state = {'id': 'run', 'game': {'pid': 123, 'birth': 456}, 'port': 9911, 'ownedWorldGeneration': 2,
                      'testProfile': 'owned-copy', 'gameplayBootstrap': {'completed': True}}
        self.guards = 0
    def remaining(self): return 1
    def pause(self, seconds): pass
    def guard_world(self): self.guards += 1
    def log(self, *_args, **_kwargs): pass


class FrameProgressTests(unittest.TestCase):
    def observe(self, samples, backend=None):
        with patch('skyrim_autotest.fixture_actors.native.alive', return_value=True), patch('skyrim_autotest.runner.request', side_effect=samples):
            return frame_progress.observe(backend or Backend(), REQUEST)

    def test_real_counter_advancement_is_observed(self):
        backend = Backend()
        value = self.observe([{'pid': 123, 'frame': 40}, {'pid': 123, 'frame': 42}], backend)
        self.assertTrue(value['gameFrames']['advanced'])
        self.assertEqual(value['gameFrames']['delta'], 2)
        self.assertEqual(backend.guards, 4)

    def test_responding_endpoint_with_frozen_frame_cannot_pass(self):
        value = self.observe([{'pid': 123, 'frame': 40}, {'pid': 123, 'frame': 40}])
        self.assertFalse(value['gameFrames']['advanced'])

    def test_wrong_pid_missing_bool_or_regressed_counter_refuses(self):
        for last in ({'pid': 999, 'frame': 41}, {'pid': 123}, {'pid': 123, 'frame': True}, {'pid': 123, 'frame': 39}):
            with self.subTest(last=last), self.assertRaises(ValueError):
                self.observe([{'pid': 123, 'frame': 40}, last])

    def test_world_change_across_observation_refuses(self):
        backend = Backend()
        def change(_): backend.state['ownedWorldGeneration'] += 1
        backend.pause = change
        with self.assertRaisesRegex(ValueError, 'World/run'):
            self.observe([{'pid': 123, 'frame': 40}, {'pid': 123, 'frame': 42}], backend)

    def test_transport_error_does_not_become_zero_or_success(self):
        with self.assertRaises(TimeoutError): self.observe([TimeoutError('health unavailable')])

    def test_process_incarnation_change_refuses_even_same_pid(self):
        backend = Backend()
        def change(_): backend.state['game']['birth'] += 1
        backend.pause = change
        with self.assertRaisesRegex(ValueError, 'exact owned'):
            self.observe([{'pid': 123, 'frame': 40}, {'pid': 123, 'frame': 42}], backend)

    def test_mapping_and_request_contract_keep_observation_read_only(self):
        platform.validate({'operation': 'world.read', 'request': REQUEST})
        self.assertIn('gameFrames.advanced', operations()['world.read']['fields'])
        for operation, req in [('object.perform', REQUEST), ('world.read', dict(REQUEST, minimumAdvance=0)),
                               ('world.read', dict(REQUEST, observationSeconds=100)), ('world.read', dict(REQUEST, url='other'))]:
            with self.subTest(operation=operation, request=req), self.assertRaises(ValueError):
                platform.validate({'operation': operation, 'request': req})
