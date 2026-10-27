"""Bounded machine-action loop inside an already initialized owned session.

No launch, receiver, microphone, interpretation, recovery or replay lives here.
"""
import math
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from . import native
from .command_bus import BusError, CommandBus, load_config, strict_json

TOOLS = {'inspect', 'menu', 'input', 'papyrus', 'platform', 'native14', 'driver'}
KEYS = {'W', 'A', 'S', 'D', 'SPACE'}
INPUT_CONTRACT = {'name': 'devbench.input', 'version': {'major': 2, 'minor': 0}}
INLINE_RESULT_BYTES = 16 * 1024
MAX_RESULT_BYTES = 16 * 1024 * 1024
PAPYRUS_READS = {'Game': {'GetPlayer'}, 'Actor': {'GetActorValue', 'GetRace', 'GetActorBase', 'IsDead'},
    'ActorBase': {'GetSex', 'GetRace', 'GetWeight'},
    'ObjectReference': {'GetPositionX', 'GetPositionY', 'GetPositionZ', 'GetAngleX', 'GetAngleY', 'GetAngleZ', 'GetScale', 'GetBaseObject', 'GetItemCount'}}


class InteractiveError(ValueError):
    pass


def validate(settings):
    required = {'channelConfig', 'maximumSeconds', 'allowedTools', 'sourceId'}
    if (type(settings) is not dict or not required <= set(settings) or set(settings) - required - {'nativeBindings','npcPersistence','morphSession'} or
            not isinstance(settings['channelConfig'], str) or not Path(settings['channelConfig']).is_absolute()):
        raise InteractiveError('interactive_session requires explicit channelConfig, maximumSeconds, allowedTools and sourceId')
    maximum, allowed = settings['maximumSeconds'], settings['allowedTools']
    if type(maximum) is not int or not 1 <= maximum <= 14400:
        raise InteractiveError('interactive_session maximumSeconds must be an integer in 1..14400')
    if (not isinstance(allowed, list) or not allowed or any(not isinstance(item, str) for item in allowed) or
            len(set(allowed)) != len(allowed) or not set(allowed) <= TOOLS):
        raise InteractiveError('interactive_session allowedTools must be a unique nonempty supported subset')
    if settings['sourceId'] != 'operator.actions':
        raise InteractiveError('interactive_session sourceId must be operator.actions')
    result = dict(settings, channelConfig=str(Path(settings['channelConfig']).resolve()), allowedTools=list(allowed))
    if 'nativeBindings' in settings:
        from .interactive_bindings import validate as validate_bindings
        result['nativeBindings'] = validate_bindings(settings['nativeBindings'])
    if 'npcPersistence' in settings:
        if type(settings['npcPersistence']) is not bool: raise InteractiveError('npcPersistence requires an explicit boolean')
        if settings['npcPersistence'] and not result.get('nativeBindings'): raise InteractiveError('NPC persistence requires frozen native actor bindings')
    if 'morphSession' in settings:
        from .morph_session import validate_config
        result['morphSession'] = validate_config(settings['morphSession'],result.get('nativeBindings'))
    return result


