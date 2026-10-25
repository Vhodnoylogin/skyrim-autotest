import unittest
from unittest.mock import patch
from skyrim_autotest import runner, se_startup


def event(seq, topic, data):
    return {'seq': seq, 'topic': topic, 'data': data}


LOADED = event(1, 'lifecycle', {'event': 'dataLoaded'})
MENU = event(2, 'menu', {'name': 'Main Menu', 'opening': True})


class Session:
    def __init__(self):
        self.state = {'game': {'pid': 12, 'birth': 34, 'path': 'SkyrimSE.exe'}, 'port': 8920}
        self.records = []
    def phase(self, *args): pass
    def save(self): pass
    def log(self, name, **data): self.records.append((name, data))


class SEStartupTests(unittest.TestCase):
    def run_gate(self, envelopes, *, pid=12, late=False):
        session, clock, routes = Session(), [0.0], []
        replies = iter(envelopes)
        def request(port, route, **kwargs):
            routes.append(route)
            if route == 'api/health':
                return {'pid': pid, 'frame': 1}
            self.assertTrue(route.startswith('api/events?since='))
            result = next(replies)
            if late: clock[0] = 2.0
            return result
        def sleep(seconds): clock[0] += seconds
        with patch.object(runner, 'request', side_effect=request), \
             patch.object(runner.native, 'alive', return_value=True), \
             patch.object(se_startup.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(se_startup.time, 'sleep', side_effect=sleep):
            se_startup.wait_main_menu(session, timeout=1)
        return session, routes

    def test_gate_waits_for_real_native_events_without_task_requests(self):
        session, routes = self.run_gate([
            {'events': [], 'headSeq': 0},
            {'events': [LOADED], 'headSeq': 1},
            {'events': [MENU], 'headSeq': 2}])
        self.assertTrue(session.state['seStartupAdmission']['completed'])
        self.assertEqual(session.state['seStartupAdmission']['cursor'], 2)
        self.assertFalse(any('api/tool/' in route for route in routes))
        self.assertIn('not gameplay readiness', session.state['seStartupAdmission']['basis'])

    def test_unobserved_newer_head_must_be_drained(self):
        session, routes = self.run_gate([
            {'events': [LOADED, MENU], 'headSeq': 3},
            {'events': [event(3, 'menu', {'name': 'Cursor Menu', 'opening': True})], 'headSeq': 3}])
        self.assertEqual(session.state['seStartupAdmission']['cursor'], 3)
        self.assertIn('api/events?since=2', routes)

    def test_gap_reset_malformed_and_foreign_health_refuse(self):
        for envelope in ({'events': [MENU], 'headSeq': 2},
                         {'events': [LOADED], 'headSeq': 0},
                         {'events': [], 'headSeq': False}):
            with self.subTest(envelope=envelope), self.assertRaises(runner.Blocked):
                self.run_gate([envelope])
        with self.assertRaisesRegex(runner.Blocked, 'identity changed'):
            self.run_gate([], pid=13)

    def test_world_transition_is_not_initial_menu_admission(self):
        with self.assertRaisesRegex(runner.Blocked, 'Unexpected world transition'):
            self.run_gate([{'events': [event(1, 'lifecycle', {'event': 'newGame'})], 'headSeq': 1}])

    def test_late_affirmative_response_never_admits(self):
        with self.assertRaisesRegex(runner.Blocked, 'deadline'):
            self.run_gate([{'events': [LOADED, MENU], 'headSeq': 2}], late=True)

    def test_main_menu_close_revokes_startup_admission(self):
        events = [LOADED, MENU, event(3, 'menu', {'name': 'Main Menu', 'opening': False})]
        with self.assertRaisesRegex(runner.Blocked, 'deadline'):
            self.run_gate([{'events': events, 'headSeq': 3}] + [{'events': [], 'headSeq': 3}]*4)
