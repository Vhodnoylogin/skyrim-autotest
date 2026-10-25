"""Read live provider contracts before test fixture/input mutations."""


def qualify_readiness(session):
    """Require explicit native menu metadata before any world-changing bootstrap."""
    from .runner import request, Blocked
    descriptor = request(session.state['port'], 'api/tools', timeout=3)
    tools = descriptor.get('tools') if isinstance(descriptor, dict) else None
    menus = [row for row in tools or [] if isinstance(row, dict) and row.get('name') == 'menu']
    schema = menus[0].get('inputSchema', {}) if len(menus) == 1 else {}
    if schema.get('properties', {}).get('includeFlags', {}).get('type') != 'boolean':
        raise Blocked('DevBench native menu flags unavailable; build/qualify tools/build_devbench_current.py compatibility candidate')
    observation = session.tool('menu', {'action': 'list', 'includeFlags': True}, timeout=8)
    rows = observation.get('menuStates')
    names = observation.get('openMenus')
    fields = ('alwaysOpen', 'pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause')
    if (type(observation.get('messageBoxOpen')) is not bool or not isinstance(rows, list)
            or not isinstance(names, list) or any(not isinstance(n, str) for n in names)
            or len(set(names)) != len(names) or len(rows) != len(names)
            or any(not isinstance(r, dict) or not isinstance(r.get('name'), str) for r in rows)
            or {r['name'] for r in rows} != set(names)
            or any(type(r.get('available')) is not bool or (r['available'] and
                       any(type(r.get(k)) is not bool for k in fields)) for r in rows)):
        raise Blocked('DevBench native menu flag response is incomplete; gameplay readiness cannot be established')
    session.log('readiness-api-contract', nativeMenuFlags=True, gameplayReady=False,
                basis='Observed native metadata availability, not a playable-world assertion')
    session.state['readinessApi'] = {'nativeMenuFlags': True}
    session.save()

def validate_observer_descriptor(result):
    entries = [entry for entry in result.get('extensions', []) if entry.get('kind') == 'world_observer']
    if len(entries) != 1:
        raise AssertionError('Unique world_observer extension descriptor unavailable')
    descriptor = entries[0].get('descriptor', {})
    properties = descriptor.get('inputSchema', {}).get('properties', {})
    refs = properties.get('refs', {})
    if (descriptor.get('readOnly') is not True or properties.get('kind', {}).get('const') != 'world_observer'
            or refs.get('type') != 'array' or refs.get('maxItems', 0) < 1):
        raise AssertionError('Observer extension does not declare this read-only refs query')
    return descriptor


MOBILITY = {
    'ObjectReference': ('memberFunctions', {
        'GetPositionX': [], 'GetPositionY': [], 'GetPositionZ': [], 'GetAngleZ': [],
        'GetItemCount': ['form'], 'PlaceAtMe': ['form', 'int', 'bool', 'bool'],
        'SetPosition': ['float', 'float', 'float'],
        'Is3DLoaded': [], 'SetMotionType': ['int', 'bool'],
    }),
    'Game': ('globalFunctions', {
        'EnablePlayerControls': ['bool'] * 8 + ['int'],
        'IsMovementControlsEnabled': [], 'IsFightingControlsEnabled': [],
        'IsLookingControlsEnabled': [], 'IsActivateControlsEnabled': [],
        'GetCurrentCrosshairRef': [], 'GetPlayerGrabbedRef': [],
    }),
    'Utility': ('globalFunctions', {
        'GetINIBool': ['string'], 'GetINIFloat': ['string'],
        'SetINIBool': ['string', 'bool'],
    }),
}
HAND = {
    'ObjectReference': ('memberFunctions', {
        'GetPositionX': [], 'GetPositionY': [], 'GetPositionZ': [],
        'PlaceAtMe': ['form', 'int', 'bool', 'bool'],
        'MoveTo': ['objectreference', 'float', 'float', 'float', 'bool'],
        'Enable': ['bool'], 'Is3DLoaded': [], 'GetMass': [], 'Disable': ['bool'], 'Delete': [],
    }),
    'NetImmerse': ('globalFunctions', {
        'HasNode': ['objectreference', 'string', 'bool'],
        'GetNodeWorldPositionX': ['objectreference', 'string', 'bool'],
        'GetNodeWorldPositionY': ['objectreference', 'string', 'bool'],
        'GetNodeWorldPositionZ': ['objectreference', 'string', 'bool'],
    }),
    'HiggsVR': ('globalFunctions', {
        'GetSetting': ['string'], 'SetSetting': ['string', 'float'],
        'CanGrabObject': ['bool'], 'GetGrabbedObject': ['bool'], 'GetGrabbedNodeName': ['bool'],
    }),
}


def validate_description(script, description, scope, methods):
    if str(description.get('name', '')).casefold() != script.casefold():
        raise AssertionError('Live Papyrus script identity mismatch: ' + script)
    values = description.get(scope)
    if not isinstance(values, list):
        raise AssertionError('Live Papyrus function metadata unavailable: ' + script)
    found = {str(value.get('name', '')).casefold(): value for value in values if isinstance(value, dict)}
    checked = []
    for name, types in methods.items():
        value = found.get(name.casefold())
        if not value:
            raise AssertionError('Live API missing ' + script + '.' + name)
        params = value.get('params')
        if not isinstance(params, list) or [str(p.get('type', '')).casefold() for p in params] != types:
            raise AssertionError('Live API parameter mismatch: ' + script + '.' + name)
        checked.append({'script': script, 'function': name, 'scope': scope,
                        'params': params, 'returnType': value.get('returnType'), 'native': value.get('native')})
    return checked


def read_description(session, script):
    """Bounded metadata reads only; failures are retained, mutations never retried."""
    import time
    from .runner import HTTPResponseError
    end = time.monotonic() + 15
    attempt = 0
    while True:
        attempt += 1
        try:
            return session.tool('papyrus', {'action': 'describe', 'script': script},
                                timeout=5, deadline=end)
        except HTTPResponseError as error:
            if error.route != 'api/tool/papyrus' or error.status not in (500, 502, 503, 504):
                raise
            session.log('papyrus-metadata-read-retry', script=script, attempt=attempt,
                        status=error.status, body=error.body, diagnostics=error.diagnostics,
                        remainingSeconds=max(0, end-time.monotonic()),
                        domain='read-only API metadata; server cause unqualified')
            if time.monotonic() >= end:
                raise
            time.sleep(min(.5, max(0, end-time.monotonic())))


def qualify(session, mobility=False, hand=False):
    required = {}
    for table, enabled in ((MOBILITY, mobility), (HAND, hand)):
        if enabled:
            for script, (scope, methods) in table.items():
                if script not in required:
                    required[script] = (scope, {})
                required[script][1].update(methods)
    session.phase('qualify-live-papyrus-api', 90)
    checked = []
    for script, (scope, methods) in required.items():
        value = read_description(session, script)
        checked.extend(validate_description(script, value, scope, methods))
    session.log('live-papyrus-api-qualified', methods=checked)
    session.state['livePapyrusApi'] = checked
    session.state['checks'].append({'name': 'live Papyrus API signatures qualified',
                                    'result': 'passed', 'observation': checked})
    session.save()
