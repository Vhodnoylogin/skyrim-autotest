"""Small identity-bound heartbeat persistence, separate from mutable run state."""
import copy
import json
import math
from pathlib import Path
import time

RECOVERY_KEYS = ('owned', 'hardwareFrame', 'hardwareOwner', 'hardwareHoldUntil', 'hardwareHoldUntilTickMs')


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
        if not isinstance(row,dict) or row.get('role') not in ('game','loader','mo2','vr'):return None
        ident=row.get('identity')
        if (not isinstance(ident,dict) or set(ident)!={'pid','birth','path'} or type(ident['pid']) is not int
                or type(ident['birth']) is not int or ident['pid']<=0 or ident['birth']<=0
                or not isinstance(ident['path'],str) or not ident['path']):return None
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
