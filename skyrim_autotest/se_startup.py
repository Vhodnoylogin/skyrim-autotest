"""SE startup admission using listener-side native events, before task requests."""
import time


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
