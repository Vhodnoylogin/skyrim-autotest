"""Strict admission of the SE observer's bounded, read-only inspection schema.

This validates request shape only. Existing session ownership, absolute deadline,
provider qualification and returned evidence checks remain the caller's job.
"""
import json
import math
import re


_FORM = re.compile(r'0x[0-9a-fA-F]{1,8}\Z')
_TOP_FIELDS = {'kind', 'action', 'refs', 'nodes', 'timeoutMs',
               'actors', 'skee', 'obody', 'cbpc'}
_MAX_REQUEST_BYTES = 16 * 1024


def _object(value, allowed, label, required=()):
    if type(value) is not dict:
        raise ValueError(f'{label} must be an object')
    if set(value) - allowed or not set(required) <= set(value):
        raise ValueError(f'{label} contains unsupported or missing fields')


def _integer(value, minimum, maximum, label):
    # Python bool is an int subclass; accepting it would differ from native JSON.
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer in {minimum}..{maximum}')


def _form(value):
    if type(value) is int and 1 <= value <= 0xffffffff:
        return
    if type(value) is str and _FORM.fullmatch(value) and int(value[2:], 16) != 0:
        return
    raise ValueError('ref must be a nonzero uint32 or 0x hexadecimal FormID')


def _refs(value, minimum=0, label='refs'):
    if type(value) is not list or not minimum <= len(value) <= 16:
        raise ValueError(f'{label} must contain {minimum}..16 FormIDs')
    for item in value:
        _form(item)


def _name(value, label):
    if type(value) is not str or not 1 <= len(value) <= 128 or '\0' in value:
        raise ValueError(f'{label} must be 1..128 UTF-8 bytes without NUL')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeEncodeError as exc:
        raise ValueError(f'{label} must be valid UTF-8') from exc
    if size > 128:
        raise ValueError(f'{label} must be 1..128 UTF-8 bytes without NUL')


def _wire_size(args):
    # Match default stdlib JSON spacing and conservatively count ASCII escapes:
    # the session transport may use json.dumps' default ensure_ascii=True.
    # Counting native UTF-8 alone would admit requests inflated past 16KiB later.
    try:
        encoded = json.dumps(args, ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise ValueError('Observer query must contain finite JSON values') from exc
    if len(encoded) > _MAX_REQUEST_BYTES:
        raise ValueError('Observer query exceeds 16KiB serialized JSON')


def validate(args, timeoutSeconds, edition):
    """Raise ValueError on refusal; return the same unmodified args on success."""
    if type(edition) is not str or edition != 'se':
        raise ValueError('This World Observer query schema is admitted only for SE')
    if type(timeoutSeconds) not in (int, float):
        raise ValueError('Observer enclosing timeoutSeconds must be finite and positive')
    try:
        finite = math.isfinite(timeoutSeconds)
    except (OverflowError, ValueError):
        finite = False
    if not finite or timeoutSeconds <= 0:
        raise ValueError('Observer enclosing timeoutSeconds must be finite and positive')
    _object(args, _TOP_FIELDS, 'Observer query', {'kind'})
    if type(args['kind']) is not str or args['kind'] != 'world_observer':
        raise ValueError('Observer query requires kind world_observer')
    action = args.get('action', 'snapshot')
    if type(action) is not str or action not in ('snapshot', 'capabilities'):
        raise ValueError('Observer action must be snapshot or capabilities')
    if action == 'capabilities':
        _object(args, {'kind', 'action'}, 'Observer capabilities', {'kind', 'action'})
        _wire_size(args)
        return args

    timeout_ms = args.get('timeoutMs', 1500)
    _integer(timeout_ms, 100, 3000, 'timeoutMs')
    if timeout_ms / 1000 > timeoutSeconds:
        raise ValueError('Observer timeoutMs exceeds enclosing timeoutSeconds')
    if 'refs' in args:
        _refs(args['refs'])
    if 'nodes' in args:
        nodes = args['nodes']
        if type(nodes) is not list or len(nodes) > 64:
            raise ValueError('nodes must be an array with at most 64 entries')
        for node in nodes:
            _object(node, {'ref', 'name', 'firstPerson'}, 'node', {'ref', 'name'})
            _form(node['ref'])
            _name(node['name'], 'node name')
            if 'firstPerson' in node and type(node['firstPerson']) is not bool:
                raise ValueError('node firstPerson must be boolean')
    for field in ('actors', 'cbpc'):
        if field in args and type(args[field]) is not bool:
            raise ValueError(f'{field} must be boolean')
    if 'skee' in args:
        skee = args['skee']
        _object(skee, {'refs', 'morphs'}, 'skee', {'refs', 'morphs'})
        _refs(skee['refs'], 1, 'skee refs')
        morphs = skee['morphs']
        if type(morphs) is not list or not 1 <= len(morphs) <= 32:
            raise ValueError('skee morphs must contain 1..32 explicit names')
        if len(skee['refs']) * len(morphs) > 64:
            raise ValueError('skee allows at most 64 actor/morph pairs')
        for name in morphs:
            _name(name, 'morph name')
    if 'obody' in args:
        obody = args['obody']
        _object(obody, {'refs', 'afterSequence', 'maximumEvents'}, 'obody')
        if 'refs' in obody:
            _refs(obody['refs'], 1, 'obody refs')
        if 'afterSequence' in obody:
            _integer(obody['afterSequence'], 0, 0xffffffffffffffff, 'obody afterSequence')
        if 'maximumEvents' in obody:
            _integer(obody['maximumEvents'], 1, 256, 'obody maximumEvents')
    _wire_size(args)
    return args
