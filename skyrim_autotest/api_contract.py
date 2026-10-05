"""Read live Papyrus signatures before test fixture/input mutations."""

MOBILITY = {
    'ObjectReference': ('memberFunctions', {
        'GetPositionX': [], 'GetPositionY': [], 'GetPositionZ': [], 'GetAngleZ': [],
        'GetItemCount': ['form'], 'PlaceAtMe': ['form', 'int', 'bool', 'bool'],
        'SetPosition': ['float', 'float', 'float'],
    }),
    'Game': ('globalFunctions', {
        'EnablePlayerControls': ['bool'] * 8 + ['int'],
        'IsMovementControlsEnabled': [], 'IsFightingControlsEnabled': [],
        'IsLookingControlsEnabled': [], 'IsActivateControlsEnabled': [],
        'GetCurrentCrosshairRef': [],
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
        value = session.tool('papyrus', {'action': 'describe', 'script': script})
        checked.extend(validate_description(script, value, scope, methods))
    session.log('live-papyrus-api-qualified', methods=checked)
    session.state['livePapyrusApi'] = checked
    session.state['checks'].append({'name': 'live Papyrus API signatures qualified',
                                    'result': 'passed', 'observation': checked})
    session.save()
