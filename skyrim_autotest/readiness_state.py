"""Typed native readiness predicates shared by startup, actions and observations."""
import re


def world_loaded(scene, expected_cell=None):
    if not isinstance(scene, dict) or not isinstance(scene.get('cell'), dict):
        return False
    cell = scene['cell'].get('editorId')
    return (scene.get('playerLoaded') is True and isinstance(cell, str)
            and re.fullmatch(r'[A-Za-z0-9_]+', cell) is not None
            and cell != 'VRPlayroom01' and (expected_cell is None or cell == expected_cell))


def menus_block_gameplay(observation):
    if not isinstance(observation, dict) or observation.get('messageBoxOpen') is not False:
        return True
    names, states = observation.get('openMenus'), observation.get('menuStates')
    if (not isinstance(names, list) or not isinstance(states, list)
            or any(not isinstance(name, str) for name in names)
            or any(not isinstance(row, dict) or not isinstance(row.get('name'), str) for row in states)
            or len(set(names)) != len(names) or len(states) != len(names)
            or {row.get('name') for row in states} != set(names)):
        return True
    for row in states:
        fields = ('alwaysOpen', 'pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause')
        if row.get('available') is not True or any(type(row.get(key)) is not bool for key in fields):
            return True
        if (row.get('name') == 'Console' or row['pausesGame'] or row['modal'] or row['freezeFramePause']
                or (not row['alwaysOpen'] and (row['usesCursor'] or row['usesMenuContext']))):
            return True
    return False


def gameplay_ready(scene, menus, expected_cell=None):
    return world_loaded(scene, expected_cell) and not menus_block_gameplay(menus)
