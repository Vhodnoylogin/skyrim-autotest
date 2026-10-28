"""One owned quit request followed by its original bounded observation grace.

The window route posts an ordinary owned WM_CLOSE once; it never terminates a
process. The caller owns any fallback after the original observation grace,
and exit telemetry remains distinct from scenario checks.
"""
from __future__ import annotations

import copy
import math
import time

from . import native


def _identity(value):
    if (type(value) is not dict or set(value) != {'pid', 'birth', 'path'}
            or type(value.get('pid')) is not int or value['pid'] <= 0
            or type(value.get('birth')) is not int or value['birth'] <= 0
            or not isinstance(value.get('path'), str) or not value['path'] or '\0' in value['path']):
        raise ValueError('Graceful game exit requires exact PID/birth/path identity')
    return copy.deepcopy(value)


def _alive(session, game, *, before_request=False):
    if session.state.get('game') != game:
        raise RuntimeError('Owned game identity changed during graceful exit')
    if not any(row.get('role') == 'game' and row.get('identity') == game
               for row in session.state.get('owned', [])):
        raise RuntimeError('Graceful exit requires the exact owned game process')
    # The shutdown barrier protects mutations. Once qqq is requested, observing
    # our retained identity must not be interrupted by an unrelated transient
    # process row. The caller guards every later mutation/restoration separately.
    if before_request:
        session.guard_shutdown()
    if session.state.get('game') != game:
        raise RuntimeError('Owned game identity changed during graceful exit guard')
    current = native.identity(game['pid'])
    if current is not None and current != game:
        raise RuntimeError('Game PID now belongs to a different process; graceful exit refused')
    return native.alive(game)


def _capture_exited(session, game):
    """A failed live identity lookup is not proof that the retained handle exited."""
    session.observe_game_exit('graceful-game-exit-observed')
    observations = session.state.get('gameProcessObservations', [])
    if not isinstance(observations, list):
        return False
    latest = next((row for row in reversed(observations) if isinstance(row, dict)
                   and row.get('identityVerified') is True and row.get('identity') == game
                   and row.get('expectedIdentity', game) == game), None)
    return latest is not None and latest.get('status') == 'exited'


def window_close_receipt(value):
    """A posted owned-window request is separate from actual process exit."""
    return (isinstance(value, dict) and value.get('requested') is True
            and value.get('systemCommand') is False and isinstance(value.get('windows'), list)
            and any(isinstance(row, dict) and type(row.get('hwnd')) is int and row['hwnd'] > 0
                    and type(row.get('message')) is int and row['message'] == 0x10
                    and row.get('accepted') is True and type(row.get('error')) is int and row['error'] == 0
                    for row in value['windows']))