def _request(text, settings, session):
    from .runner import changes_reference_world
    value = strict_json(text)
    if type(value) is not dict or type(value.get('schemaVersion')) is not int or value['schemaVersion'] != 1:
        raise InteractiveError('Action text must be a schemaVersion 1 machine JSON object')
    if value.get('operation') == 'finish' and set(value) == {'schemaVersion', 'operation'}:
        return value
    if value.get('operation') == 'fixture-create':
        if set(value) != {'schemaVersion', 'operation', 'request', 'timeoutSeconds'} or type(value['request']) is not dict:
            raise InteractiveError('Fixture creation requires one explicit request and timeoutSeconds')
        timeout = value['timeoutSeconds']
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise InteractiveError('Fixture timeoutSeconds must be finite in (0,30]')
        if 'papyrus' not in settings['allowedTools'] or not settings.get('nativeBindings'):
            raise InteractiveError('Fixture creation requires the frozen nativeBindings policy and papyrus allowlist')
        from .fixture_actors import validate_request
        validate_request(value['request'], settings['nativeBindings'])
        return value
    if value.get('operation') == 'binding':
        required = {'schemaVersion', 'operation', 'bindingId', 'args', 'timeoutSeconds'}
        if (not required <= set(value) or set(value) - required - {'self'} or
                not isinstance(value['bindingId'], str) or not isinstance(value['args'], list) or
                ('self' in value and (type(value['self']) is not dict or set(value['self']) != {'reference', 'base'}))):
            raise InteractiveError('Binding request requires bindingId, typed args array, timeoutSeconds and optional exact actor self')
        timeout = value['timeoutSeconds']
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise InteractiveError('Binding timeoutSeconds must be finite in (0,30]')
        if 'papyrus' not in settings['allowedTools'] or _binding(value, settings) is None:
            raise InteractiveError('Native binding is disabled, unlisted or outside the papyrus tool allowlist')
        return value
    if set(value) != {'schemaVersion', 'operation', 'tool', 'args', 'timeoutSeconds'} or value.get('operation') != 'tool':
        raise InteractiveError('Tool request requires operation, tool, args and timeoutSeconds')
    tool, args, timeout = value['tool'], value['args'], value['timeoutSeconds']
    if tool not in settings['allowedTools'] or type(args) is not dict:
        raise InteractiveError('Tool is outside the explicit interactive allowlist or args is not an object')
    domain_request = args.get('request') if isinstance(args.get('request'),dict) else {}
    load_request = (tool=='platform' and args.get('operation')=='object.perform' and
        domain_request.get('domain')=='save-state' and domain_request.get('action')=='load-owned-disposable-once')
    maximum_timeout = 90 if load_request else 30
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= maximum_timeout:
        raise InteractiveError('Action timeoutSeconds must be finite in (0,30]')
    if changes_reference_world(tool, args):
        raise InteractiveError('Interactive requests cannot load, replace or delete the reference world')
    edition = session.state.get('configuration', {}).get('game_edition', 'vr')
    if edition == 'se' and tool in ('driver', 'native14'):
        raise InteractiveError('VR-only tool is unavailable in this SE session')
    if tool == 'inspect':
        if args.get('kind') == 'world_observer':
            from .observer_query import validate as validate_observer_query
            try:
                validate_observer_query(args, timeout, edition)
            except ValueError as exc:
                raise InteractiveError(str(exc)) from exc
        elif set(args) != {'kind'} or args['kind'] not in ('state', 'scene', 'mods', 'player'):
            raise InteractiveError('Interactive inspect supports state, scene, mods or player reads only')
    elif tool == 'menu':
        if args.get('action') == 'list':
            if set(args) - {'action', 'includeFlags'} or ('includeFlags' in args and type(args['includeFlags']) is not bool):
                raise InteractiveError('Menu list accepts only optional boolean includeFlags')
        elif args.get('action') != 'describe' or set(args) != {'action', 'menu'} or not isinstance(args['menu'], str) or not 1 <= len(args['menu']) <= 96:
            raise InteractiveError('Interactive menu supports list and explicit describe only')
    elif tool == 'input':
        action = args.get('action')
        if action in ('status', 'capabilities') and set(args) == {'action'}:
            pass
        elif (args.get('device') != 'keyboard' or action not in ('down', 'up') or args.get('key') not in KEYS or
                set(args) != ({'device', 'action', 'key', 'owner', 'maxHoldMs'} if action == 'down' else {'device', 'action', 'key', 'owner'}) or
                args.get('owner') != 'autotest-' + session.state['id']):
            raise InteractiveError('Keyboard input requires a safe gameplay key and this run owner; no console, saves or quickloads')
        elif action == 'down' and (type(args['maxHoldMs']) is not int or not 100 <= args['maxHoldMs'] <= min(1000, timeout * 1000)):
            raise InteractiveError('Keyboard down requires a 100..1000ms server lease within request timeout')
    elif tool == 'papyrus':
        if (args.get('action') != 'call' or set(args) - {'action', 'script', 'function', 'args', 'self', 'timeoutMs'} or
                args.get('function') not in PAPYRUS_READS.get(args.get('script'), set()) or not isinstance(args.get('args', []), list) or
                len(args.get('args', [])) > 2):
            raise InteractiveError('Raw Papyrus is limited to explicit known native read functions; no arbitrary script/selector escape')
        if 'self' in args and (type(args['self']) is not dict or set(args['self']) != {'form'} or
                not isinstance(args['self']['form'], str) or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,8}', args['self']['form'])):
            raise InteractiveError('Papyrus self must be one explicit form identity')
        if 'timeoutMs' in args and (type(args['timeoutMs']) is not int or not 1 <= args['timeoutMs'] <= timeout * 1000):
            raise InteractiveError('Papyrus timeoutMs must fit the enclosing request deadline')
    elif tool == 'platform':
        from . import platform, preset_domain
        platform.validate(args)
        operation, request = args.get('operation'), args.get('request', {})
        from . import morph_session
        if morph_session.validate(operation,request):
            if edition!='se' or not settings.get('morphSession') or not settings.get('nativeBindings'):
                raise InteractiveError('Morph domains require the explicit frozen SE morph session and actor bindings')
            if request.get('domain')=='save-state' and not settings.get('npcPersistence'):
                raise InteractiveError('Owned save/load requires explicit NPC persistence opt-in')
            return value
        if not (operation in platform.READS or
                operation == 'controller.perform' and request.get('action') in platform.ACTIONS['controller.perform'] or
                operation == 'object.perform' and request.get('action') in preset_domain.ACTIONS):
            raise InteractiveError('Interactive semantic actions allow bounded controllers and guarded morph presets only; no world/fixture/save/race mutation')
        if operation == 'object.perform' and not settings.get('nativeBindings'):
            raise InteractiveError('Interactive preset mutations require a frozen nativeBindings fixture policy and a newly created actor witness')
    elif tool == 'driver':
        from .scenarios import validate_driver
        validate_driver(args)
        if args.get('holdSeconds', 0) > timeout:
            raise InteractiveError('Driver lease must fit the request deadline')
    elif tool == 'native14':
        from .native14_live import validate_request
        validate_request(args)
        if args.get('transition', 'same-context') != 'same-context':
            raise InteractiveError('Interactive native14 reads must retain the same reference world')
    return value


