"""Restart slots derived from the frozen scenario, never permission or a retry loop."""
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def step_identity(section, index, step):
    return {'section': section, 'index': index, 'name': step.get('name'),
            'argsSha256': digest(step.get('args', {}))}


def plan(scenario):
    slots = []
    for section in ('steps', 'postSteps'):
        for index, step in enumerate(scenario.get(section, [])):
            args = step.get('args', {})
            selector = args.get('request', {}).get('action')
            # Reserving a future selector does not implement or qualify it.
            restarting = ((args.get('operation') == 'input.perform' and selector == 'restart_game') or
                          (args.get('operation') == 'object.perform' and selector == 'restart_with_fixture_subject_settings'))
            if step.get('tool') == 'platform' and restarting:
                if step.get('poll'):
                    raise ValueError('Restart actions cannot poll')
                slots.append(step_identity(section, index, step))
    return {'schemaVersion': 1, 'scenarioSha256': digest(scenario), 'slots': slots,
            'maximum': len(slots)}


def verify(state):
    frozen = state.get('ownedGameRestartBudget')
    if not isinstance(frozen, dict) or frozen != plan(state['scenario']):
        raise ValueError('Frozen restart budget differs from the attempt scenario')
    return frozen


def next_slot(state):
    frozen = verify(state)
    used = state.get('ownedGameRestartCount', 0)
    if type(used) is not int or not 0 <= used < frozen['maximum']:
        raise ValueError('Declared attempt restart budget exhausted or invalid')
    slot = frozen['slots'][used]
    if state.get('activeScenarioStep') != slot:
        raise ValueError('Restart is not the next declared scenario step; no replay')
    history = state.get('gameRestartHistory', [])
    if not isinstance(history, list) or len(history) != used:
        raise ValueError('Restart history and reserved slot count differ')
    if history and history[-1].get('completed') is not True:
        raise ValueError('Previous restart is incomplete; no replay')
    return used + 1, slot


def update(state, **values):
    transition = state['gameRestartTransition']
    transition.update(values)
    history = state.get('gameRestartHistory')
    if history:
        if history[-1].get('ordinal') != transition.get('ordinal'):
            raise ValueError('Restart history identity differs')
        history[-1].update(values)


def segment_number(state, name):
    match = re.fullmatch(r'before-restart-([1-9][0-9]*)', name)
    if match is None:
        raise ValueError('Invalid restart evidence segment')
    number = int(match[1])
    if 'ownedGameRestartBudget' in state:
        maximum = verify(state)['maximum']
        used = state.get('ownedGameRestartCount', 0)
        if type(used) is not int or not 0 <= used <= maximum or number > used:
            raise ValueError('Restart segment exceeds reserved attempt slots')
    elif number > 2:
        # Historical recovery only; new runs always freeze their derived budget.
        raise ValueError('Legacy recovery cannot invent additional restart segments')
    return number
