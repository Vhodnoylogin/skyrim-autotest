"""Prepare an owned inspection scene, then execute explicit operator commands.

This sequencer shares the existing companion transport. It launches nothing,
opens no audio and interprets no speech. Scene readiness is separate from a
rendered-morph or whole-mod verdict.
"""
import math
import time
import copy
import re


CASE = 'owner-controlled-manual-scene'


def run_world_plan(exchange, emit, next_command, notify, input_owner):
    """Keep the initial world open and measure explicitly requested physical input."""
    sequence = 0
    emit({'kind': 'check-start', 'caseId': CASE, 'role': 'subject'})
    def call(tool, args):
        nonlocal sequence
        sequence += 1
        request = {'schemaVersion': 1, 'operation': 'tool', 'tool': tool, 'args': args, 'timeoutSeconds': 15}
        row = {'kind': 'measurement', 'caseId': CASE, 'sequence': sequence, 'request': request}
        emit(dict(row, delivery='intent')); raw = exchange(request)
        emit(dict(row, delivery='completed', rawResult=raw)); return raw
    def scene():
        raw = call('inspect', {'kind': 'scene'})
        pos = raw.get('position')
        if (raw.get('playerLoaded') is not True or type(pos) is not list or len(pos) != 3 or
                any(type(n) not in (int, float) or not math.isfinite(n) for n in pos)):
            raise ValueError('Actual loaded world and player position unavailable')
        return raw
    initial = scene()
    emit({'kind': 'assertion', 'caseId': CASE, 'check': 'initial-world-loaded-position-observed',
          'actual': initial['playerLoaded'], 'expected': True, 'outcome': 'passed'})
    notify('scene-ready', {'stage': 'initial-world-control', 'scene': initial, 'actors': {},
                          'sixActorSceneReady': False, 'awaitingOwnerCommands': True})
    commands = 0
    while True:
        command = next_command(); commands += 1
        if (type(command) is not dict or command.get('sequence') != commands or
                not isinstance(command.get('sourceRef'), str) or not command['sourceRef'].strip()):
            raise ValueError('Fresh sequential current owner command required')
        action = command.get('action')
        if action == 'finish' and set(command) == {'sequence', 'sourceRef', 'action'}:
            emit({'kind': 'check-result', 'caseId': CASE, 'outcome': 'passed',
                  'detail': 'Owner-ended world observations; no NPC or whole-mod verdict'})
            sequence += 1
            request = {'schemaVersion': 1, 'operation': 'finish'}
            row = {'kind': 'measurement', 'caseId': None, 'sequence': sequence, 'request': request}
            emit(dict(row, delivery='intent')); raw = exchange(request)
            emit(dict(row, delivery='completed', rawResult=raw))
            return {'initialWorldInspected': True, 'wholeModAccepted': False}
        before = scene()
        if action == 'move':
            if (set(command) != {'sequence', 'sourceRef', 'action', 'key', 'milliseconds'} or
                    command['key'] not in ('W', 'A', 'S', 'D', 'SPACE') or
                    type(command['milliseconds']) is not int or not 100 <= command['milliseconds'] <= 1000):
                raise ValueError('Only short leased gameplay keys are accepted')
            call('input', {'action': 'capabilities'})
            args = {'device': 'keyboard', 'key': command['key'], 'owner': input_owner}
            call('input', dict(args, action='down', maxHoldMs=command['milliseconds']))
            time.sleep(command['milliseconds'] / 1000)
            call('input', dict(args, action='up'))
        elif action != 'inspect' or set(command) != {'sequence', 'sourceRef', 'action'}:
            raise ValueError('Only move/inspect/finish supported in initial-world control')
        after = scene()
        notify('command-result', {'command': command, 'before': before, 'after': after,
               'positionDeltaGameUnits': math.dist(before['position'], after['position']),
               'sixActorSceneReady': False, 'inputReceiptIsNotMovementProof': True})


