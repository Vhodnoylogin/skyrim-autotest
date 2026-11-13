"""SE startup admission using listener-side native events, before task requests."""
import time
import hashlib
from pathlib import Path
import re


def wait_main_menu(session, timeout=75):
    from . import runner
    session.phase('se-native-startup-events', timeout + 5)
    end = time.monotonic() + timeout
    cursor, loaded, menu = 0, False, False
    samples = []
    while time.monotonic() < end:
        remaining = end - time.monotonic()
        game = session.state.get('game')
        if not game or not runner.native.alive(game):
            raise runner.Blocked('Owned SE identity unavailable during startup')
        health = runner.request(session.state['port'], 'api/health', timeout=min(3, remaining))
        if health.get('pid') != game['pid']:
            raise runner.Blocked('SE startup health identity changed')
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        envelope = runner.request(session.state['port'], 'api/events?since=' + str(cursor),
                                  timeout=min(3, remaining))
        events, head = envelope.get('events'), envelope.get('headSeq')
        if (not isinstance(events, list) or type(head) is not int or head < cursor):
            raise runner.Blocked('SE startup event stream reset or malformed')
        for event in events:
            if (not isinstance(event, dict) or type(event.get('seq')) is not int
                    or event['seq'] != cursor + 1 or event['seq'] > head):
                raise runner.Blocked('SE startup event gap; readiness is unavailable')
            cursor = event['seq']
            data = event.get('data', {})
            if event.get('topic') == 'lifecycle' and isinstance(data, dict):
                name = data.get('event')
                if name in ('newGame', 'preLoadGame', 'postLoadGame'):
                    raise runner.Blocked('Unexpected world transition before SE startup admission')
                if name == 'dataLoaded':
                    loaded = True
            if event.get('topic') == 'menu' and isinstance(data, dict) and data.get('name') == 'Main Menu':
                if type(data.get('opening')) is not bool:
                    raise runner.Blocked('Malformed SE native Main Menu event')
                menu = data['opening']
        sample = {'frame': health.get('frame'), 'cursor': cursor, 'head': head,
                  'dataLoaded': loaded, 'mainMenuOpen': menu}
        if not samples or sample != samples[-1]:
            samples.append(sample)
            session.log('se-native-startup-observation', **sample)
        # A newer stream head is not yet observed evidence. Drain it first.
        if loaded and menu and cursor == head and time.monotonic() <= end:
            session.state['seStartupAdmission'] = {'completed': True, 'game': dict(game),
                'cursor': cursor, 'samples': samples,
                'basis': 'contiguous native dataLoaded and Main Menu; not gameplay readiness'}
            session.save()
            session.log('se-native-startup-admitted', cursor=cursor, gameplayReady=False)
            return
        time.sleep(min(.25, max(0, end - time.monotonic())))
    raise runner.Blocked('SE dataLoaded/Main Menu startup events did not settle before deadline')


def pinned_owned_fixture(session):
    """Verify the declared local save before deferring pre-world task probes."""
    if session.state.get('configuration', {}).get('game_edition') != 'se':
        return False
    fixture = session.state.get('scenario', {}).get('fixture')
    if fixture is None:
        return False
    if (not isinstance(fixture, dict) or not re.fullmatch(r'[A-Za-z0-9_-]+', fixture.get('saveStem', ''))
            or any(not re.fullmatch(r'[0-9a-f]{64}', fixture.get(ext + 'Sha256', '')) for ext in ('ess', 'skse'))
            or session.state.get('configuration', {}).get('allow_owned_save_load') is not True):
        raise ValueError('Declared owned fixture lacks explicit save-load authority or exact source pins')
    directory = Path(session.state.get('ownedSaveDirectory', ''))
    if not directory.is_absolute():
        raise ValueError('Owned fixture save directory unavailable')
    for extension in ('ess', 'skse'):
        path = directory / (fixture['saveStem'] + '.' + extension)
        if (not path.is_file() or path.is_symlink() or
                getattr(path.lstat(), 'st_file_attributes', 0) & 0x400 or
                hashlib.sha256(path.read_bytes()).hexdigest() != fixture[extension + 'Sha256']):
            raise ValueError('Pinned owned fixture changed before startup: ' + extension)
    return True
