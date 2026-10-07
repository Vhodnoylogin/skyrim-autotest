"""One bounded game-only restart; MO2, VR and the owned profile stay in place."""
import copy
import math
from pathlib import Path
import time


def expected_restart(state, now):
    """Guardian exception requires durable owned identity and a <=180s window."""
    value=state.get('gameRestartTransition',{})
    start,end=value.get('startedAt'),value.get('expiresAt')
    before=value.get('beforeGame')
    return (value.get('completed') is False and value.get('stage') in ('stopping','launching','loading') and
            type(start) in (int,float) and type(end) in (int,float) and
            math.isfinite(start) and math.isfinite(end) and 0<end-start<=180 and start<=now<end and
            state.get('configuration',{}).get('allow_owned_save_load') is True and
            not state.get('phase','').startswith('stop-and-restore') and
            any(p.get('role')=='game' and p.get('identity')==before for p in state.get('owned',[])))


def settle_owned_loaders(backend):
    """Wait for the old launch chain, closing only already owned SKSE identities."""
    from . import native
    from .runner import GAME_NAMES
    b, s = backend, backend.s
    allowed = [p['identity'] for p in s.state['owned'] if p['role'] in ('game', 'loader')]
    def residuals():
        rows = []
        for process in native.processes():
            if process['name'].lower() not in GAME_NAMES: continue
            ident = native.identity(process['pid'])
            rows.append(dict(process, identity=ident, owned=ident is not None and ident in allowed))
        s.log('owned-game-restart-residuals', processes=rows)
        if any(row['identity'] is not None and
               (not row['owned'] or row['name'].lower() != 'sksevr_loader.exe' or
                Path(row['identity']['path']).name.lower() != 'sksevr_loader.exe') for row in rows):
            raise ValueError('Foreign or unexpected game/loader blocks restart launch')
        return rows
    rows = residuals()
    # A launcher often survives its child for a short interval. An enum entry
    # alone must not be mistaken for a new foreign launch or a restart failure.
    finish = min(time.monotonic()+8, b.end)
    while rows and time.monotonic() < finish:
        b.pause(.2)
        rows = residuals()
    if any(row['identity'] is None for row in rows):
        raise ValueError('Unidentified game/loader persisted after bounded resampling; no relaunch')
    for row in rows:
        result = native.close(row['identity'])
        s.log('owned-game-restart-loader-close', identity=row['identity'], result=result)
    finish = min(time.monotonic()+3, b.end)
    while rows and time.monotonic() < finish:
        b.pause(.2)
        rows = residuals()
    if any(row['identity'] is None for row in rows):
        raise ValueError('Unidentified game/loader during loader shutdown; no termination or relaunch')
    for row in rows:
        s.log('owned-game-restart-loader-forced-stop', identity=row['identity'])
        native.terminate(row['identity'])  # native rechecks creation time on its handle
    finish = min(time.monotonic()+4, b.end)
    while rows and time.monotonic() < finish:
        b.pause(.1)
        rows = residuals()
    if rows: raise ValueError('Exact owned loader did not stop; refusing restart launch')


