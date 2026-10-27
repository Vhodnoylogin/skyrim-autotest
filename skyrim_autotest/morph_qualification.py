"""Finite component qualification through the existing pinned companion callbacks.

Never launches a game or adopts references. The operator supplies immutable
fixture/catalog inputs and owns installation, admission, restoration and report.
This qualifies tool routes; measured subject errors are not mod acceptance.
"""
import copy
import math
import time

CASES = (
    'provider-catalog-and-config', 'six-persistent-automatic-fixtures',
    'named-undressed-stationary-references', 'real-human-preset-assignment',
    'signed-zero-and-foreign-key-observation', 'typed-link-and-race-routes',
    'owned-save-and-six-native-remaps', 'postload-reference-and-name-identity',
    'provider-reset-and-exact-key-cleanup',
)


def run_plan(spec, exchange, emit):
    """Execute once inside an already owned, ready SE session; no action retry."""
    actors = spec['actors']
    if len(actors) != 6 or len({a['tag'] for a in actors}) != 6:
        raise ValueError('Qualification needs six unique pinned fixture definitions')
    case, sequence, finished = None, 0, []
    references={}

    def call(envelope):
        nonlocal sequence
        sequence += 1
        emit({'kind':'measurement','caseId':case,'sequence':sequence,'request':envelope,'delivery':'intent'})
        value = exchange(envelope)
        emit({'kind':'measurement','caseId':case,'sequence':sequence,'request':envelope,'delivery':'completed','rawResult':value})
        return value

    def tool(name, args, timeout=15):
        return call({'schemaVersion':1,'operation':'tool','tool':name,'args':args,'timeoutSeconds':timeout})

    def domain(operation, request, timeout=20):
        return tool('platform',{'operation':operation,'request':request},timeout)

    def check(name, actual, expected=True):
        passed = actual == expected
        emit({'kind':'assertion','caseId':case,'check':name,'actual':actual,'expected':expected,
              'outcome':'passed' if passed else 'mismatch'})
        if not passed: raise AssertionError(name+': observed '+repr(actual))

    def start(index):
        nonlocal case
        case=CASES[index];emit({'kind':'check-start','caseId':case,'role':'subject'})

    def end():
        emit({'kind':'check-result','caseId':case,'outcome':'passed','detail':'Actual component calls and independent data verified'})
        finished.append(case)

    def inspection(a, action=None, phase='initial'):
        req={'domain':'actor-fixture-inspection','actor':{'fixtureTag':a['tag']},'displayName':a['displayName'],
             'nameScope':'reference-only','phase':phase,'requireActualOwnedReferenceWitness':True}
        if action:
            req.update(action=action,preserveInventory=True,editBaseNPC=False,editBaseOutfit=False,
                       collisionPolicy='retain-enabled',noRetryOnUnknownOutcome=True)
        else:
            req.update(wornArmorSlots=[30,61],minimumPositionSamples=2,minimumObservationSpanMs=200,
                       positionToleranceGameUnits=1.0)
        return domain('object.perform' if action else 'world.read',req)

    def human(a):
        return domain('world.read',{'domain':'human-preset-state','actor':{'fixtureTag':a['tag']}})

    def settled(a, status, weight_role):
        until=time.monotonic()+20
        while True:
            receipt=call({'schemaVersion':1,'operation':'binding','bindingId':'morph_status',
                'args':[references[a['tag']]],'timeoutSeconds':6})
            if receipt.get('returned')==status:
                weight=call({'schemaVersion':1,'operation':'binding','bindingId':'morph_'+weight_role,
                    'args':[references[a['tag']]],'timeoutSeconds':6})
                if type(weight.get('returned'))in(int,float) and weight['returned']>=0:return
            if time.monotonic()>=until:raise AssertionError('Native subject diagnostic did not settle for '+a['tag'])
            time.sleep(.1)

    def observe_vector(a, stage, label):
        profile=spec['profiles'][a['sex']]
        return domain('world.read',{'domain':'actor-morph-link-evaluation','actor':{'fixtureTag':a['tag']},
            'stage':stage,'captureSnapshot':label,'familyId':profile['familyId'],'rows':profile['rows'],
            'publicTargets':profile['publicTargets'],'ownKey':spec['ownKey'],
            'sourceValueMeaning':'actual-SKEE-aggregate'},30)

    target=next(a for a in actors if a['sex']=='female')
    tag=target['tag']; baseline=None
    try:
        start(0)
        caps=tool('inspect',{'kind':'world_observer','action':'capabilities'})
        check('read-only-independent-provider',caps.get('readOnly'))
        catalog=domain('world.read',spec['catalogRequest'])
        check('requested-real-presets',catalog['catalog']['missingRequestedPresetCount'],0)
        config=domain('world.read',spec['configurationRequest'])
        check('stock-distribution-enabled',config['human']['config']['disablePresetDistribution'],'none')
        check('current-native-readiness',config['human']['officialApiReady'])
        end()

        start(1)
        for a in actors:
            domain('object.perform',{'domain':'actor-fixture','action':'create','base':a['base'],
                'placement':a['placement'],'persistence':'save-load-witness-required','maximumCreations':6,
                'actor':{'fixtureTag':a['tag']}})
            identity=domain('world.read',{'domain':'actor-fixture-identity','actor':{'fixtureTag':a['tag']}})
            references[a['tag']]={'reference':identity['actor']['reference'],'base':a['base']['formId']}
            check(a['tag']+'-real-persistent-reference',identity['actor']['persistentSaveWitnessAvailable'])
            check(a['tag']+'-exact-base',identity['actor']['baseFormId'],a['base']['formId'])
            raw=domain('world.read',{'domain':'human-preset-state','actor':{'fixtureTag':a['tag']},
                'requireStockGenerationWitness':True,'requireAutomaticOrigin':True,
                'expectedStockEventResponsibleInterface':None,'allowedHumanPresets':spec['presetsBySex'][a['sex']],
                'manualGenerationOrAssignmentCallsBeforeThisObservation':0})
            check(a['tag']+'-genuine-automatic-event',raw['human']['automaticGenerationWitnessCount'],1)
        end()

        start(2)
        for a in actors:
            for action in ('set-reference-display-name','unequip-all-reference-gear','hold-position-keep-collision'):
                inspection(a,action)
            raw=inspection(a)
            check(a['tag']+'-actual-name',raw['actor']['displayName'],a['displayName'])
            check(a['tag']+'-registry-reference',raw['fixture']['registryIdentityMatch'])
            check(a['tag']+'-armor-cleared',raw['fixture']['wornArmorItemCount'],0)
            check(a['tag']+'-weapons-cleared',raw['fixture']['equippedWeaponCount'],0)
            check(a['tag']+'-position-stable',raw['fixture']['positionDriftGameUnits']<=1)
            check(a['tag']+'-no-collision-disable',raw['fixture']['collisionDisableCommandCount'],0)
        end()

        start(3)
        for a in actors:
            raw=domain('object.perform',{'domain':'human-preset','action':'assign','presetName':a['humanPreset'],
                'applyImmediately':True,'assignmentOnly':False,'actor':{'fixtureTag':a['tag']}})
            check(a['tag']+'-assignment-admission',raw['request']['assignmentAccepted'])
            raw=human(a)
            check(a['tag']+'-actual-assignment',raw['human']['assignedPreset'],a['humanPreset'])
            check(a['tag']+'-source-read-coverage',raw['human']['appliedSourceReadUnavailableCount'],0)
        settled(target,5,'humanWeight')
        baseline=observe_vector(target,'human-own-clear','qualification-human-baseline')
        check('complete-independent-vector',baseline['sources']['unavailableReadCount'],0)
        end()

        start(4)
        domain('object.perform',{'domain':'actor-morph-fixture','action':'set-keyed-coefficients-once',
            'values':spec['testValues'],'sourceOfValues':'explicit-supplementary-test-contributions-not-OBody-presets',
            'actor':{'fixtureTag':tag}})
        raw=observe_vector(target,'human-own-clear','qualification-signed-zero')
        for field,value in zip(('foreignHumanValue','zeroHumanKeyValue','foreignWolfValue'),spec['testValues']):
            check('actual-key-'+field,raw['fixture'][field],value['value'])
        check('zero-presence-measured',raw['fixture']['zeroHumanKeyPresenceRecorded'])
        check('provider-aggregate-not-key-sum',raw['sourceAggregationWasReconstructedFromKeys'],False)
        end()

        start(5)
        domain('object.perform',{'domain':'actor-race','action':'change-current-race','race':spec['beastRace'],
            'preserveBaseRecord':True,'actor':{'fixtureTag':tag}})
        settled(target,2,'beastWeight')
        raw=observe_vector(target,'linked-beast','qualification-beast-route')
        check('all-target-read-routes',raw['own']['targetReadCount'],len(spec['profiles']['female']['publicTargets']))
        check('finite-independent-error',math.isfinite(raw['mapping']['maxAbsoluteError']))
        for action in ('clear-own','refresh'):
            reply=domain('object.perform',{'domain':'morph-link','action':action,'actor':{'fixtureTag':tag}})
            check('typed-'+action+'-admission',reply['request']['admitted'])
            settled(target,6,'beastWeight')
        reply=domain('object.perform',{'domain':'morph-link','action':'bind-resource-family',
            'familyId':spec['profiles']['female']['familyId'],'actor':{'fixtureTag':tag}})
        check('typed-family-admission',reply['request']['admitted'])
        settled(target,2,'beastWeight')
        domain('object.perform',{'domain':'actor-race','action':'change-current-race','race':target['humanRace'],
            'preserveBaseRecord':True,'actor':{'fixtureTag':tag}})
        settled(target,5,'humanWeight')
        end()

        start(6)
        label='MorphToolQualification'
        domain('object.perform',{'domain':'save-state','action':'save-disposable-once','saveLabel':label,
            'actors':[a['tag'] for a in actors],'scope':'current-temporary-profile','maximumSaves':1},30)
        saved=domain('world.read',{'domain':'save-state','saveLabel':label})
        check('one-actual-owned-pair',saved['save']['ownedPairCount'],1)
        check('six-native-save-witnesses',saved['save']['actorWitnessCount'],6)
        domain('object.perform',{'domain':'save-state','action':'load-owned-disposable-once',
            'saveLabel':label,'maximumLoads':1,'processRestart':False},90)
        loaded=domain('world.read',{'domain':'save-state','saveLabel':label})
        check('six-actual-native-remaps',loaded['save']['actorRemapWitnessCount'],6)
        check('postload-gameplay-ready',loaded['save']['worldReady'])
        end()

        start(7)
        for a in actors:
            raw=inspection(a,phase='returned-human')
            check(a['tag']+'-name-persisted',raw['actor']['displayName'],a['displayName'])
            check(a['tag']+'-mapped-reference',raw['fixture']['registryIdentityMatch'])
            raw=human(a)
            check(a['tag']+'-assignment-persisted',raw['human']['assignedPreset'],a['humanPreset'])
        end()

        start(8)
        domain('object.perform',{'domain':'human-preset','action':'unassign','actor':{'fixtureTag':tag}})
        domain('object.perform',{'domain':'human-preset','action':'reset-own-provider-morphs','actor':{'fixtureTag':tag}})
        raw=observe_vector(target,'human-own-clear','qualification-provider-reset')
        check('actual-provider-keys-reset',raw['human']['providerOwnMaxAbsoluteCoefficient']<=.0001)
        check('foreign-key-preserved',raw['fixture']['foreignHumanValue'],spec['testValues'][0]['value'])
        domain('object.perform',{'domain':'human-preset','action':'assign','presetName':target['humanPreset'],
            'applyImmediately':True,'assignmentOnly':False,'actor':{'fixtureTag':tag}})
        domain('object.perform',{'domain':'actor-morph-fixture','action':'remove-exact-keys-once',
            'keys':[v['key']for v in spec['testValues']],'actor':{'fixtureTag':tag}})
        raw=observe_vector(target,'human-own-clear','qualification-exact-key-cleanup')
        check('only-owned-test-keys-removed',raw['fixture']['remainingOwnedTestKeyCount'],0)
        end()
    except BaseException as error:
        if case not in finished:
            outcome='mismatch' if isinstance(error,AssertionError) else 'unavailable'
            emit({'kind':'check-result','caseId':case,'outcome':outcome,'detail':str(error)});finished.append(case)
        for pending in CASES:
            if pending not in finished:emit({'kind':'check-result','caseId':pending,'outcome':'not_run','detail':'Qualification stopped before this case'})
        raise
    case=None
    call({'schemaVersion':1,'operation':'finish'})
    return {'qualification':'tools-only','outcome':'passed','cases':list(CASES),
        'physicsQualified':False,'subjectModAccepted':False,'automaticSubjectOrdersStarted':False}
