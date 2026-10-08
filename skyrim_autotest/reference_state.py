"""Sampled exact-reference presence; absence never supplies a live stack count."""


def form(value):
    if not isinstance(value, str) or not value.startswith('0x'):
        raise ValueError('Exact native reference identity unavailable')
    try:
        result = int(value, 16)
    except ValueError:
        raise ValueError('Exact native reference identity unavailable') from None
    if not 0 < result <= 0xFFFFFFFF:
        raise ValueError('Exact native reference identity unavailable')
    return result


def presence(b, ref, tagged):
    raw = b.call('inspect', {'kind': 'world_observer', 'refs': [ref]})
    if (not isinstance(raw, dict) or raw.get('ok') is not True or
            raw.get('phase') != 'skse_main_thread_task' or
            not isinstance(raw.get('sessionId'), str) or not raw['sessionId'] or
            type(raw.get('loadGeneration')) is not int or raw['loadGeneration'] <= 0 or
            not isinstance(raw.get('refs'), list) or len(raw['refs']) != 1):
        raise ValueError('Exact native reference presence observation unavailable')
    old = tagged.get('incarnation')
    if old is not None and (not isinstance(old, dict) or
            old.get('sessionId') != raw['sessionId'] or
            old.get('loadGeneration') != raw['loadGeneration']):
        raise ValueError('Tagged reference observer session/generation changed')
    row = raw['refs'][0]
    if not isinstance(row, dict):
        raise ValueError('Exact native reference presence observation unavailable')
    # This exact reason is produced by Observer's native Ref(id)==nullptr path.
    # Other unavailable reasons (deadline, non-finite transform, etc.) prove nothing.
    if row.get('status') == 'unavailable':
        if (form(row.get('form')) != form(ref) or
                row.get('reason') != 'Reference not resolved' or 'identity' in row):
            raise ValueError('Native reference absence is not established')
        return 'not_resolved', raw
    identity = row.get('identity', {})
    if (row.get('status') != 'available' or not isinstance(identity, dict) or
            form(identity.get('form')) != form(ref) or
            identity.get('loadGeneration') != raw['loadGeneration'] or
            type(identity.get('runtimeHandle')) is not int or identity['runtimeHandle'] <= 0 or
            any(type(row.get(k)) is not bool for k in ('loaded3D', 'deleted', 'disabled'))):
        raise ValueError('Exact native reference presence/identity unavailable')
    if old is not None and identity['runtimeHandle'] != old.get('runtimeHandle'):
        raise ValueError('Tagged reference runtime handle changed')
    if row['deleted']:
        return 'deleted', raw
    return ('loaded' if row['loaded3D'] else 'unloaded'), raw


def read(b, req):
    b.guard_world()
    tagged = b.s.state.get('platformReferences', {}).get(req['referenceTag'])
    if not isinstance(tagged, dict) or not tagged.get('id'):
        raise ValueError('Reference tag is unavailable in this world generation')
    ref = tagged['id']
    wanted = form(ref)
    # An id-only creation tag can have a later acquired alias with a known
    # incarnation. Reuse that evidence, never adopt a replacement live handle.
    known = [v['incarnation'] for v in b.s.state.get('platformReferences', {}).values()
             if isinstance(v, dict) and form(v.get('id')) == wanted and 'incarnation' in v]
    if known and any(v != known[0] for v in known):
        raise ValueError('Reference tags disagree about the observed incarnation')
    expected = dict(tagged, **({'incarnation': known[0]} if known else {}))
    raw = b.call('inspect', {'kind': 'refs', 'formId': ref})
    if not isinstance(raw, dict) or not isinstance(raw.get('refs'), list):
        raise ValueError('Exact native reference/stack-count observation unavailable')
    rows = raw['refs']
    if ('count' in raw and (type(raw['count']) is not int or raw['count'] != len(rows))) or len(rows) > 1:
        raise ValueError('Exact native reference response is inconsistent')
    if rows and (not isinstance(rows[0], dict) or form(rows[0].get('formId')) != wanted):
        raise ValueError('Exact native reference response targets a different reference')
    if not rows and raw.get('count') != 0:
        raise ValueError('Exact native reference lookup outcome unavailable')

    # A missing count may be expected after stow/deletion. Ask the native presence
    # provider instead of synthesizing zero, trusting an empty list, or retrying.
    row = rows[0] if rows else None
    state, observer = presence(b, ref, expected)
    if state == 'loaded':
        if row is None:
            raise ValueError('Native reference presence changed between samples')
        loaded = b.pap('ObjectReference', 'Is3DLoaded', target=ref)
        if type(loaded) is not bool:
            raise ValueError('Native Is3DLoaded boolean unavailable')
        if loaded is False:
            raise ValueError('Native reference presence changed between samples')
    if state in ('not_resolved', 'deleted', 'unloaded'):
        reference = {'id': ref, 'idBasis': 'requested historical tag; not a live identity claim',
                     'existsInLoadedWorld': False, 'presence': state,
                     'quantity': {'available': False, 'reason': 'No live loaded world stack'},
                     'item': {'available': False, 'reason': 'No live loaded world item'}}
    else:
        if row is None or type(row.get('quantityItems')) is not int or row['quantityItems'] < 0:
            raise ValueError('Exact native reference/stack-count observation unavailable')
        reference = {'id': ref, 'existsInLoadedWorld': True,
                     'quantity': {'items': row['quantityItems']}, 'item': b.item(ref)}
    b.guard_world()
    if state == 'loaded' and 'incarnation' not in tagged:
        identity = observer['refs'][0]['identity']
        tagged['incarnation'] = {'sessionId': observer['sessionId'],
                                 'loadGeneration': observer['loadGeneration'],
                                 'runtimeHandle': identity['runtimeHandle']}
        b.s.save()
    result = {'reference': reference, 'providerObservation': raw,
              'observationBasis': 'sequential native reads bracketed by world lifecycle; not atomic'}
    if observer is not None:
        result['presenceObservation'] = observer
    return result