def validate_spec(spec):
    """Validate the complete declaration before creating any reference."""
    from skyrim_autotest import morph_session, actor_inspection
    if type(spec) is not dict:
        raise ValueError('A complete manual scene declaration is required')
    allowed = {'actors', 'wildActors', 'beastRace', 'catalogRequest', 'configurationRequest',
               'wildConfigurationRequest', 'presetMode', 'automaticObservationSeconds',
               'morphObservationRequest', 'morphObservationRequestsBySex', 'wildOriginPolicy'}
    if set(spec) - allowed or not {'actors', 'beastRace', 'catalogRequest', 'configurationRequest'} <= set(spec):
        raise ValueError('Unknown or missing manual scene declaration fields')
    mode = spec.get('presetMode', 'explicit-assignment')
    if mode not in ('explicit-assignment', 'automatic-stock'):
        raise ValueError('Explicit supported presetMode required')
    seconds = spec.get('automaticObservationSeconds', 10)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise ValueError('automaticObservationSeconds must be within1..30')
    form = lambda v: isinstance(v, str) and re.fullmatch(r'0x[0-9A-Fa-f]{8}', v) and int(v, 16) > 0
    if not form(spec['beastRace']):
        raise ValueError('Exact beast race form required')
    groups = {'humans': spec.get('actors'), 'wild': spec.get('wildActors', [])}
    if type(groups['humans']) is not list or len(groups['humans']) != 6:
        raise ValueError('Six uniquely named human fixture references are required')
    if 'wildActors' in spec and (type(groups['wild']) is not list or len(groups['wild']) != 6):
        raise ValueError('Optional wildActors requires six born-beast declarations')
    if groups['wild'] and (mode != 'automatic-stock' or spec.get('wildOriginPolicy') != 'observe-natural-host'):
        raise ValueError('Born-beast fixtures require automatic-stock and explicit observe-natural-host policy')
    if not groups['wild'] and ('wildConfigurationRequest' in spec or 'wildOriginPolicy' in spec):
        raise ValueError('Wild-only declarations require wildActors')
    tags, names = set(), set()
    for group, actors in groups.items():
        for actor in actors:
            if type(actor) is not dict or not {'tag', 'displayName', 'sex', 'base', 'placement'} <= set(actor):
                raise ValueError('Every actor requires tag/name/sex/base/placement')
            actor_fields = {'tag', 'displayName', 'sex', 'base', 'placement', 'humanRace', 'humanPreset',
                            'allowedHumanPresets', 'initialRace'}
            if set(actor) - actor_fields:
                raise ValueError('Unknown manual actor fields')
            tag, name = actor['tag'], actor['displayName']
            if (not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', tag)
                    or tag in tags or not isinstance(name, str) or not name.strip() or len(name.encode('utf-8')) > 128
                    or '\0' in name or name.casefold() in names or actor['sex'] not in ('male', 'female')):
                raise ValueError('All actor tags and names must be unique, explicit and bounded')
            tags.add(tag); names.add(name.casefold())
            actor_inspection.validate('world.read', {'domain': 'actor-fixture-inspection',
                'actor': {'fixtureTag': tag}, 'displayName': name, 'nameScope': 'reference-only',
                'phase': 'initial', 'requireActualOwnedReferenceWitness': True, 'wornArmorSlots': [30, 61],
                'minimumPositionSamples': 2, 'minimumObservationSpanMs': 200, 'positionToleranceGameUnits': 1.0})
            if group == 'humans' and not form(actor.get('humanRace')):
                raise ValueError('Every human requires its actual initial humanRace')
            if group == 'humans' and 'initialRace' in actor and actor['initialRace'] != actor['humanRace']:
                raise ValueError('Human initialRace must agree with humanRace')
            if group == 'wild' and actor.get('initialRace') != spec['beastRace']:
                raise ValueError('Wild actors must be created directly in beastRace')
            if mode == 'explicit-assignment':
                if not isinstance(actor.get('humanPreset'), str) or not actor['humanPreset']:
                    raise ValueError('Legacy explicit assignment requires humanPreset')
            else:
                pool = actor.get('allowedHumanPresets')
                if (type(pool) is not list or not 1 <= len(pool) <= 64 or len(set(pool)) != len(pool)
                        or any(not isinstance(p, str) or not p or '\0' in p or len(p.encode('utf-8')) > 512 for p in pool)):
                    raise ValueError('Automatic mode requires an exact bounded allowedHumanPresets pool per actor')
            # The platform validates plugin-local base and placement fields without game calls.
            morph_session.validate('object.perform', {'domain': 'actor-fixture', 'action': 'create',
                'actor': {'fixtureTag': tag}, 'base': actor['base'], 'placement': actor['placement'],
                'persistence': 'save-load-witness-required', 'maximumCreations': 12 if groups['wild'] else 6})
            if not 50 <= math.hypot(actor['placement']['forwardGameUnits'], actor['placement']['rightGameUnits']) <= 1000:
                raise ValueError('Actual fixture placement radius must be50..1000game units')
    for key, domain in (('catalogRequest', 'human-preset-catalog'),
                        ('configurationRequest', 'human-provider-config'),
                        ('wildConfigurationRequest', 'human-provider-config')):
        if key in spec:
            if type(spec[key]) is not dict or spec[key].get('domain') != domain:
                raise ValueError(key + ' requires the exact documented domain')
            morph_session.validate('world.read', spec[key])
            if domain == 'human-provider-config':
                morph_session.required_target_presets(spec[key], spec.get('catalogRequest', {}).get('presets'))
    primary_config, wild_config = spec.get('configurationRequest', {}), spec.get('wildConfigurationRequest', {})
    if wild_config and ('allowedAdditionalLoadedPresets' in primary_config or 'allowedAdditionalLoadedPresets' in wild_config):
        def extras(request):
            return {(item['category'], item['name']) for item in request.get('allowedAdditionalLoadedPresets', [])}
        if ('allowedAdditionalLoadedPresets' not in primary_config or 'allowedAdditionalLoadedPresets' not in wild_config
                or extras(primary_config) != extras(wild_config)):
            raise ValueError('Human and wild configuration must declare the same complete additional installed catalog')
    if {'morphObservationRequest', 'morphObservationRequestsBySex'} <= set(spec):
        raise ValueError('Choose one morph template or exact sex-specific templates, never both')
    templates = []
    if 'morphObservationRequestsBySex' in spec:
        by_sex = spec['morphObservationRequestsBySex']
        if type(by_sex) is not dict or set(by_sex) != {'male', 'female'}:
            raise ValueError('morphObservationRequestsBySex requires exactly male and female templates')
        templates.extend(by_sex.values())
    if 'morphObservationRequest' in spec:
        if len({a['sex'] for rows in groups.values() for a in rows}) != 1:
            raise ValueError('Mixed-sex actors require morphObservationRequestsBySex')
        templates.append(spec['morphObservationRequest'])
    for template in templates:
        if type(template) is not dict or {'actor', 'captureSnapshot', 'stage'} & set(template):
            raise ValueError('Morph template must leave actor, snapshot label and stage to the sequencer')
        request = dict(template, actor={'fixtureTag': groups['humans'][0]['tag']},
                       captureSnapshot='manual-validation', stage='human-own-clear')
        if request.get('domain') != 'actor-morph-link-evaluation':
            raise ValueError('A complete actor-morph-link-evaluation template is required')
        morph_session.validate('world.read', request)
    return groups


