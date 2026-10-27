"""Prepare an owned inspection scene, then execute explicit operator commands.

This sequencer shares the existing companion transport. It launches nothing,
opens no audio and interprets no speech. Scene readiness is separate from a
rendered-morph or whole-mod verdict.
"""
import math
import time


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


def run_plan(spec, exchange, emit, next_command, notify):
    actors = spec['actors']
    if (len(actors) != 6 or len({a['tag'] for a in actors}) != 6 or
            len({a['displayName'] for a in actors}) != 6):
        raise ValueError('Six uniquely named fixture references are required')
    by_tag = {a['tag']: a for a in actors}
    sequence, command_sequence, ended = 0, 0, False
    registry = {}
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

    def domain(operation, request):
        return call({'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform',
                     'args': {'operation': operation, 'request': request}, 'timeoutSeconds': 30})

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

    def human(a):
        return domain('world.read', {'domain': 'human-preset-state', 'actor': {'fixtureTag': a['tag']}})

    def current(a):
        raw = identity(a)
        require(a['tag'] + '-same-reference', raw['actor']['reference'], registry[a['tag']]['reference'])
        require(a['tag'] + '-same-base', raw['actor']['baseFormId'], a['base']['formId'])
        return raw

    try:
        catalog = domain('world.read', spec['catalogRequest'])
        require('requested-presets', catalog['catalog']['missingRequestedPresetCount'], 0)
        configuration = domain('world.read', spec['configurationRequest'])['human']
        require('provider-ready', configuration['officialApiReady'])
        require('stock-distribution-enabled', configuration['config']['disablePresetDistribution'], 'none')
        require('no-unexpected-presets', configuration['config']['unexpectedLoadedPresetCount'], 0)
        require('no-missing-presets', configuration['config']['missingExpectedPresetCount'], 0)
        for a in actors:
            domain('object.perform', {'domain': 'actor-fixture', 'action': 'create', 'base': a['base'],
                   'placement': dict(a['placement'], basis='prepared-qasmoke-anchor-v1'), 'persistence': 'save-load-witness-required',
                   'maximumCreations': 6, 'actor': {'fixtureTag': a['tag']}})
            raw = identity(a)
            require(a['tag'] + '-base', raw['actor']['baseFormId'], a['base']['formId'])
            require(a['tag'] + '-initial-human', raw['actor']['race'], a['humanRace'])
            registry[a['tag']] = dict(raw['actor'], displayName=a['displayName'])
            prepare_inspection(a, 'initial')
            assigned = domain('object.perform', {'domain': 'human-preset', 'action': 'assign',
                       'presetName': a['humanPreset'], 'applyImmediately': True, 'assignmentOnly': False,
                       'actor': {'fixtureTag': a['tag']}})
            require(a['tag'] + '-assignment-admitted', assigned['request']['assignmentAccepted'])
            observed = human(a)
            require(a['tag'] + '-assigned-preset', observed['human']['assignedPreset'], a['humanPreset'])
            require(a['tag'] + '-independent-source-reads', observed['human']['appliedSourceReadUnavailableCount'], 0)
        # Check the full arrangement again after the final actor was placed.
        for a in actors:
            require(a['tag'] + '-final-human', current(a)['actor']['race'], a['humanRace'])
            verify_inspection(a, inspect(a))
        notify('scene-ready', {'actors': registry, 'automaticTransformations': False,
                              'renderedMorphsVerified': False, 'awaitingOwnerCommands': True})
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
            if (set(command) != {'sequence', 'sourceRef', 'action', 'actor'} or
                    command.get('actor') not in by_tag or action not in ('inspect', 'to-beast', 'to-human')):
                raise ValueError('Only one exact fixture tag and inspect/to-beast/to-human are supported')
            a = by_tag[command['actor']]
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
                   'inspection': inspection, 'humanSource': observed, 'renderedMorphsVerified': False})
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