def _binding(request, settings):
    policy = settings.get('nativeBindings')
    return next((row for row in policy['bindings'] if row['id'] == request['bindingId']), None) if policy else None


def _mutation(request, settings):
    if request['operation'] == 'fixture-create': return True
    if request['operation'] == 'binding':
        return _binding(request, settings)['effect'] == 'mutate'
    tool, args = request.get('tool'), request.get('args', {})
    return (tool == 'input' and args.get('action') in ('down', 'up') or
            tool == 'driver' and args.get('action') != 'status' or
            tool == 'platform' and args.get('operation') in ('object.perform', 'controller.perform'))


def _lease(request):
    tool, args = request.get('tool'), request.get('args', {})
    if tool == 'input' and args.get('action') == 'down': return args['maxHoldMs'] / 1000
    if tool == 'driver': return args.get('holdSeconds', 0)
    if tool == 'platform' and args.get('operation') == 'controller.perform':
        return sum(args.get('request', {}).get(key, 0) for key in ('durationSeconds', 'holdSeconds', 'settleSeconds', 'motionSeconds'))
    return 0


def _reject(bus, session, session_id, binding, command, reason):
    result = {'outcome': 'rejected', 'executed': False, 'reason': str(reason)}
    bus.delivered(session_id, command['id'], command['claimId'], binding)
    session.log('interactive-action-rejected', commandId=command['id'], **result)
    bus.complete(session_id, command['id'], command['claimId'], binding, result)


