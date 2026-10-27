"""Freeze a component qualification from supplied fixture data; never install/run."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from skyrim_autotest.morph_qualification import CASES
from skyrim_autotest import interactive_bindings, morph_session, semantic_companion
from tools.prepare_semantic_companion import compile_scenario

HELD_BRIDGE_CASE='held-semantic-world-read'

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def pin(path):
    p=Path(path).resolve(); raw=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def write(path,value):
    with path.open('x',encoding='utf-8')as f:json.dump(value,f,indent=2,ensure_ascii=False);f.write('\n')

def staged_source(spec,bridge_spec,qualification_source,semantic_source):
    """Render authored stages; one caller owns global sequence and final finish."""
    semantic_companion.validate_spec(bridge_spec)
    return ('_QUALIFICATION_SOURCE='+repr(qualification_source)+'\n_HELD_SOURCE='+repr(semantic_source)+
        '\n_SPEC='+repr(spec)+'\n_HELD_SPEC='+repr(bridge_spec)+'\n'+'''
def run(exchange,emit):
    qualification={'__name__':'qualification_stage','__file__':__file__}
    held={'__name__':'held_semantic_stage','__file__':__file__}
    exec(_QUALIFICATION_SOURCE,qualification)
    exec(_HELD_SOURCE,held)
    sequence=0
    def stage_emit(record):
        nonlocal sequence
        record=dict(record)
        if record['kind']=='measurement':
            if record['delivery']=='intent':sequence+=1
            record['sequence']=sequence
        emit(record)
    try:
        first=qualification['run_plan'](_SPEC,exchange,stage_emit,finish_owner=False)
    except BaseException:
        emit({'kind':'check-result','caseId':_HELD_SPEC['scenario']['steps'][0]['name'],
              'outcome':'not_run','detail':'Native component stage stopped; no bridge action attempted'})
        raise
    if first.get('outcome')!='passed':raise RuntimeError('Native component stage did not pass')
    second=held['run_plan'](_HELD_SPEC,exchange,stage_emit,finish_owner=False)
    if second.get('outcome')!='passed':raise AssertionError('Generic held semantic world readiness did not pass')
    request={'schemaVersion':1,'operation':'finish'}
    stage_emit({'kind':'measurement','caseId':None,'request':request,'delivery':'intent'})
    raw=exchange(request)
    stage_emit({'kind':'measurement','caseId':None,'request':request,'delivery':'completed','rawResult':raw})
    return {'qualification':'tools-only','outcome':'passed','nativeComponents':first,'heldSemantic':second,
        'physicsQualified':False,'subjectModAccepted':False,'automaticSubjectOrdersStarted':False}
''')

def bridge_material(output,maximum_seconds):
    """Pin a real generic compilation; this generated probe is tooling data."""
    order={'schemaVersion':2,'kind':'tool-qualification-held-probe','id':HELD_BRIDGE_CASE,
        'subjectPlan':{'interface':'polygon-actions/1','fixture':{'cell':'QASmoke','startMode':'new-game'},'steps':[
            {'name':HELD_BRIDGE_CASE,'operation':'state.read','timeout':20,'assert':[{'field':'world.ready','equals':True}]}]},
        'testing':{'start':{'kind':'check','name':HELD_BRIDGE_CASE},'checks':[{'name':HELD_BRIDGE_CASE,'role':'subject'}]}}
    mapping={'schemaVersion':1,'interface':'polygon-actions/1','operations':{'state.read':{
        'tool':'platform','args':{'operation':'state.read'},'fields':{'world.ready':'world.ready'}}}}
    compiled=compile_scenario(order,mapping)
    for name,value in [('held-bridge-order.json',order),('held-bridge-mapping.json',mapping),('held-bridge-compiled.json',compiled)]:write(output/name,value)
    spec={'schemaVersion':1,'interface':semantic_companion.INTERFACE,
        'subjectOrderSha256':semantic_companion.canonical_hash(order),'originalTesting':order['testing'],'scenario':compiled,
        'bounds':{'maximumSeconds':maximum_seconds,'maximumCommands':256},'provenance':{
            'order':pin(output/'held-bridge-order.json'),'mappingManifest':pin(output/'held-bridge-mapping.json'),
            'compiledScenario':pin(output/'held-bridge-compiled.json'),'sourcePlanSha256':semantic_companion.canonical_hash(order['subjectPlan'])}}
    spec=semantic_companion.validate_spec(spec)
    write(output/'held-bridge-spec.json',spec)
    return spec

def prepare(draft_path,fixture_path,registry_path,config_path,provider_path,output,maximum_seconds=600,*,include_held_bridge_check=False):
    if type(maximum_seconds) is not int or not 60 <= maximum_seconds <= 1200:
        raise ValueError('Qualification window must be an integer in60..1200seconds')
    if type(include_held_bridge_check) is not bool:raise ValueError('include_held_bridge_check requires an explicit boolean')
    output=Path(output).resolve()
    if any((p/'.git').exists() for p in [output,*output.parents]):raise ValueError('External new output directory required')
    output.mkdir(parents=True,exist_ok=False)
    draft,fixture,registry=read(draft_path),read(fixture_path),read(registry_path)
    plan=draft['subjectPlan']; requests=[s.get('parameters',{}).get('request',{}) for s in plan['steps']]
    profiles={}
    for r in requests:
        if r.get('domain')=='actor-morph-link-evaluation' and 'rows'in r:
            sex=next(a['sex']for a in fixture['actors']if a['tag']==r['actor']['fixtureTag'])
            profiles[sex]={'familyId':r['familyId'],'rows':r['rows'],'publicTargets':r['publicTargets']}
    if set(profiles)!={'male','female'}:raise ValueError('Both real resource family catalogs required')
    names={a['fixtureTag']:a['displayName']for a in registry['actors']}
    actors=[{'tag':a['tag'],'sex':a['sex'],'base':{'plugin':a['plugin'],'formId':a['baseFormId']},
             'placement':a['placement'],'humanPreset':a['humanPreset'],'humanRace':a['raceFormId'],
             'displayName':names[a['tag']]}for a in fixture['actors']]
    catalog=next(r for r in requests if r.get('domain')=='human-preset-catalog')
    config_request=next(r for r in requests if r.get('domain')=='human-provider-config')
    test_values=next(r['values']for r in requests if r.get('domain')=='actor-morph-fixture' and r.get('action')=='set-keyed-coefficients-once')
    spec={'schemaVersion':1,'actors':actors,'profiles':profiles,'ownKey':next(r['ownKey']for r in requests if 'ownKey'in r),
        'catalogRequest':catalog,'configurationRequest':config_request,'testValues':test_values,
        'presetsBySex':{sex:[a['humanPreset']for a in actors if a['sex']==sex]for sex in profiles},
        'beastRace':next(r['race']for r in requests if r.get('domain')=='actor-race' and r['race']!=actors[0]['humanRace'])}
    policy={'schemaVersion':1,'fixtureActorBases':[a['base']['formId']for a in actors],
            'allowedRaceForms':[actors[0]['humanRace'],spec['beastRace']],'bindings':[]}
    funcs={'status':('GetStatus','int'),'error':('GetLastError','string'),'assigned':('GetAssigned','string'),
        'humanWeight':('GetHumanWeight','float'),'beastWeight':('GetBeastWeight','float'),
        'clear':('ClearOwn','bool'),'refresh':('Refresh','bool'),'configure':('ConfigureMorphFamily','bool')}
    # Explicit provider bindings are a platform recipe, never subject-order fields.
    for role,(function,returns)in funcs.items():
        policy['bindings'].append({'id':'morph_'+role,'script':'CLAWDistributionNative','function':function,'scope':'global',
            'params':['actor']+(['string']if role=='configure'else[]),'returnType':returns,
            'effect':'mutate'if role in ('clear','refresh','configure')else'read','actorSelf':False,
            'actorArgs':[0],'raceArgs':[],'completion':'native-return'})
    for identifier,function,params in [('morph_race','SetRace',['race']),('fixture_unequip','UnequipAll',[]),('fixture_hold','SetDontMove',['bool'])]:
        policy['bindings'].append({'id':identifier,'script':'Actor','function':function,'scope':'member','params':params,
            'returnType':'none','effect':'mutate','actorSelf':True,'actorArgs':[],'raceArgs':[0]if function=='SetRace'else[],
            'completion':'actor-race'if function=='SetRace'else'native-return'})
    policy=interactive_bindings.validate(policy)
    settings={'bindings':{**{k:'morph_'+k for k in funcs},'race':'morph_race'},
        'testKeys':[v['key']for v in test_values],'providerOwnKeys':['OBody','OClothe'],
        'providerKeyEvidence':{'sourceCommit':'13513609145313f721970c2ebe113290f6add6e8','providerSha256':pin(provider_path)['sha256']},
        'providerConfigSha256':pin(config_path)['sha256'],
        'sourceMorphsBySex':{sex:list(dict.fromkeys(row['sourceMorph']for row in p['rows']))for sex,p in profiles.items()}}
    settings=morph_session.validate_config(settings,policy)
    write(output/'qualification-inputs.json',spec)
    write(output/'interactive-policy.json',{'nativeBindings':policy,'npcPersistence':True,'morphSession':settings,'manageCommandEndpoint':True})
    checks=CASES+(HELD_BRIDGE_CASE,) if include_held_bridge_check else CASES
    write(output/'execution-plan.json',{'schemaVersion':1,'checks':[{'name':name,'role':'subject'}for name in checks],
        'bounds':{'maximumSeconds':maximum_seconds,'maximumCommands':256},'fixture':{'cell':'QASmoke'},
        'scope':'tools-only component qualification; no physics or subject-mod acceptance'})
    snapshots=output/'source-snapshots';snapshots.mkdir()
    source_pins=[]
    for name in ('morph_qualification.py','semantic_companion.py'):
        target=snapshots/name;target.write_bytes((ROOT/'skyrim_autotest'/name).read_bytes());source_pins.append(pin(target))
    source=(snapshots/'morph_qualification.py').read_text(encoding='utf-8')
    extra_files=[]
    if include_held_bridge_check:
        bridge_spec=bridge_material(output,maximum_seconds)
        source=staged_source(spec,bridge_spec,source,(snapshots/'semantic_companion.py').read_text(encoding='utf-8'))
        extra_files=['held-bridge-order.json','held-bridge-mapping.json','held-bridge-compiled.json','held-bridge-spec.json']
    else:source+='\nSPEC = '+repr(spec)+'\n\ndef run(exchange,emit):\n    return run_plan(SPEC,exchange,emit)\n'
    with(output/'sequencer.py').open('x',encoding='utf-8')as f:f.write(source)
    manifest={'schemaVersion':1,'kind':'offline-tool-qualification-material','inputs':[pin(p)for p in
        (draft_path,fixture_path,registry_path,config_path,provider_path)],
        'files':[pin(output/name)for name in ['qualification-inputs.json','interactive-policy.json','execution-plan.json','sequencer.py',*extra_files]]+source_pins,
        'source':source_pins[0],'sourceSnapshots':source_pins,
        'sourceOrigins':[{'module':name,'path':str(ROOT/'skyrim_autotest'/name),
            'repository':'https://github.com/Vhodnoylogin/skyrim-autotest','basis':'authored source snapshot SHA256 is authoritative'}for name in ('morph_qualification.py','semantic_companion.py')],
        'includeHeldBridgeCheck':include_held_bridge_check,'gameStarted':False,'installed':False,'holdsCleared':False,
        'launchAuthority':'Operator must independently verify current owner request and exact finite package before admission'}
    write(output/'preparation-manifest.json',manifest)
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('subject-draft','fixture','actor-registry','provider-config','provider-dll','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--maximum-seconds',type=int,default=600,
        help='Finite companion window; leave time for common startup and teardown inside the operator wall limit')
    p.add_argument('--include-held-bridge-check',action='store_true',help='Add one actual generic semantic state.read probe before the sole owner finish')
    a=p.parse_args();result=prepare(a.subject_draft,a.fixture,a.actor_registry,a.provider_config,a.provider_dll,a.output,a.maximum_seconds,include_held_bridge_check=a.include_held_bridge_check)
    print(json.dumps({'output':str(a.output),'fileCount':len(result['files']),'installed':False}))
if __name__=='__main__':main()
