"""Initial executor world epoch, established by native events and settled gameplay."""
import copy
import time

from .owned_saves import Events, lifecycle


class InitialWorld:
    def __init__(self, session, mode):
        from .platform import Backend
        self.s, self.mode = session, mode
        if session.state.get('initialWorldTransition'):
            raise ValueError('Initial world transition already requested; no replay')
        game = copy.deepcopy(session.state.get('game'))
        if not isinstance(game, dict) or not game.get('pid') or not game.get('birth'):
            raise ValueError('Initial world requires an exact owned game identity')
        cursor = session.capture_probe_cursor()
        self.events = Events(Backend(session, time.monotonic()+360), cursor)
        self.record = dict(completed=False, mode=mode, beforeGame=game,
                           cursorBefore=cursor, cursor=cursor, events=[])
        session.state['initialWorldTransition'] = self.record
        session.save()

    def read(self):
        if self.s.state.get('game') != self.record['beforeGame']:
            raise ValueError('Initial world process identity changed')
        fresh = self.events.read()
        self.record['events'].extend(copy.deepcopy(fresh))
        self.record['cursor'] = self.events.cursor
        names = [lifecycle(e) for e in self.record['events']
                 if lifecycle(e) in ('preLoadGame', 'postLoadGame', 'newGame')]
        if self.mode == 'fixture':
            if names not in ([], ['preLoadGame'], ['preLoadGame', 'postLoadGame']):
                raise ValueError('Initial fixture lacks a unique ordered native load transition')
        elif any(n != 'newGame' for n in names) or len(names) > 1:
            raise ValueError('Unexpected save load or repeated New Game during initial world')
        self.s.save()
        return names

    def fixture_loaded(self):
        return self.read() == ['preLoadGame', 'postLoadGame']

    def complete(self, scene, menus):
        if self.record['completed']:
            raise ValueError('Initial world transition already completed; no replay')
        names = self.read()
        state = self.s.state
        if self.mode == 'fixture' and names != ['preLoadGame', 'postLoadGame']:
            raise ValueError('Initial fixture has no native pre/post load completion')
        from .readiness_state import gameplay_ready
        if not gameplay_ready(scene, menus, state.get('scenario', {}).get('cell')):
            raise ValueError('Initial world is not actual gameplay')
        if self.mode == 'new-game':
            from .bootstrap import new_game_transition
            proof = state.get('newGameStarted', {})
            if (proof.get('saveLoaded') is not False or proof.get('consoleBootstrap') is not False
                    or not proof.get('events') or not all(e in self.record['events'] for e in proof['events'])):
                raise ValueError('Initial New Game transition proof is unavailable')
            fresh = proof['events']
            closed = [e for e in fresh if e.get('topic') == 'menu' and
                      e.get('data') == dict(name='Main Menu', opening=False)]
            loading = [e for e in fresh if e.get('topic') == 'menu' and
                       e.get('data') == dict(name='Loading Menu', opening=True)]
            loaded = [e for e in fresh if e.get('topic') == 'scene.cellLoaded']
            if not new_game_transition(closed, loading, loaded, proof.get('initialScene', {})):
                raise ValueError('Initial New Game lacks native menu/loading/cell provenance')
        if self.mode == 'cell' and not any(
                e.get('topic') == 'scene.cellLoaded' and isinstance(e.get('data'), dict)
                and e['data'].get('cell') == scene.get('cell', {}).get('editorId')
                for e in self.record['events']):
            raise ValueError('Initial cell has no fresh native cell-loaded event')
        generation = state.get('ownedWorldGeneration', 0)
        if type(generation) is not int or generation < 0:
            raise ValueError('Initial world epoch is malformed')
        state['ownedWorldGeneration'] = generation+1
        self.record.update(completed=True, afterGame=copy.deepcopy(state['game']),
                           worldGeneration=generation+1, scene=copy.deepcopy(scene),
                           menus=copy.deepcopy(menus),
                           basis='contiguous native initial transition and common settled gameplay; executor epoch, not atomic engine generation')
        self.s.save()
        self.s.log('initial-world-completed', transition=copy.deepcopy(self.record))