def _completion_result(session, command_id, result):
    """Preserve a large result before the bounded durable completion receipt."""
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(raw) <= INLINE_RESULT_BYTES: return result
    if len(raw) > MAX_RESULT_BYTES:
        raise InteractiveError('Interactive result exceeds the 16MiB evidence bound; no truncation or replay')
    if not re.fullmatch('[0-9a-f]{32}', command_id):
        raise InteractiveError('Evidence requires the exact command UUID')
    run_dir = Path(session.dir)
    if not run_dir.is_absolute() or not run_dir.is_dir():
        raise InteractiveError('Interactive evidence requires the existing absolute run directory')
    if (run_dir.resolve().is_relative_to(Path(__file__).resolve().parent.parent) or
            any((item / '.git').exists() for item in [run_dir, *run_dir.parents])):
        raise InteractiveError('Interactive evidence must remain outside Git and the distribution')
    folder = run_dir / 'interactive-results'
    path = folder / (command_id + '.json')
    for item in [path, *path.parents]:
        try: info = item.lstat()
        except FileNotFoundError: continue
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise InteractiveError('Interactive evidence refuses symlink/reparse-point paths')
    evidence = {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'format': 'json'}
    row = dict(evidence, commandId=command_id)
    registry = session.state.setdefault('interactiveArtifacts', [])
    if not isinstance(registry, list):
        raise InteractiveError('Interactive artifact registry is invalid')
    previous = [item for item in registry if item.get('commandId') == command_id]
    if previous and (previous != [row] or not path.is_file()):
        raise InteractiveError('Registered interactive evidence changed or disappeared; it was preserved')
    folder.mkdir(exist_ok=True)
    if not path.exists():
        temporary = folder / (command_id + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try: os.link(temporary, path)  # Atomic creation; never replace another result.
            except FileExistsError: pass
        finally:
            temporary.unlink(missing_ok=True)
    if not path.is_file() or path.read_bytes() != raw:
        raise InteractiveError('Interactive result path already contains different bytes; no overwrite/replay')
    if not previous:
        registry.append(row)
        session.save()
    return {'outcome': 'result-recorded', 'evidence': evidence}


def run(session, settings):
    """Use the caller's mutex/guardian/session; every request is single-attempt."""
    settings = validate(settings)
    if not session.state.get('gameplayBootstrap', {}).get('completed') or session.state.get('interactiveSession'):
        raise InteractiveError('Interactive hold requires completed common bootstrap and a fresh owned run')
    channel = load_config(settings['channelConfig'])
    bus = CommandBus(channel['database'], channel['claimTimeoutSeconds'])
    run_id = session.state['id']
    session_id = 'game-' + run_id
    binding = {'provider': 'skyrim-autotest', 'conversationId': run_id, 'agentId': 'owned-game-executor'}
    if any(item['sessionId'] == session_id for item in bus.status()['sessions']):
        raise InteractiveError('This machine-action session already exists; no reconnect or old-command replay is allowed')
    bus.create_session(session_id)
    bus.bind(session_id, binding)
    end = time.monotonic() + settings['maximumSeconds']
    metadata = {'sessionId': session_id, 'binding': binding, 'sourceId': settings['sourceId'],
        'channelConfig': settings['channelConfig'], 'maximumSeconds': settings['maximumSeconds'],
        'ready': True, 'liveQualified': False}
    session.state['interactiveSession'] = metadata
    session.phase('interactive-session', settings['maximumSeconds'] + 5)
    session.save()
    session.log('interactive-ready', **metadata)
    command, keyboard_owned, completed_normally = None, False, False
    try:
        while True:
            if session.heartbeat_failed.is_set():
                raise InteractiveError('Executor heartbeat failed during interactive hold')
            if not native.alive(session.state.get('game')):
                raise InteractiveError('Owned game exited or changed identity during interactive hold')
            if time.monotonic() >= end:
                raise InteractiveError('Interactive maximumSeconds expired; no automatic extension or relaunch')
            delivery = bus.next(session_id, binding)
            if delivery['blocked']:
                raise InteractiveError('Interactive delivery is active or uncertain; explicit review is required')
            command = delivery['command']
            if command is None:
                time.sleep(min(.1, max(0, end - time.monotonic())))
                continue
            try:
                if command['sourceId'] != settings['sourceId'] or command['kind'] != 'text':
                    raise InteractiveError('Only explicit operator.actions machine text is accepted; raw ASR is never interpreted')
                request = _request(command['text'], settings, session)
            except (ValueError, TypeError, KeyError) as rejected:
                _reject(bus, session, session_id, binding, command, rejected)
                command = None
                continue
            now = time.monotonic()
            deadline = min(end, now + request.get('timeoutSeconds', 1), now + command['claimUntil'] - time.time() - .25)
            if deadline <= now:
                raise InteractiveError('Action deadline/claim expired before delivery')
            if _mutation(request, settings):
                from .readiness_state import gameplay_ready
                scene = session.tool('inspect', {'kind': 'scene'}, timeout=min(3, deadline - time.monotonic()), deadline=deadline)
                menus = session.tool('menu', {'action': 'list', 'includeFlags': True}, timeout=min(3, deadline - time.monotonic()), deadline=deadline)
                ready = gameplay_ready(scene, menus)
                if request.get('tool') == 'input':
                    caps = session.tool('input', {'action': 'capabilities'}, timeout=min(3, deadline - time.monotonic()), deadline=deadline)
                    keyboard = caps.get('capabilities', {}).get('keyboard', {})
                    ready = ready and (caps.get('contract') == INPUT_CONTRACT and
                        keyboard.get('version') == 1 and keyboard.get('available') is True and keyboard.get('ready') is True and
                        keyboard.get('injection') == 'Skyrim.BSInputEventQueue' and keyboard.get('encoding') == 'DirectInputScanCode' and
                        {'down', 'up', 'status', 'releaseAll'} <= set(keyboard.get('actions', [])) and
                        request['args']['key'].lower() in {row.get('key') for row in keyboard.get('keys', []) if isinstance(row, dict)})
                if not ready or _lease(request) > deadline - time.monotonic():
                    _reject(bus, session, session_id, binding, command, 'Fresh native gameplay/input readiness or remaining lease budget is unavailable')
                    command = None
                    continue
            bus.delivered(session_id, command['id'], command['claimId'], binding)
            session.log('interactive-action-delivered', commandId=command['id'], request=request)
            if request['operation'] == 'finish':
                result = {'outcome': 'owner-finished'}
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or _lease(request) > remaining:
                    _reject(bus, session, session_id, binding, command, 'Remaining deadline cannot contain this action/lease; nothing executed')
                    command = None
                    continue
                if not native.alive(session.state.get('game')):
                    raise InteractiveError('Owned game identity changed before action invocation')
                if request['operation'] == 'binding':
                    from .interactive_bindings import guarded_call
                    arguments = {key: request[key] for key in ('bindingId', 'args', 'self') if key in request}
                    result = guarded_call(session, arguments, deadline, settings['nativeBindings'])
                elif request['operation'] == 'fixture-create':
                    from .fixture_actors import create
                    result = create(session, request['request'], deadline, settings['nativeBindings'])
                else:
                    keyboard_owned |= request['tool'] == 'input' and request['args'].get('action') == 'down'
                    if (request['tool'] == 'platform' and request['args'].get('operation') == 'object.perform' and
                            not request['args'].get('request',{}).get('domain')):
                        from .fixture_actors import guard
                        guard(session, request['args']['request']['actor'], deadline, settings['nativeBindings'])
                    if request['tool']=='platform': session.state['activeSemanticCommandId']=command['id']
                    try:
                        result = session.tool(request['tool'], request['args'], timeout=remaining, deadline=deadline)
                    finally:
                        session.state.pop('activeSemanticCommandId',None)
                result = _completion_result(session, command['id'], result)
                session.log('interactive-action-result', commandId=command['id'], result=result)
                if time.monotonic() > deadline:
                    raise InteractiveError('Action returned after its deadline; outcome requires review and is never replayed')
            bus.complete(session_id, command['id'], command['claimId'], binding, result)
            command = None
            if request['operation'] == 'finish':
                metadata.update(ready=False, reason='owner-finished')
                session.save()
                completed_normally = True
                return metadata
    except Exception as error:
        if command is not None:
            try:
                bus.reconcile(session_id, command['id'], binding, 'uncertain', 'Interactive executor stopped; inspect run evidence before any reconciliation. No automatic replay.')
            except Exception:
                pass  # Never replace the original failure or retry an uncertain outcome.
        metadata.update(ready=False, reason=str(error))
        session.save()
        session.log('interactive-stopped', reason=str(error), commandId=command['id'] if command else None, replayed=False)
        raise InteractiveError('Interactive session ended: ' + str(error)) from error
    finally:
        if keyboard_owned:
            owner, cleanup_end = 'autotest-' + run_id, time.monotonic() + 3
            try:
                if not native.alive(session.state.get('game')):
                    raise InteractiveError('Owned identity unavailable for keyboard release; no foreign input touched')
                released = session.tool('input', {'device': 'keyboard', 'action': 'releaseAll', 'owner': owner}, timeout=2, deadline=cleanup_end)
                status = session.tool('input', {'device': 'keyboard', 'action': 'status'}, timeout=max(.01, cleanup_end - time.monotonic()), deadline=cleanup_end)
                if (released.get('contract') != INPUT_CONTRACT or released.get('device') != 'keyboard' or released.get('action') != 'releaseAll' or
                        released.get('owner') != owner or released.get('failed') != [] or released.get('pending') != [] or
                        status.get('contract') != INPUT_CONTRACT or status.get('device') != 'keyboard' or status.get('ready') is not True or not isinstance(status.get('held'), list) or
                        any(not isinstance(row, dict) or not isinstance(row.get('owner'), str) or row['owner'] == owner for row in status['held']) or time.monotonic() > cleanup_end):
                    raise InteractiveError('Owner keyboard release/readback remains unverified')
                metadata['keyboardRelease'] = {'verified': True, 'owner': owner}
            except Exception as release_error:
                metadata['keyboardRelease'] = {'verified': False, 'owner': owner, 'reason': str(release_error)}
                if completed_normally:
                    raise InteractiveError('Interactive owner keyboard cleanup failed: ' + str(release_error)) from release_error
            finally:
                session.save()
                session.log('interactive-keyboard-release', **metadata['keyboardRelease'])
