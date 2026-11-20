import json
from threading import Event
from time import monotonic
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest.readiness_reads import ReadinessSession
from skyrim_autotest.runner import HTTPResponseError, Session


ARGS = {'op': 'get', 'menu': 'Main Menu', 'path': '_root.MenuHolder.Menu_mc.strCurrentState'}
ABANDONED = ('main-thread task did not start within 5000ms; queued task abandoned '
             '(101 frames elapsed -- main thread busy) [blocked by Main Menu: the game is at the main menu; '
             'load a save with game action=load or loadLast]')


class ReadinessRequestTraceTests(unittest.TestCase):
    def session(self):
        session = Session.__new__(Session)
        session.heartbeat_failed = Event()
        session.state = {'port': 1234, 'game': {'pid': 23}}
        session.log = Mock()
        return session

    def test_actual_main_menu_variant_links_two_events_and_retries_one_read(self):
        session = self.session()
        error = HTTPResponseError(504, 'api/tool/gfx', json.dumps({'code': 504, 'error': ABANDONED}))
        healthy = {'pid': 23}
        response = {'value': 'title'}
        with (patch('skyrim_autotest.runner.request', side_effect=[healthy, error, healthy, response]) as request,
              patch('skyrim_autotest.runner.native.alive', return_value=True),
              patch('skyrim_autotest.readiness_reads.time.sleep')):
            got = ReadinessSession(session, monotonic() + 5).tool('gfx', ARGS)
        self.assertEqual(got, response)
        self.assertEqual(request.call_count, 4)
        failure, decision, success = session.log.call_args_list
        self.assertEqual([row.args[0] for row in (failure, decision, success)],
                         ['tool-error', 'common-readiness-abandoned-read', 'tool'])
        self.assertTrue(failure.kwargs['clientRequestId'])
        self.assertEqual(failure.kwargs['clientRequestId'], decision.kwargs['clientRequestId'])
        self.assertNotEqual(failure.kwargs['clientRequestId'], success.kwargs['clientRequestId'])

    def test_same_response_is_terminal_for_other_menus_mutations_and_unknown_suffix(self):
        for args, message in ((dict(ARGS, menu='Other Menu'), ABANDONED),
                              (dict(ARGS, op='set'), ABANDONED), (ARGS, ABANDONED + ' unknown')):
            with self.subTest(args=args, message=message):
                session = self.session()
                error = HTTPResponseError(504, 'api/tool/gfx', json.dumps({'code': 504, 'error': message}))
                with (patch('skyrim_autotest.runner.request', side_effect=[{'pid': 23}, error]) as request,
                      patch('skyrim_autotest.runner.native.alive', return_value=True)):
                    with self.assertRaises(HTTPResponseError):
                        ReadinessSession(session, monotonic() + 5).tool('gfx', args)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(session.log.call_args.args[0], 'tool-error')