def request_and_wait(session, seconds=10, *, route='qqq'):
    """Issue the selected owned quit request once, then observe actual exit.

    A durable matching intent is never dispatched again, even if its callback is
    unknown. Recovery retains the original monotonic deadline. A previous boot's
    dead process returns without creating a fresh grace or sending input.
    """
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 30:
        raise ValueError('Graceful game exit requires a finite grace in(0,30]seconds')
    if route not in ('qqq', 'window-close'):
        raise ValueError('Unknown owned graceful exit route')
    if not session.state.get('game'):
        return True
    game = _identity(session.state['game'])
    existing = session.state.get('gracefulGameExit')
    if existing is not None and (not isinstance(existing, dict) or existing.get('game') != game
                                 or existing.get('command') != route):
        raise RuntimeError('Previous graceful exit intent belongs to another game identity')
    alive = _alive(session, game, before_request=existing is None)
    if existing is None:
        if not alive:
            # No new quit request/grace is created for an already missing live
            # identity. Report gone only if actual retained telemetry proves it.
            return _capture_exited(session, game)
        started = time.monotonic()
        record = {'game': game, 'command': route, 'status': 'request-intent',
                  'startedMonotonic': started, 'deadlineMonotonic': started + seconds,
                  'graceSeconds': seconds, 'requestAttempted': False}
        session.state['gracefulGameExit'] = record
        session.save()  # Must precede the one potentially uncertain mutation.
        session.log('graceful-game-exit-request', **copy.deepcopy(record))
        if _alive(session, game, before_request=True):
            try:
                remaining = record['deadlineMonotonic'] - time.monotonic()
                if remaining > 0:
                    if route == 'window-close':
                        record['requestAttempted'] = True
                        session.save()  # Before the single possibly uncertain PostMessage operation.
                        response = native.close(game)
                        record['windowClose'] = copy.deepcopy(response)
                    else:
                        response = session.tool('console', {'action': 'exec', 'command': 'qqq'},
                                                timeout=min(4, remaining), deadline=record['deadlineMonotonic'])
                    record['requestAttempted'] = True
                    record['requestAcknowledgement'] = copy.deepcopy(response)
            except Exception as error:
                # Transport uncertainty does not authorize replay or a second
                # quit path while the original game grace is still running.
                record['requestAttempted'] = True
                record['requestError'] = {'type': type(error).__name__, 'message': str(error)}
            record['status'] = 'waiting'
            session.save()
    else:
        record = existing
        deadline = record.get('deadlineMonotonic')
        started = record.get('startedMonotonic')
        if (record.get('command') != route or type(deadline) not in (int, float)
                or type(started) not in (int, float) or not math.isfinite(deadline)
                or not math.isfinite(started) or not 0 < deadline - started <= 30):
            raise RuntimeError('Previous graceful exit deadline is unavailable; never replay its request')
    while True:
        alive = _alive(session, game)
        # Access/identity lookup can become unavailable while the retained
        # process handle still reports running. Keep observing within the same
        # deadline; neither that lookup failure nor a missing snapshot is exit.
        gone = _capture_exited(session, game) if not alive else False
        remaining = record['deadlineMonotonic'] - time.monotonic()
        if gone or remaining <= 0:
            record.update(status='observed-gone' if gone else 'grace-expired',
                          observedGone=gone, waitFinishedMonotonic=time.monotonic())
            session.save()
            session.log('graceful-game-exit-wait-finished', game=game, observedGone=gone,
                        deadlineMonotonic=record['deadlineMonotonic'],
                        waitFinishedMonotonic=record['waitFinishedMonotonic'])
            return gone
        time.sleep(min(.2, remaining))


def classify_exit(session):
    """Classify only actual latest identity-verified telemetry for this game."""
    state = session.state
    game = copy.deepcopy(state.get('game'))
    record = state.get('gracefulGameExit', {})
    own_quit = (isinstance(record, dict) and record.get('game') == game
                and record.get('requestAttempted') is True
                and (record.get('command') == 'qqq'
                     or (record.get('command') == 'window-close' and window_close_receipt(record.get('windowClose')))
                     or (record.get('command') == 'menu-main-quit'
                         and isinstance(record.get('desktopQuit'), dict)
                         and record['desktopQuit'].get('game') == game
                         and record['desktopQuit'].get('requestAttempted') is True)))
    forced = bool(state.get('forcedGameStop'))
    result = {'kind': 'forced_stop' if forced else 'unknown', 'game': game,
              'exitCode': None, 'exitCodeHex': None, 'exitCodeAvailable': False,
              'identityVerified': False, 'ownQuitRequest': own_quit, 'forcedGameStop': forced}
    observations = state.get('gameProcessObservations', [])
    if not isinstance(observations, list):
        result['reason'] = 'Game exit telemetry unavailable'
        return result
    latest = next((row for row in reversed(observations) if isinstance(row, dict)
                   and row.get('identityVerified') is True and game is not None
                   and row.get('identity') == game and row.get('expectedIdentity', game) == game), None)
    if latest is None:
        result['reason'] = 'No exact identity-verified game exit observation'
        return result
    result.update(identityVerified=True, observationStage=latest.get('stage'),
                  observedAtUtc=latest.get('observedAtUtc'))
    code = latest.get('exitCode')
    if (latest.get('status') != 'exited' or latest.get('exitCodeAvailable') is not True
            or type(code) is not int or not 0 <= code <= 0xFFFFFFFF):
        result['reason'] = 'Latest exact game observation has no actual exit code'
        return result
    result.update(exitCode=code, exitCodeHex=f'0x{code:08X}', exitCodeAvailable=True)
    if not forced:
        result['kind'] = 'abnormal_exit' if code else 'normal_close' if own_quit else 'unknown'
    if result['kind'] == 'unknown':
        result['reason'] = 'Exit0 has no recorded owned quit request'
    return result
