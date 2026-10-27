"""Freeze a component qualification from supplied fixture data; never install/run."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from skyrim_autotest.morph_qualification import CASES
from skyrim_autotest import interactive_bindings, morph_session

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def pin(path):
    p=Path(path).resolve(); raw=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def write(path,value):
    with path.open('x',encoding='utf-8')as f:json.dump(value,f,indent=2,ensure_ascii=False);f.write('\n')

def prepare(draft_path,fixture_path,registry_path,config_path,provider_path,output,maximum_seconds=600):
    if type(maximum_seconds) is not int or not 60 <= maximum_seconds <= 1200:
        raise ValueError('Qualification window must be an integer in60..1200seconds')
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
    write(output/'interactive-policy.json',{'nativeBindings':policy,'npcPersistence':True,'morphSession':settings})
    write(output/'execution-plan.json',{'schemaVersion':1,'checks':[{'name':name,'role':'subject'}for name in CASES],
        'bounds':{'maximumSeconds':maximum_seconds,'maximumCommands':256},'fixture':{'cell':'QASmoke'},
        'scope':'tools-only component qualification; no physics or subject-mod acceptance'})
    source=(ROOT/'skyrim_autotest/morph_qualification.py').read_text(encoding='utf-8')
    source+='\nSPEC = '+repr(spec)+'\n\ndef run(exchange,emit):\n    return run_plan(SPEC,exchange,emit)\n'
    with(output/'sequencer.py').open('x',encoding='utf-8')as f:f.write(source)
    manifest={'schemaVersion':1,'kind':'offline-tool-qualification-material','inputs':[pin(p)for p in
        (draft_path,fixture_path,registry_path,config_path,provider_path)],
        'files':[pin(output/name)for name in ('qualification-inputs.json','interactive-policy.json','execution-plan.json','sequencer.py')],
        'source':pin(ROOT/'skyrim_autotest/morph_qualification.py'),'gameStarted':False,'installed':False,'holdsCleared':False,
        'launchAuthority':'Operator must independently verify current owner request and exact finite package before admission'}
    write(output/'preparation-manifest.json',manifest)
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('subject-draft','fixture','actor-registry','provider-config','provider-dll','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--maximum-seconds',type=int,default=600,
        help='Finite companion window; leave time for common startup and teardown inside the operator wall limit')
    a=p.parse_args();result=prepare(a.subject_draft,a.fixture,a.actor_registry,a.provider_config,a.provider_dll,a.output,a.maximum_seconds)
    print(json.dumps({'output':str(a.output),'fileCount':len(result['files']),'installed':False}))
if __name__=='__main__':main()
