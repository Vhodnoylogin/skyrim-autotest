"""Collect one owned DevBench input recording without leaving its source artifact."""
import hashlib
import json
import re
from pathlib import Path
from . import runner

def start(session):
    status=session.tool('record', {'action':'status'})
    if status.get('recording') is not False or status.get('state') != 'idle':
        raise AssertionError('Input activity recorder is not idle; foreign recording untouched')
    result=session.tool('record', {'action':'start', 'intervalMs':50,
                                  'correlationId':session.state['id']})
    if result.get('recording') is not True or result.get('correlationId') != session.state['id']:
        raise AssertionError('Owned input activity start unavailable')
    session.log('pickup-input-activity-start', result=result)

def collect(session, result):
    relative=result.get('path','').replace('\\','/')
    if (not re.fullmatch(r'Data/SKSE/Plugins/devbench/recordings/recording_[0-9]+\.json',relative)
            or result.get('meta',{}).get('correlationId') != session.state['id']):
        raise AssertionError('Input activity output identity unavailable; no artifact removed')
    data_relative=Path(relative).relative_to('Data')
    provider_dirs = {Path(name.replace('\\','/')).parts[0]
                     for name in session.state.get('preflight', {}).get('dlls', {})
                     if Path(name.replace('\\','/')).name.casefold() == 'devbench.dll'}
    if len(provider_dirs) != 1:
        raise AssertionError('Pinned DevBench provider directory unavailable')
    roots=[runner.P.game, runner.P.overwrite, runner.P.mods/next(iter(provider_dirs))]
    paths=[roots[0]/relative]+[root/data_relative for root in roots[1:]]
    found=[]
    for path in paths:
        if path.is_file() and path.stat().st_size <= 8*1024*1024:
            blob=path.read_bytes()
            try: value=json.loads(blob)
            except (ValueError,UnicodeDecodeError): continue
            if value.get('meta',{}).get('correlationId') == session.state['id']:
                found.append((path,blob,value))
    if len(found) != 1:
        raise AssertionError('Unique owned input recording unavailable; source artifacts preserved')
    path,blob,value=found[0]
    if value.get('meta',{}).get('format') != 'devbench-recording-3':
        raise AssertionError('Input recording format unavailable; source artifact preserved')
    destination=session.dir/'evidence/pickup-input-recording.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(blob)
    digest=hashlib.sha256(blob).hexdigest()
    if destination.read_bytes() != blob or path.read_bytes() != blob:
        raise AssertionError('Input recording changed during evidence transfer; source preserved')
    # Remove only this newly generated, correlation-qualified file after copying.
    path.unlink()
    events=[e for e in value.get('activityEvents',[]) if e.get('kind')=='input']
    session.log('pickup-input-activity-collected', path=str(destination), sha256=digest,
                source=str(path), sourceRemoved=True, meta=value['meta'], inputEvents=events,
                domain='engine input event bus; not proof of downstream handler consumption')
    return value

def finish(session):
    result=session.tool('record',{'action':'stop'})
    session.log('pickup-input-activity-stop',result=result)
    return collect(session,result)
