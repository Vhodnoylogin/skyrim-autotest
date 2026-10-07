"""Configured read-only subject snapshots and owned offline fixture settings."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from .config import P

ACTION='restart_with_fixture_subject_settings'
RESTORATION='Restore original installed settings, source profile selection and all original saves; no live source-profile edits'


def validate(operation,req):
    if req.get('observation')=='subject.settings':
        if operation!='world.read' or set(req)!={'observation','subject'}:raise ValueError('Subject settings requires exact read selector')
    elif req.get('action')==ACTION:
        fields={'action','subject','saveTag','scope','settings','inputHandedness','bodySlotFixtures','restoration'}
        if operation!='object.perform' or set(req)!=fields or req['scope']!='owned-disposable-profile' or req['restoration']!=RESTORATION:
            raise ValueError('Subject fixture restart requires complete owned restore contract')
        if not isinstance(req['saveTag'],str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',req['saveTag']):raise ValueError('Invalid owned save tag')
        settings(req['settings'])
        if req['inputHandedness'] not in ('left','right'):raise ValueError('Explicit actual input handedness required')
        slots=req['bodySlotFixtures']
        if not isinstance(slots,list) or len(slots)>14:raise ValueError('Bounded explicit body-slot fixtures required')
        seen=set()
        for slot in slots:
            if (not isinstance(slot,dict) or set(slot)!={'slot','allowSmall','visible'} or type(slot['slot']) is not int or
                    not 1<=slot['slot']<=14 or slot['slot'] in seen or type(slot['allowSmall']) is not bool or type(slot['visible']) is not bool):
                raise ValueError('Invalid or duplicate body-slot fixture')
            seen.add(slot['slot'])
    else:return False
    if not isinstance(req['subject'],str) or not 1<=len(req['subject'])<=96 or any(ord(c)<32 for c in req['subject']):
        raise ValueError('Stable subject name required')
    return True


def settings(value,complete=False):
    if (not isinstance(value,dict) or not {'language','logLevel','mayEnableSlots'}<=set(value) or
            set(value)-({'language','logLevel','mayEnableSlots','pouches','inputHandedness'} if complete else {'language','logLevel','mayEnableSlots','pouches'}) or
            not isinstance(value['language'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',value['language']) or
            not isinstance(value['logLevel'],str) or not re.fullmatch(r'[a-z]{1,16}',value['logLevel']) or
            type(value['mayEnableSlots']) is not bool):raise ValueError('Effective subject settings contract unavailable')
    if complete and (set(value)!={'language','logLevel','mayEnableSlots','pouches','inputHandedness'} or value['inputHandedness'] not in ('left','right')):
        raise ValueError('Complete native settings and handedness unavailable')
    if 'pouches' in value:
        if not isinstance(value['pouches'],list) or len(value['pouches'])>14:raise ValueError('Bounded pouch list required')
        slots=set()
        for pouch in value['pouches']:
            if (not isinstance(pouch,dict) or set(pouch)!={'slot','mode'} or type(pouch['slot']) is not int or
                    not 1<=pouch['slot']<=14 or pouch['slot'] in slots or pouch['mode'] not in ('exclusive','shared')):
                raise ValueError('Invalid or duplicate configured pouch')
            slots.add(pouch['slot'])


def binding(subject):
    value=P.value.get('subject_state_bindings',{}).get(subject)
    if not isinstance(value,dict) or not value.get('inspectKind'):raise ValueError('No qualified native subject state binding')
    return value


def observe(b,subject):
    provider=binding(subject);b.guard_world()
    if b.remaining()<.12:raise TimeoutError('Insufficient native subject snapshot time')
    raw=b.call('inspect',{'kind':provider['inspectKind'],'action':'snapshot',
                         'timeoutMs':max(100,min(3000,int((b.remaining()-.02)*1000)))})
    game=b.s.state['game'];process=raw.get('process',{});sample=raw.get('sample',{});state=raw.get('subject',{})
    if (type(raw.get('schemaVersion')) is not int or raw['schemaVersion']!=1 or raw.get('provider')!=provider['inspectKind'] or
            raw.get('ok') is not True or raw.get('available') is not True or raw.get('readOnly') is not True or
            process.get('identityAvailable') is not True or type(process.get('pid')) is not int or process['pid']!=game['pid'] or
            type(process.get('createdFileTime100ns')) is not int or process['createdFileTime100ns']!=game['birth'] or
            sample.get('phase')!='skse_main_thread_task' or type(sample.get('sequence')) is not int or sample['sequence']<=0 or
            type(sample.get('lifecycleEpoch')) is not int or sample['lifecycleEpoch']<0 or
            state.get('available') is not True or type(state.get('loadGeneration')) is not int or state['loadGeneration']<0 or
            type(state.get('callbackFrame')) is not int or state['callbackFrame']<=0):
        raise ValueError('Native subject snapshot identity/readiness unavailable')
    settings(state.get('settings'),complete=True)
    runtime=state.get('runtime',{})
    if (type(runtime.get('assignmentCount')) is not int or not 0<=runtime['assignmentCount']<=14 or
            runtime.get('assignmentCountUnits')!='assigned_pouches'):
        raise ValueError('Native assignment count/units unavailable')
    cursor=b.s.state.setdefault('subjectStateReadCursors',{}).get(subject)
    if cursor and cursor['game']==game:
        if sample['sequence']<=cursor['sequence'] or sample['lifecycleEpoch']<cursor['epoch']:
            raise ValueError('Replayed or older native subject snapshot')
    b.s.state['subjectStateReadCursors'][subject]={'game':copy.deepcopy(game),'sequence':sample['sequence'],'epoch':sample['lifecycleEpoch']}
    b.s.save()
    b.guard_world();b.s.log('platform-subject-native-state',subject=subject,raw=raw,
                          basis='effective native state; not requested settings or file inference')
    return {'subject':{'settings':copy.deepcopy(state['settings']),'runtime':copy.deepcopy(runtime)},'providerObservation':raw}


def slot_suspended(b,slot):
    values=[]
    for subject in P.value.get('subject_state_bindings',{}):
        raw=observe(b,subject)['providerObservation']
        for row in raw['subject'].get('bodySlots',[]):
            if row.get('slot')==slot:
                if row.get('suspendedAvailable') is not True or type(row.get('suspended')) is not bool:
                    raise ValueError('Actual native VRIK suspension unavailable')
                values.append(row['suspended'])
    if not values or len(set(values))!=1:raise ValueError('Native slot suspension missing/conflicting across bound providers')
    return values[0]


def destination(relative):
    target=(P.overwrite/relative).resolve()
    if not target.is_relative_to(P.overwrite.resolve()):raise ValueError('Subject fixture target escapes overwrite')
    for part in (target,*target.parents):
        if part==P.overwrite.parent:break
        if part.exists() and (part.is_symlink() or getattr(part.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('Subject fixture target contains a link/reparse point')
    return target


def snapshot(b,target):
    path=str(target.resolve()).casefold()
    rows=[row for row in b.s.state['snapshots'] if str(Path(row['path']).resolve()).casefold()==path]
    if len(rows)!=1:raise ValueError('Fixture setting was not durably snapshotted before the run')
    return rows[0]


def bytes_for(b,target):
    row=snapshot(b,target);previous=b.s.state.get('fixtureSettingsWrites',{}).get(str(target))
    expected=previous['sha256'] if previous else row.get('sha256') if row['exists'] else None
    if target.exists():
        if not target.is_file() or target.stat().st_size>4*1024*1024:raise ValueError('Fixture setting file outside bound')
        data=target.read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Fixture setting differs from last verified bytes')
        return data
    if expected is not None:raise ValueError('Fixture setting disappeared')
    return None


def atomic_write(b,target,data,profile=False,program_subject=None,slot_subject=None):
    from .runner import sha
    written_json=None
    if program_subject is not None:
        written_json=json.loads(data);settings(written_json)
    b.remaining();temp=target.with_name(target.name+'.autotest-fixture.tmp')
    if not profile:
        if snapshot(b,temp)['exists'] or temp.exists():raise ValueError('Fixture temporary file is not exclusively available')
        bytes_for(b,target)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp.write_bytes(data);os.replace(temp,target)
    if sha(target)!=hashlib.sha256(data).hexdigest():raise ValueError('Fixture setting write verification failed')
    record={'path':str(target),'sha256':sha(target),'bytes':len(data),'profileLocal':profile,
            'writtenSha256':sha(target),'writtenBytesHex':data.hex(),
            'writeOrdinal':len(b.s.state.get('fixtureSettingsWriteHistory',[]))+1}
    if slot_subject is not None:record['slotSubject']=slot_subject
    if program_subject is not None:
        record.update(programSubject=program_subject,writtenSha256=record['sha256'],
                      writtenBytesHex=data.hex(),writtenJson=written_json)
    b.s.state.setdefault('fixtureSettingsWrites',{})[str(target)]=record
    b.s.state.setdefault('fixtureSettingsWriteHistory',[]).append(copy.deepcopy(record))
    b.s.save()


def reconcile_native_settings_output(b,target,subject,observed):
    """Accept byte changes only when explicit settings and native state corroborate them.

    This establishes content continuity, not which process wrote the file.
    Original snapshot/backup and exact executor write bytes remain unchanged.
    """
    record=b.s.state.get('fixtureSettingsWrites',{}).get(str(target))
    if not record or record.get('programSubject')!=subject:
        raise ValueError('No matching owned settings write to reconcile')
    transition=b.s.state.get('ownedLoadTransition',{})
    if transition.get('completed') is not True or transition.get('afterGame')!=b.s.state.get('game'):
        raise ValueError('Settings output requires the completed exact owned load')
    snapshot(b,target)
    stat=target.lstat()
    if (not target.is_file() or target.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400
            or stat.st_size>4*1024*1024):
        raise ValueError('Native settings output is not a bounded regular file')
    data=target.read_bytes();digest=hashlib.sha256(data).hexdigest()
    if digest==record['sha256']:return
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('Duplicate settings output key')
            result[key]=value
        return result
    def constant(value):raise ValueError('Nonfinite settings JSON')
    actual=json.loads(data.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)
    settings(actual)
    native=copy.deepcopy(observed['subject']['settings']);native.pop('inputHandedness')
    written=record['writtenJson']
    if actual!=native or any(key not in actual or actual[key]!=value for key,value in written.items()):
        raise ValueError('Settings output does not preserve explicit values and actual native settings')
    raw=observed['providerObservation']
    if raw['process']['pid']!=b.s.state['game']['pid'] or raw['process']['createdFileTime100ns']!=b.s.state['game']['birth']:
        raise ValueError('Settings output native process identity changed')
    cursor=b.s.state.get('subjectStateReadCursors',{}).get(subject,{})
    if (cursor.get('game')!=b.s.state['game'] or cursor.get('sequence')!=raw['sample']['sequence']
            or cursor.get('epoch')!=raw['sample']['lifecycleEpoch']):
        raise ValueError('Settings output lacks the current corroborating native sample')
    if target.read_bytes()!=data:raise ValueError('Settings output changed during reconciliation')
    evidence={'path':str(target),'sha256':digest,'bytes':len(data),'previousVerifiedSha256':record['sha256'],
              'writtenSha256':record['writtenSha256'],'actualBytesHex':data.hex(),'actualJson':actual,
              'nativeObservation':copy.deepcopy(raw),'game':copy.deepcopy(b.s.state['game']),
              'addedKeys':sorted(set(actual)-set(written)),
              'basis':'explicit values preserved; complete output corroborated by actual native state after exact owned load; writer identity not inferred'}
    record.update(sha256=digest,bytes=len(data),nativeOutput=evidence)
    b.s.state.setdefault('fixtureSettingsOutputHistory',[]).append(copy.deepcopy(evidence))
    b.s.save();b.s.log('platform-fixture-settings-output-reconciled',evidence=evidence)


def slot_ini(data,slots):
    if not slots:return data
    text=data.decode('utf-8-sig')
    for slot in slots:
        for name,flag in (('allowSmallSlot',slot['allowSmall']),('visibleSlot',slot['visible'])):
            key=name+str(slot['slot']);pattern=re.compile(r'^([ \t]*'+re.escape(key)+r'[ \t]*=)[^\r\n]*(?=\r?$)',re.I|re.M)
            if len(pattern.findall(text))!=1:raise ValueError('Unique actual VRIK slot setting missing: '+key)
            text=pattern.sub(lambda m:m[1]+' '+str(int(flag)),text)
    return text.encode('utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8')


def perform(b,req):
    provider=binding(req['subject']);required={'settingsDestination','handednessProfileIni','bodySlotsDestination','bodySlotsSource'}
    if not required<=set(provider):raise ValueError('Native subject binding has no owned fixture write contract')
    # Read current native capability before stopping; no file-only state fallback.
    observe(b,req['subject'])
    configuration=destination(provider['settingsDestination']);slots_target=destination(provider['bodySlotsDestination'])
    from . import slot_outputs
    slot_sample=slot_outputs.capture(b,slots_target,req['subject'])
    slot_outputs.reconcile(b,slots_target,req['subject'],slot_sample)
    bytes_for(b,configuration);bytes_for(b,slots_target)
    profile=Path(b.s.state['testProfile']).resolve()
    if (profile.parent!=P.profiles.resolve() or profile.name!=b.s.state['testProfileName'] or
            profile.name==b.s.state['preflight']['profile']):raise ValueError('Fixture INI requires the exact owned disposable profile')
    ini=profile/provider['handednessProfileIni']
    if not ini.is_file() or ini.is_symlink():raise ValueError('Owned profile INI unavailable')
    # Always derive slot overrides from the pinned baseline, so a later empty
    # fixture list does not inherit a previous variant's temporary slot changes.
    source=Path(provider['bodySlotsSource']['path'])
    if not source.is_file() or source.is_symlink() or source.stat().st_size>4*1024*1024:raise ValueError('Bounded immutable slot baseline unavailable')
    with source.open('rb') as stream:source_bytes=stream.read(4*1024*1024+1)
    if len(source_bytes)>4*1024*1024 or hashlib.sha256(source_bytes).hexdigest()!=provider['bodySlotsSource']['sha256']:
        raise ValueError('Pinned VRIK slot baseline changed')
    slot_bytes=slot_ini(source_bytes,req['bodySlotFixtures'])
    writes={'configuration':str(configuration),'slots':str(slots_target),'profileIni':str(ini),'subject':req['subject'],
            'requestedSettings':copy.deepcopy(req['settings']),'requestedHandedness':req['inputHandedness'],'completed':False}
    def between_launch():
        from . import native
        from .runner import GAME_NAMES,set_ini
        if any(p['name'].lower() in GAME_NAMES for p in native.processes()):raise ValueError('Fixture changes require fully stopped game/loaders')
        # VRIK may save its last loaded pose on exit. Corroborate only that
        # numeric pose output against the pre-exit identity-bound readback.
        slot_outputs.reconcile(b,slots_target,req['subject'],slot_sample)
        b.remaining();b.s.state.setdefault('fixtureSettingsHistory',[]).append(writes);b.s.save()
        b.s.log('platform-fixture-settings-intent',write=writes,sourceProfileEdited=False)
        atomic_write(b,configuration,(json.dumps(req['settings'],indent=2)+'\n').encode('utf-8'),program_subject=req['subject'])
        atomic_write(b,slots_target,slot_bytes,slot_subject=req['subject'])
        text=ini.read_text(encoding='utf-8-sig')
        atomic_write(b,ini,set_ini(text,'VRInput','bLeftHandedMode',str(int(req['inputHandedness']=='left'))).encode('utf-8'),profile=True)
        writes['completed']=True;b.s.save();b.s.log('platform-fixture-settings-written',write=writes)
    from .owned_saves import perform as owned_perform
    result=owned_perform(b,req,restart_prepare=between_launch)
    observed=observe(b,req['subject'])
    reconcile_native_settings_output(b,configuration,req['subject'],observed)
    writes['nativeAfterRestart']=copy.deepcopy(observed);b.s.save()
    return {**result,**observed}