def start(backend):
    from . import native
    from .runner import request, read_json, GAME_NAMES
    b,s,state=backend,backend.s,backend.s.state
    if state.get('configuration',{}).get('allow_owned_save_load') is not True:
        raise ValueError('Owned restart is not enabled')
    before=copy.deepcopy(state.get('game'))
    owned=[p['identity'] for p in state.get('owned',[]) if p['role']=='game']
    if before not in owned or not native.alive(before):
        raise ValueError('Restart requires the exact live owned game identity')
    if state.get('gameRestartTransition',{}).get('completed') is False:
        raise ValueError('Incomplete restart cannot be replayed')
    if state.get('ownedGameRestartCount',0)>=2:
        raise ValueError('Owned game restart limit2 reached')
    for process in native.processes():
        if process['name'].lower() in GAME_NAMES:
            current=native.identity(process['pid'])
            if current not in [p['identity'] for p in state['owned'] if p['role'] in ('game','loader')]:
                raise ValueError('Foreign game/loader blocks owned restart')
    token=Path(state['configuration']['bridge_token']).read_text().strip()
    port=state['configuration'].get('bridge_port',8930)
    def bridge_ready():
        ping=request(port,'ping',token=token,timeout=min(3,b.remaining()))
        if (ping.get('profile')!=state['testProfileName'] or ping.get('game')!='SkyrimVR' or
                Path(ping.get('modsPath','')).resolve()!=Path(state['configuration']['mods']).resolve()):
            raise ValueError('MO2 instance/profile changed before game restart')
        return ping
    bridge_ready()
    duration=min(179.,b.remaining())
    state['gameRestartTransition']={'completed':False,'stage':'stopping','beforeGame':before,
                                    'startedAt':time.time(),'expiresAt':time.time()+duration}
    state['ownedGameRestartCount']=state.get('ownedGameRestartCount',0)+1
    s.save()
    s.collect(segment='before-restart-'+str(state['ownedGameRestartCount']))
    s.log('owned-game-restart-stop',identity=before,mutationPolicy='one qqq request; exact-owned fallback termination only')
    try:b.call('console',{'action':'exec','command':'qqq'})
    except (OSError,RuntimeError) as error:s.log('owned-game-exit-response',error=str(error))
    finish=min(time.monotonic()+12,b.end)
    while native.alive(before) and time.monotonic()<finish:b.pause(.2)
    if native.alive(before):
        s.log('owned-game-restart-forced-stop',identity=before)
        native.terminate(before)
    finish=min(time.monotonic()+4,b.end)
    while native.alive(before) and time.monotonic()<finish:b.pause(.1)
    if native.alive(before):raise ValueError('Exact owned game did not stop; no relaunch')
    settle_owned_loaders(b)
    bridge_ready()
    state['gameRestartTransition']['stage']='launching'
    state.pop('port',None);state.pop('game',None)
    state['launchIntents']['game']={'at':time.time(),'directory':state['configuration']['game']}
    s.save()
    launch=request(port,'run',{'binary':'SKSE','wait':False,
                              'iUnderstandTheRisk':'yes-I-read-the-docs-and-accept-irreversible-changes'},
                   token=token,timeout=min(30,b.remaining()))
    s.log('owned-game-restart-launch',result=launch)
    if not launch.get('started') or launch.get('applied') is False:
        raise ValueError('MO2 did not start owned restart SKSE')
    if launch.get('pid'):s.own(launch['pid'],'loader')
    candidates=[Path(p) for p in state['configuration'].get('devbench_runtime_files',[])]
    if not candidates:raise ValueError('Restart requires explicit DevBench runtime paths')
    first=None
    while True:
        b.remaining();s.discover()
        games=[p['identity'] for p in state['owned'] if p['role']=='game' and native.alive(p['identity']) and p['identity']!=before]
        for path in candidates:
            try:
                if path.stat().st_mtime<state['launchIntents']['game']['at']-1:continue
                game_port=int(read_json(path)['port'])
                health=request(game_port,'api/health',timeout=min(3,b.remaining()))
            except (OSError,ValueError,RuntimeError):continue
            game=next((p for p in games if p['pid']==health.get('pid')),None)
            if game is None:continue
            marker=(game['pid'],game['birth'],health.get('frame'))
            if first is not None and marker[:2]==first[:2] and marker[2]!=first[2]:
                state.update(game=game,port=game_port)
                state['gameRestartTransition'].update(stage='loading',afterGame=game)
                s.save()
                b.call('inspect',{'kind':'state'})
                s.log('owned-game-restart-task-ready',beforeGame=before,afterGame=game,health=health)
                return
            first=marker
        b.pause(.5)
