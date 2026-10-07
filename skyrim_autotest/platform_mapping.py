"""Candidate mappings; an operator must qualify their exact live semantics."""


def operations():
    fields = {
        'state.read': ['world.ready'],
        'player.read': ['player.health.points', 'actor.reference', 'actor.base', 'actor.sex',
                        'actor.race', 'actor.loaded3D', 'actor.weight'],
        'world.read': ['save.completed', 'save.ownedByAttempt', 'save.essSha256', 'save.skseSha256',
                       'lifecycle.worldReady', 'lifecycle.pidChanged', 'lifecycle.generationChanged',
                       'lifecycle.oldReferenceTagsInvalidated', 'alchemy.effects.0.runtimeId', 'alchemy.runtimeId', 'alchemy.poison', 'alchemy.hostile', 'alchemy.food',
                       'alchemy.effectCount', 'alchemy.effects', 'alchemy.hasDetrimentalEffect',
                       'form.runtimeId', 'hand.occupied', 'hand.reference.id',
                       'hand.quantity.items', 'hand.item.plugin', 'hand.item.localId', 'hand.matchesRequestedReference',
                       'hand.continuousHold.seconds', 'inventory.entries', 'inventory.quantity.items',
                       'body_slot.allowSmall', 'body_slot.displayed', 'body_slot.position.x.gameUnits',
                       'body_slot.position.y.gameUnits', 'body_slot.position.z.gameUnits',
                       'reference.existsInLoadedWorld', 'reference.id', 'reference.quantity.items',
                       'reference.item.plugin', 'reference.item.localId', 'actor.reference', 'actor.base',
                       'actor.sex', 'actor.race', 'actor.loaded3D', 'actor.weight',
                       'actorBase.sex', 'actorBase.race', 'morph.value'],
        'controller.perform': [], 'object.perform': ['action.completed'], 'input.perform': [], 'menu.read': []
    }
    result = {}
    for op, names in fields.items():
        args = {'operation': op}
        if op in ('world.read', 'controller.perform', 'object.perform', 'input.perform', 'menu.read'):
            args['request'] = {'$parameter': 'request'}
        result[op] = {'tool': 'platform', 'args': args, 'fields': {name: name for name in names}}
    return result
