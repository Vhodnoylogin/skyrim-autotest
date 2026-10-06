"""Candidate mappings; an operator must qualify their exact live semantics."""


def operations():
    fields = {
        'state.read': ['world.ready'],
        'player.read': ['player.health.points'],
        'world.read': ['form.runtimeId', 'hand.occupied', 'hand.reference.id',
                       'hand.item.plugin', 'hand.item.localId', 'hand.matchesRequestedReference',
                       'hand.continuousHold.seconds', 'inventory.entries', 'inventory.quantity.items',
                       'body_slot.allowSmall', 'body_slot.displayed', 'body_slot.position.x.gameUnits',
                       'body_slot.position.y.gameUnits', 'body_slot.position.z.gameUnits',
                       'reference.existsInLoadedWorld', 'reference.id', 'reference.quantity.items',
                       'reference.item.plugin', 'reference.item.localId'],
        'controller.perform': [], 'object.perform': [], 'menu.read': []
    }
    result = {}
    for op, names in fields.items():
        args = {'operation': op}
        if op in ('world.read', 'controller.perform', 'object.perform', 'menu.read'):
            args['request'] = {'$parameter': 'request'}
        result[op] = {'tool': 'platform', 'args': args, 'fields': {name: name for name in names}}
    return result
