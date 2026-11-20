"""Correlate an owned process exit with a bounded Windows Application Error read."""
from datetime import datetime, timedelta, timezone
import ntpath
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from .exit_projection import terminal_exit_observation


_NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}
_PROVIDER = 'Application Error'
_MAX_EVENTS = 32
_WINDOW = timedelta(seconds=30)


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _hex(value):
    if isinstance(value, str) and re.fullmatch(r'(?:0x)?[0-9a-f]{1,16}', value, re.I):
        return int(value, 16)
    return None


def _event_projection(event, game, exit_code, start, end):
    system = event.find('e:System', _NS)
    if system is None or system.findtext('e:EventID', namespaces=_NS) != '1000':
        return None
    provider = system.find('e:Provider', _NS)
    timestamp = system.find('e:TimeCreated', _NS)
    created = _utc(timestamp.get('SystemTime')) if timestamp is not None else None
    record = system.findtext('e:EventRecordID', '', _NS)
    if (provider is None or provider.get('Name') != _PROVIDER or created is None
            or not start <= created <= end or not re.fullmatch(r'[0-9]{1,20}', record)):
        return None
    data = event.findall('e:EventData/e:Data', _NS)
    fields = {item.get('Name'): item.text for item in data}
    app_path = fields.get('AppPath')
    if (len(fields) != len(data) or not app_path or not ntpath.isabs(app_path)
            or ntpath.normcase(app_path) != ntpath.normcase(game['path'])
            or _hex(fields.get('ProcessId')) != game['pid']
            or _hex(fields.get('ProcessCreationTime')) != game['birth']
            or _hex(fields.get('ExceptionCode')) != exit_code):
        return None
    module = fields.get('ModuleName')
    offset = _hex(fields.get('FaultingOffset'))
    if (not module or len(module) > 255 or not module.isprintable()
            or module != ntpath.basename(module) or offset is None):
        return None
    return {'eventId': 1000, 'recordId': int(record), 'timeUtc': created.isoformat(),
            'module': module, 'offsetHex': f'0x{offset:X}', 'exceptionHex': f'0x{exit_code:08X}'}


def project_events(xml, game, exit_code, start, end):
    """Project only Event 1000 records for this path, PID, creation time and code."""
    if len(xml) > 256 * 1024:
        return {'status': 'unavailable', 'reason': 'oversize-event-log-response'}
    try:
        root = ET.fromstring(xml)
        if root.tag != 'Events':
            raise ET.ParseError('Expected the requested Events root')
    except ET.ParseError:
        return {'status': 'unavailable', 'reason': 'invalid-event-log-response'}
    events = root.findall('e:Event', _NS)
    matches = [match for event in events
               if (match := _event_projection(event, game, exit_code, start, end)) is not None]
    if len(matches) > 1:
        return {'status': 'ambiguous', 'matchingRecords': len(matches)}
    if len(events) >= _MAX_EVENTS:
        return {'status': 'unavailable', 'reason': 'query-limit-reached'}
    if matches:
        return {'status': 'matched', **matches[0]}
    return {'status': 'no-match'}


def _read_application_events(start, end):
    windows = Path(os.environ['SystemRoot'])
    if not windows.is_absolute():
        raise OSError('Windows system directory unavailable')
    low, high = (bound.isoformat().replace('+00:00', 'Z') for bound in (start, end))
    query = (f"*[System[Provider[@Name='{_PROVIDER}'] and EventID=1000 and "
             f"TimeCreated[@SystemTime >= '{low}' and @SystemTime <= '{high}']]]")
    return subprocess.run([str(windows / 'System32' / 'wevtutil.exe'), 'qe', 'Application',
                           f'/q:{query}', '/f:xml', '/e:Events', '/rd:true', f'/c:{_MAX_EVENTS}'],
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=3, creationflags=subprocess.CREATE_NO_WINDOW).stdout


def capture_windows_fault(state, *, read_events=None):
    """Read diagnostic evidence only for a verified nonzero exit with a timestamp."""
    game = state.get('game')
    terminal = terminal_exit_observation(state.get('gameProcessObservations'), game)
    if terminal is None or terminal['exitCode'] == 0:
        return None
    exit_time = _utc(terminal.get('firstExitObservedAtUtc'))
    if exit_time is None:
        return {'status': 'unavailable', 'reason': 'missing-exit-time'}
    if read_events is None and os.name != 'nt':
        return {'status': 'unavailable', 'reason': 'unsupported-platform'}
    start, end = exit_time - _WINDOW, exit_time + _WINDOW
    try:
        xml = (read_events or _read_application_events)(start, end)
    except (OSError, KeyError, subprocess.SubprocessError):
        return {'status': 'unavailable', 'reason': 'event-log-query-failed'}
    return project_events(xml, game, terminal['exitCode'], start, end)