def run_plan(spec, exchange, emit, next_command, notify):
    groups = validate_spec(spec)
    actors = groups['humans']
    by_tag = {a['tag']: a for rows in groups.values() for a in rows}
    group_of = {a['tag']: group for group, rows in groups.items() for a in rows}
    automatic = spec.get('presetMode', 'explicit-assignment') == 'automatic-stock'
    maximum_creations = 12 if groups['wild'] else 6
    sequence, command_sequence, ended = 0, 0, False
    registry, hidden, origins = {}, set(), {}
    snapshot_sequence = 0
    emit({'kind': 'check-start', 'caseId': CASE, 'role': 'subject'})

    def call(envelope):
        nonlocal sequence
        sequence += 1
        record = {'kind': 'measurement', 'caseId': None if envelope['operation'] == 'finish' else CASE, 'sequence': sequence,
                  'request': envelope}
        emit(dict(record, delivery='intent'))
        raw = exchange(envelope)
        emit(dict(record, delivery='completed', rawResult=raw))
        return raw

    def domain(operation, request, timeout_seconds=30):
        return call({'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform',
                     'args': {'operation': operation, 'request': request}, 'timeoutSeconds': timeout_seconds})

    def require(name, actual, expected=True):
        passed = actual == expected
        emit({'kind': 'assertion', 'caseId': CASE, 'check': name,
              'actual': actual, 'expected': expected, 'outcome': 'passed' if passed else 'mismatch'})
        if not passed:
            raise AssertionError(name + ': ' + repr(actual))

    def identity(a):
        return domain('world.read', {'domain': 'actor-fixture-identity', 'actor': {'fixtureTag': a['tag']}})

    def inspect(a, action=None, phase='initial'):
        request = {'domain': 'actor-fixture-inspection', 'actor': {'fixtureTag': a['tag']},
                   'displayName': a['displayName'], 'nameScope': 'reference-only', 'phase': phase,
                   'requireActualOwnedReferenceWitness': True}
        if action:
            request.update(action=action, preserveInventory=True, editBaseNPC=False,
                           editBaseOutfit=False, collisionPolicy='retain-enabled', noRetryOnUnknownOutcome=True)
        else:
            request.update(wornArmorSlots=[30, 61], minimumPositionSamples=2,
                           minimumObservationSpanMs=200, positionToleranceGameUnits=1.0)
        return domain('object.perform' if action else 'world.read', request)

    def verify_inspection(a, raw):
        require(a['tag'] + '-name', raw['actor']['displayName'], a['displayName'])
        require(a['tag'] + '-owned-name', raw['fixture']['registryIdentityMatch'])
        require(a['tag'] + '-no-worn-gear', raw['fixture']['wornArmorItemCount'], 0)
        require(a['tag'] + '-no-weapons', raw['fixture']['equippedWeaponCount'], 0)
        require(a['tag'] + '-held', raw['fixture']['dontMove'])
        drift = raw['fixture']['positionDriftGameUnits']
        require(a['tag'] + '-stationary', type(drift) in (int, float) and math.isfinite(drift) and drift <= 1)
        require(a['tag'] + '-no-collision-disable', raw['fixture']['collisionDisableCommandCount'], 0)
        return raw

    def prepare_inspection(a, phase):
        for action in ('set-reference-display-name', 'unequip-all-reference-gear', 'hold-position-keep-collision'):
            inspect(a, action, phase)
        return verify_inspection(a, inspect(a, phase=phase))

    def human(a, stock_origin=False, timeout_seconds=30):
        request = {'domain': 'human-preset-state', 'actor': {'fixtureTag': a['tag']}}
        if stock_origin:
            request.update(requireStockGenerationWitness=True, requireAutomaticOrigin=True,
                expectedStockEventResponsibleInterface=None, allowedHumanPresets=a['allowedHumanPresets'],
                manualGenerationOrAssignmentCallsBeforeThisObservation=0)
        return domain('world.read', request, timeout_seconds)

    def observe_origin(a):
        stock = group_of[a['tag']] == 'humans'
        seconds = spec.get('automaticObservationSeconds', 10)
        end = time.monotonic() + seconds
        polls = 0
        observed, assigned, witnessed = None, False, False
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            observed = human(a, stock_origin=stock, timeout_seconds=min(30, remaining)); polls += 1
            value = observed['human']
            assigned = (value.get('assignedPreset') in a['allowedHumanPresets'] and
                        value.get('appliedSourceReadUnavailableCount') == 0)
            witnessed = value.get('automaticGenerationWitnessCount', 0) > 0
            if (assigned and (witnessed or not stock)) or time.monotonic() >= end or polls >= 8:
                break
            time.sleep(min(seconds / 7, max(0, end - time.monotonic())))
        # A missing subject outcome is evidence, never an excuse to force generation.
        origin = {'status': 'observed' if assigned and (witnessed or not stock) else 'unavailable',
                  'automaticOriginVerified': bool(stock and assigned and witnessed), 'pollCount': polls,
                  'observation': observed, 'testerManualFallbackUsed': False,
                  'naturalHostOrigin': 'not-applicable' if stock else 'unverified-raw-evidence'}
        origins[a['tag']] = origin
        notify('automatic-origin', {'actor': a['tag'], **origin})
        return origin

    def morph(a, identity_raw, pristine=False):
        nonlocal snapshot_sequence
        template = spec.get('morphObservationRequestsBySex', {}).get(a['sex'], spec.get('morphObservationRequest'))
        if template is None:
            return {'status': 'unavailable', 'reason': 'No complete explicit morph observation template declared',
                    'renderedMorphsVerified': False}
        snapshot_sequence += 1
        request = copy.deepcopy(template)
        request.pop('manualTesterMutationsBeforeThisObservation', None)
        if pristine:
            request['manualTesterMutationsBeforeThisObservation'] = 0
        request.update(actor={'fixtureTag': a['tag']},
            captureSnapshot='manual-%06d-%s' % (snapshot_sequence, a['tag'][:50]),
            stage='linked-beast' if identity_raw['actor']['race'] == spec['beastRace'] else 'human-own-clear')
        return domain('world.read', request)

    def current(a):
        raw = identity(a)
        require(a['tag'] + '-same-reference', raw['actor']['reference'], registry[a['tag']]['reference'])
        require(a['tag'] + '-same-base', raw['actor']['baseFormId'], registry[a['tag']]['baseFormId'])
        require(a['tag'] + '-same-sex', raw['actor']['sex'], a['sex'])
        return raw

    def configuration(request):
        actual = domain('world.read', request)['human']
        require('provider-ready', actual['officialApiReady'])
        require('stock-distribution-enabled', actual['config']['disablePresetDistribution'], 'none')
        require('no-unexpected-presets', actual['config']['unexpectedLoadedPresetCount'], 0)
        require('no-missing-presets', actual['config']['missingExpectedPresetCount'], 0)
        if 'allowedAdditionalLoadedPresets' in request:
            require('no-missing-declared-additional-presets', actual['config']['missingAllowedAdditionalPresetCount'], 0)

    def create_actor(a):
        created = domain('object.perform', {'domain': 'actor-fixture', 'action': 'create', 'base': a['base'],
            'placement': dict(a['placement'], basis='prepared-qasmoke-anchor-v1'),
            'persistence': 'save-load-witness-required', 'maximumCreations': maximum_creations,
            'actor': {'fixtureTag': a['tag']}})
        raw = identity(a)
        resolved_base = created.get('actor', {}).get('base', a['base']['formId'])
        require(a['tag'] + '-base', raw['actor']['baseFormId'], resolved_base)
        initial_race = spec['beastRace'] if group_of[a['tag']] == 'wild' else a['humanRace']
        require(a['tag'] + '-initial-race', raw['actor']['race'], initial_race)
        require(a['tag'] + '-initial-sex', raw['actor']['sex'], a['sex'])
        registry[a['tag']] = dict(raw['actor'], displayName=a['displayName'])
        if automatic:
            observe_origin(a)
        prepare_inspection(a, 'initial')
        if not automatic:
            assigned = domain('object.perform', {'domain': 'human-preset', 'action': 'assign',
                'presetName': a['humanPreset'], 'applyImmediately': True, 'assignmentOnly': False,
                'actor': {'fixtureTag': a['tag']}})
            require(a['tag'] + '-assignment-admitted', assigned['request']['assignmentAccepted'])
            observed = human(a)
            require(a['tag'] + '-assigned-preset', observed['human']['assignedPreset'], a['humanPreset'])
            require(a['tag'] + '-independent-source-reads', observed['human']['appliedSourceReadUnavailableCount'], 0)
        return raw

    def visibility(a, action):
        request = {'domain': 'actor-fixture-visibility', 'action': action,
                   'actor': {'fixtureTag': a['tag']}}
        raw = domain('world.read' if action == 'read' else 'object.perform', request)
        if (raw.get('unchangedIdentity') is not True or raw.get('actor', {}).get('reference') != registry[a['tag']]['reference']
                or raw['actor'].get('base') != registry[a['tag']]['baseFormId'] or type(raw.get('disabled')) is not bool):
            raise ValueError('Actual visibility readback belongs to another fixture or is unavailable')
        if action != 'read' and (raw['disabled'] != (action == 'hide') or
                                action == 'show' and raw.get('loaded3D') is not True):
            raise ValueError('Actual requested visibility did not settle')
        if action == 'hide': hidden.add(a['tag'])
        elif action == 'show': hidden.discard(a['tag'])
        return raw

    try:
        catalog = domain('world.read', spec['catalogRequest'])
        require('requested-presets', catalog['catalog']['missingRequestedPresetCount'], 0)
        configuration(spec['configurationRequest'])
        for a in actors:
            create_actor(a)
            morph(a, current(a), pristine=automatic)
        # Check the full arrangement again after the final actor was placed.
        for a in actors:
            require(a['tag'] + '-final-human', current(a)['actor']['race'], a['humanRace'])
            verify_inspection(a, inspect(a))
        notify('scene-ready', {'actors': registry, 'automaticTransformations': False,
            'renderedMorphsVerified': False, 'awaitingOwnerCommands': True, 'automaticOrigins': origins,
            'wildCreatedCount': 0, 'presetMode': spec.get('presetMode', 'explicit-assignment'),
            'morphObservationStatus': 'explicit-native-measurements-requested' if
                ('morphObservationRequest' in spec or 'morphObservationRequestsBySex' in spec) else 'unavailable-no-template'})
        while True:
            command = next_command()
            if (type(command) is not dict or type(command.get('sequence')) is not int or
                    command['sequence'] != command_sequence + 1 or not isinstance(command.get('sourceRef'), str) or
                    not command['sourceRef'].strip()):
                raise ValueError('Fresh sequential operator command and owner reference required')
            command_sequence += 1
            action = command.get('action')
            if action == 'finish':
                if set(command) != {'sequence', 'sourceRef', 'action'}:
                    raise ValueError('Finish has no actor or extra fields')
                emit({'kind': 'check-result', 'caseId': CASE, 'outcome': 'passed',
                      'detail': 'Scene prepared and requested mechanical actions completed; visual mod verdict belongs to owner'})
                ended = True
                call({'schemaVersion': 1, 'operation': 'finish'})
                return {'manualScenePrepared': True, 'operatorCommands': command_sequence,
                        'wholeModAccepted': False, 'renderedMorphsVerified': False}
            if action in ('add-group', 'remove-group'):
                if (set(command) != {'sequence', 'sourceRef', 'action', 'group'} or
                        command.get('group') not in groups or not groups[command['group']]):
                    raise ValueError('One declared nonempty humans/wild group required')
                group = command['group']; members = groups[group]
                if action == 'add-group' and group == 'wild' and not any(a['tag'] in registry for a in members):
                    if 'wildConfigurationRequest' in spec:
                        configuration(spec['wildConfigurationRequest'])
                    for a in members:
                        create_actor(a)
                        morph(a, current(a), pristine=True)
                results = []
                for a in members:
                    if a['tag'] not in registry:
                        # Removing a never-created wild group does not create it.
                        continue
                    requested = 'show' if action == 'add-group' else 'hide'
                    results.append({'actor': a['tag'], 'visibility': visibility(a, requested)})
                notify('command-result', {'command': command, 'outcome': 'observed', 'group': group,
                    'members': results, 'actors': registry, 'hiddenActors': sorted(hidden),
                    'otherGroupsTargeted': False, 'renderedMorphsVerified': False})
                continue
            if action == 'assign-preset':
                if (set(command) != {'sequence', 'sourceRef', 'action', 'actor', 'presetName'} or
                        command.get('actor') not in registry):
                    raise ValueError('Preset command requires one existing exact actor and presetName')
                a = by_tag[command['actor']]
                if a['tag'] in hidden:
                    raise ValueError('Show the exact group before changing its preset')
                pool = a.get('allowedHumanPresets', [a.get('humanPreset')])
                if command['presetName'] not in pool:
                    raise ValueError('Requested preset is outside the declared actor pool')
                before = current(a)
                assigned = domain('object.perform', {'domain': 'human-preset', 'action': 'assign',
                    'presetName': command['presetName'], 'applyImmediately': True, 'assignmentOnly': False,
                    'actor': {'fixtureTag': a['tag']}})
                require(a['tag'] + '-owner-assignment-admitted', assigned['request']['assignmentAccepted'])
                observed = human(a)
                require(a['tag'] + '-owner-assigned-preset', observed['human']['assignedPreset'], command['presetName'])
                notify('command-result', {'command': command, 'outcome': 'observed', 'identity': current(a),
                    'humanSource': observed, 'morphObservation': morph(a, before),
                    'separateOwnerPresetDiagnostic': True, 'automaticOrigin': origins.get(a['tag']),
                    'renderedMorphsVerified': False})
                continue
            if (set(command) != {'sequence', 'sourceRef', 'action', 'actor'} or
                    command.get('actor') not in registry or action not in ('inspect', 'to-beast', 'to-human')):
                raise ValueError('Only one existing exact fixture tag and inspect/to-beast/to-human are supported')
            a = by_tag[command['actor']]
            if a['tag'] in hidden:
                raise ValueError('Show the exact group before observing or transforming its actors')
            if group_of[a['tag']] == 'wild' and action != 'inspect':
                raise ValueError('Born-beast observations never create a human history')
            before = current(a)
            if action != 'inspect':
                race = spec['beastRace'] if action == 'to-beast' else a['humanRace']
                if before['actor']['race'] == race:
                    notify('command-result', {'command': command, 'outcome': 'already-in-requested-race', 'identity': before})
                    continue
                domain('object.perform', {'domain': 'actor-race', 'action': 'change-current-race',
                       'race': race, 'preserveBaseRecord': True, 'actor': {'fixtureTag': a['tag']}})
                after = current(a)
                require(a['tag'] + '-actual-requested-race', after['actor']['race'], race)
                inspection = prepare_inspection(a, 'returned-human' if action == 'to-human' else 'initial')
            else:
                after, inspection = before, inspect(a)
            observed = human(a)
            notify('command-result', {'command': command, 'outcome': 'observed', 'identity': after,
                   'inspection': inspection, 'humanSource': observed, 'morphObservation': morph(a, after),
                   'renderedMorphsVerified': False})
    except BaseException as error:
        if not ended:
            emit({'kind': 'check-result', 'caseId': CASE, 'outcome': 'unavailable', 'detail': str(error)})
        notify('stopped', {'reason': str(error), 'actors': registry, 'noUnknownActionReplay': True})
        raise


def directory_commands(directory, maximum_seconds):
    """Read new immutable operator files; no raw speech or inferred target parsing."""
    import json
    from pathlib import Path
    folder = Path(directory)
    if (not folder.is_absolute() or not folder.is_dir() or
            any(p.is_symlink() or getattr(p.stat(), 'st_file_attributes', 0) & 0x400
                for p in (folder, *folder.parents))):
        raise ValueError('Absolute external operator inbox required')
    deadline, sequence = time.monotonic() + maximum_seconds, 0
    while time.monotonic() < deadline:
        path = folder / ('%06d.json' % (sequence + 1))
        if path.exists():
            if path.is_symlink() or path.stat().st_size > 8192:
                raise ValueError('Operator file must be a bounded ordinary JSON file')
            raw = path.read_bytes()
            value = json.loads(raw.decode('utf-8'))
            if path.read_bytes() != raw:
                raise ValueError('Operator command changed during read; no delivery')
            sequence += 1
            yield value
        else:
            time.sleep(.1)
    raise TimeoutError('Original manual command window expired')
