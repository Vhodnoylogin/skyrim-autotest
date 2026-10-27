"""Small identity-bound heartbeat persistence, separate from mutable run state."""
import copy
import json
import math
import ntpath
from pathlib import Path
import time

RECOVERY_KEYS = ('owned', 'hardwareFrame', 'hardwareOwner', 'hardwareHoldUntil', 'hardwareHoldUntilTickMs')


def _identity(ident):
    return (isinstance(ident,dict) and set(ident)=={'pid','birth','path'} and type(ident['pid']) is int
            and type(ident['birth']) is int and ident['pid']>0 and ident['birth']>0
            and isinstance(ident['path'],str) and bool(ident['path']))


def _owned_capture(state, ident):
    """A new role cannot authorize its own adoption from the sidecar."""
    capture,config=state.get('crashCapture'),state.get('configuration')
    game=state.get('game')
    if not isinstance(capture,dict) or not isinstance(config,dict) or not _identity(game):return False
    setting=config.get('crash_capture')
    return (config.get('game_edition')=='se' and isinstance(setting,dict) and setting.get('provider')=='cdb'
            and isinstance(setting.get('executable'),str) and bool(setting['executable'])
            and ntpath.normcase(ntpath.normpath(setting['executable']))==ntpath.normcase(ntpath.normpath(ident['path']))
            and type(capture.get('schemaVersion')) is int and capture['schemaVersion']==1 and capture.get('provider')=='cdb'
            and capture.get('debugger')==ident and capture.get('target')==game
            and isinstance(state.get('owned'),list)
            and any(isinstance(row,dict) and row.get('role')=='game' and row.get('identity')==game
                    for row in state.get('owned',[])))


def snapshot(state, error=None):
    # These fields are mutated under Session.lock; do not traverse lifecycle,
    # checks, snapshots or arbitrary subject state owned by the main thread.
    return {'schemaVersion':1, 'id':state['id'], 'runner':copy.deepcopy(state.get('runner')),
            'at':time.time(), 'healthy':error is None, 'error':error,
            'recovery':{k:copy.deepcopy(state[k]) for k in RECOVERY_KEYS if k in state}}


def read(directory, state, filename='heartbeat.json'):
    try:
        value=json.loads((Path(directory)/filename).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    if (not isinstance(value,dict) or value.get('schemaVersion')!=1 or value.get('id')!=state.get('id')
            or value.get('runner')!=state.get('runner') or type(value.get('healthy')) is not bool
            or type(value.get('at')) not in (int,float) or not math.isfinite(value['at'])
            or value['at']>time.time()+5 or not isinstance(value.get('recovery'),dict)
            or set(value['recovery'])-set(RECOVERY_KEYS)):
        return None
    owned=value['recovery'].get('owned',[])
    if not isinstance(owned,list) or len(owned)>1024:return None
    for row in owned:
        if not isinstance(row,dict):return None
        ident=row.get('identity')
        if not _identity(ident):return None
        if row.get('role') not in ('game','loader','mo2','vr'):
            if row.get('role')!='crash-capture' or not _owned_capture(state,ident):return None
    return value


def restore(directory, state):
    pulses=[p for name in ('heartbeat.json','input-state.json')
            if (p:=read(directory,state,name)) is not None]
    for pulse in sorted(pulses,key=lambda p:p['at']):
        for row in pulse['recovery'].get('owned',[]):
            if row not in state.setdefault('owned',[]):state['owned'].append(row)
        if pulse['at']>state.get('stateSavedAt',state.get('heartbeat',0)):
            for key in RECOVERY_KEYS:
                if key!='owned' and key in pulse['recovery']:state[key]=copy.deepcopy(pulse['recovery'][key])


def observed_at(directory, state):
    pulse=read(directory,state)
    return max(state.get('heartbeat',0),pulse['at'] if pulse else 0),pulse


def guardian_deadlines(directory, state):
    """Record the exact bound pulse used for the existing guardian time limits."""
    pulse_at,pulse=observed_at(directory,state)
    now=time.time()
    deadline=state.get('deadline',now+1)
    stopping=state.get('phase','').startswith('stop-and-restore')
    reasons=[]
    if now>deadline+15:reasons.append('phase-deadline-exceeded')
    if now-pulse_at>35:reasons.append('runner-heartbeat-expired')
    if pulse and not pulse['healthy'] and not stopping:reasons.append('heartbeat-reported-failure')
    return {'at':now,'phase':state.get('phase'),'deadline':deadline,
            'stateHeartbeat':state.get('heartbeat'),'pulseAt':pulse_at,
            'pulse':pulse,'reasons':reasons}
