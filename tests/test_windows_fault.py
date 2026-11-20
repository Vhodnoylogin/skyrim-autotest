from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
from threading import RLock
import unittest
from unittest.mock import patch

from skyrim_autotest.run_review import review_directory
from skyrim_autotest.runner import Session
from skyrim_autotest.windows_fault import capture_windows_fault


GAME = {'pid': 47, 'birth': 0x01DD78FD814F3382, 'path': r'D:\Тест\SkyrimVR.exe'}
EXIT = {'schemaVersion': 1, 'status': 'exited', 'handleRetained': True,
        'exitCodeAvailable': True, 'identityVerified': True, 'identity': GAME,
        'expectedIdentity': GAME, 'exitCode': 0xC0000005, 'exitCodeHex': '0xC0000005',
        'firstExitObservedAtUtc': '2026-11-20T14:44:49.007Z'}
STATE = {'game': GAME, 'gameProcessObservations': [EXIT]}


def _event(record=102979, **fields):
    time = fields.pop('time', '2026-11-20T14:44:40.4056357Z')
    data = {'AppPath': r'd:\ТЕСТ\SKYRIMVR.EXE', 'ProcessId': '0x2f',
            'ProcessCreationTime': '0x1dd78fd814f3382', 'ExceptionCode': 'c0000005',
            'ModuleName': 'SkyrimVR.exe', 'FaultingOffset': '0000000000e3ed1d',
            'ModulePath': r'D:\private-hidden\SkyrimVR.exe', **fields}
    body = ''.join(f'<Data Name="{key}">{value}</Data>' for key, value in data.items())
    return ('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
            '<Provider Name="Application Error"/><EventID>1000</EventID>'
            f'<TimeCreated SystemTime="{time}"/><EventRecordID>{record}</EventRecordID>'
            f'</System><EventData>{body}</EventData></Event>')


def _events(*events):
    return ('<Events>' + ''.join(events) + '</Events>').encode('utf-16')


class WindowsFaultTests(unittest.TestCase):
    def test_matches_actual_event_1000_format_and_keeps_only_diagnostic_fields(self):
        def read(start, end):
            self.assertEqual(start, datetime.fromisoformat('2026-11-20T14:44:19.007Z'))
            self.assertEqual(end, datetime.fromisoformat('2026-11-20T14:45:19.007Z'))
            return _events(_event(), _event(102980, ProcessId='0x41'))

        self.assertEqual(capture_windows_fault(STATE, read_events=read), {
            'status': 'matched', 'eventId': 1000, 'recordId': 102979,
            'timeUtc': '2026-11-20T14:44:40.405635+00:00', 'module': 'SkyrimVR.exe',
            'offsetHex': '0xE3ED1D', 'exceptionHex': '0xC0000005',
        })

    def test_reused_pid_other_executable_exception_and_stale_event_refuse_correlation(self):
        xml = _events(_event(ProcessCreationTime='0x1dd78fd814f3390'),
                      _event(AppPath=r'C:\Other\SkyrimVR.exe'), _event(ExceptionCode='c0000374'),
                      _event(time='2026-11-20T14:43:39.001Z'))
        self.assertEqual(capture_windows_fault(STATE, read_events=lambda *_: xml), {'status': 'no-match'})

    def test_ambiguous_and_unavailable_event_reads_stay_distinct(self):
        full = _events(*[_event(index, ProcessId='0x41') for index in range(32)])
        cases = [(_events(_event(), _event(102980)), 'ambiguous'),
                 (b'<broken>', 'unavailable'), (full, 'unavailable')]
        for xml, expected in cases:
            with self.subTest(expected=expected, size=len(xml)):
                self.assertEqual(capture_windows_fault(STATE, read_events=lambda *_: xml)['status'], expected)
        with patch('skyrim_autotest.windows_fault._read_application_events',
                   side_effect=subprocess.TimeoutExpired('wevtutil', 3)) as read:
            self.assertEqual(capture_windows_fault(STATE, read_events=read)['reason'], 'event-log-query-failed')

    def test_unknown_or_zero_exit_does_not_read_event_log(self):
        normal = dict(EXIT, exitCode=0, exitCodeHex='0x00000000')
        for state in ({}, dict(STATE, gameProcessObservations=[normal]), dict(STATE, game=dict(GAME, pid=77))):
            self.assertIsNone(capture_windows_fault(state, read_events=lambda *_: self.fail('unexpected read')))
        undated = dict(EXIT, firstExitObservedAtUtc=None)
        self.assertEqual(capture_windows_fault(dict(STATE, gameProcessObservations=[undated]),
                                              read_events=lambda *_: self.fail('unexpected read'))['reason'],
                         'missing-exit-time')

    def test_default_replay_uses_retained_result_and_opt_in_replay_is_read_only(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            payload = json.dumps(dict(STATE, windowsFault={'status': 'no-match'})).encode()
            state.write_bytes(payload)
            with patch('skyrim_autotest.windows_fault.capture_windows_fault',
                       return_value={'status': 'unavailable'}) as read:
                self.assertEqual(review_directory(directory)['windowsFault']['status'], 'no-match')
                read.assert_not_called()
                self.assertEqual(review_directory(directory, query_windows_fault=True)['windowsFault']['status'],
                                 'unavailable')
                read.assert_called_once()
            self.assertEqual(state.read_bytes(), payload)

    def test_terminal_report_saves_one_observation_and_keeps_the_scenario_result(self):
        with TemporaryDirectory() as directory:
            session = Session.__new__(Session)
            session.dir = Path(directory)
            session.state = dict(STATE, id='owned-run', preflight={'profile': 'test'},
                                 result='failed', scenarioResult='passed', restored=True)
            session.lock = RLock()
            session.heartbeat_thread_id = None
            observed = capture_windows_fault(STATE, read_events=lambda *_: _events(_event()))
            with patch('skyrim_autotest.windows_fault.capture_windows_fault', return_value=observed) as read:
                session.report()
                session.report()
                read.assert_called_once()
            review = review_directory(session.dir)
            self.assertEqual(review['windowsFault'], observed)
            self.assertEqual((review['result'], review['scenarioResult'], review['restored']),
                             ('failed', 'passed', True))
            self.assertIn('SkyrimVR.exe+0xE3ED1D', (session.dir / 'report.md').read_text())
