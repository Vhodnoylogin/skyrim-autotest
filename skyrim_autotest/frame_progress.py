"""Bounded observation of the owned game's real DevBench update counter."""
import copy


DOMAIN = 'game-frame-progress'


def validate(operation, request):
    if not isinstance(request, dict) or request.get('domain') != DOMAIN:
        return False
    if operation != 'world.read' or set(request) != {'domain', 'observationSeconds', 'minimumAdvance'}:
        raise ValueError('Frame progress is an exact read-only observation')
    from .platform import number
    number(request['observationSeconds'], .05, 2)
    advance = request['minimumAdvance']
    if type(advance) is not int or not 1 <= advance <= 600:
        raise ValueError('Frame progress needs a positive bounded integer advance')
    return True


def observe(backend, request):
    validate('world.read', request)
    from . import fixture_actors
    from .runner import request as health_request
    state = backend.s.state
    game = copy.deepcopy(state.get('game'))
    generation, run = state.get('ownedWorldGeneration'), state.get('id')
    if (not isinstance(game, dict) or type(game.get('pid')) is not int or
            type(generation) is not int or generation < 1 or not isinstance(run, str) or not run):
        raise ValueError('Frame progress requires the actual owned run/game/world')

    def guarded():
        fixture_actors._owned(backend, game)
        if state.get('ownedWorldGeneration') != generation or state.get('id') != run:
            raise ValueError('World/run changed across frame observation')
        backend.remaining()

    def sample():
        guarded()
        raw = health_request(state['port'], 'api/health', timeout=min(2, backend.remaining()))
        backend.remaining()
        if (not isinstance(raw, dict) or type(raw.get('pid')) is not int or raw['pid'] != game['pid'] or
                type(raw.get('frame')) is not int or raw['frame'] < 0):
            raise ValueError('Actual owned DevBench frame counter is unavailable')
        guarded()
        return raw

    before = sample()
    backend.pause(request['observationSeconds'])
    after = sample()
    delta = after['frame'] - before['frame']
    if delta < 0:
        raise ValueError('DevBench frame counter regressed during observation')
    result = {'gameFrames': {'advanced': delta >= request['minimumAdvance'], 'delta': delta,
                            'before': before['frame'], 'after': after['frame'],
                            'worldGeneration': generation},
              'healthSamples': [before, after], 'processIdentity': game,
              'basis': 'Actual game-update counter over a bounded same-world interval; not raster/mesh-quality proof'}
    backend.s.log('platform-game-frame-progress', observation=result)
    return result
