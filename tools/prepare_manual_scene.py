"""Freeze an owner-controlled scene program; never launch, install or open audio."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from skyrim_autotest import command_bus, manual_scene


def pin(path):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def prepare(base_config, scene_inputs, output, maximum_seconds=6900):
    if type(maximum_seconds) is not int or not 1 <= maximum_seconds <= 14100:
        raise ValueError('Explicit held window must fit the original outer window minus300seconds')
    output = Path(output).resolve()
    if any((p / '.git').exists() for p in (output, *output.parents)):
        raise ValueError('New output outside Git required')
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads(Path(base_config).read_text(encoding='utf-8-sig'))
    spec = json.loads(Path(scene_inputs).read_text(encoding='utf-8-sig'))
    if config.get('game_edition') != 'se' or not config.get('se_new_game_ui'):
        raise ValueError('Existing native SE New Game configuration required')
    if len(spec['actors']) != 6:
        raise ValueError('Existing exact six-actor scene inputs required')
    config.pop('crash_capture', None)  # Optional debugger is not part of manual play.
    config['runtime'] = str(output / 'runtime')
    settings = config['interactive_session']
    settings.update(maximumSeconds=maximum_seconds, manageCommandEndpoint=True,
                    channelConfig=str(output / 'command-channel.json'))
    channel = {'schemaVersion': 1, 'database': str(output / 'commands.db'),
               'tokenFile': str(output / 'command-token.txt'), 'host': '127.0.0.1', 'port': 8767}
    write(output / 'command-channel.json', channel)
    command_bus.initialize(output / 'command-channel.json')
    write(output / 'runner-config.json', config)
    write(output / 'scene-inputs.json', spec)
    write(output / 'execution-plan.json', {'schemaVersion': 1,
        'checks': [{'name': manual_scene.CASE, 'role': 'subject'}],
        'bounds': {'maximumSeconds': maximum_seconds, 'maximumCommands': 256},
        'fixture': {'cell': 'QASmoke'}, 'scope': 'Owner-controlled scene and observed actions; no whole-mod acceptance'})
    write(output / 'scenario.json', {'schemaVersion': 1, 'name': 'SE owner-controlled manual scene',
        'startMode': 'new-game', 'cell': 'QASmoke', 'steps': [
            {'name': 'Read independent observation capability', 'tool': 'inspect',
             'args': {'kind': 'world_observer', 'action': 'capabilities'}, 'timeout': 30,
             'assert': [{'path': 'domains.references', 'equals': True}]}]})
    controls = output / 'operator-commands'; controls.mkdir()
    observations = output / 'manual-observations'; observations.mkdir()
    source = (ROOT / 'skyrim_autotest/manual_scene.py').read_text(encoding='utf-8')
    source += '\nSPEC = ' + repr(spec) + '\nCONTROLS = ' + repr(str(controls))
    source += '\nOBSERVATIONS = ' + repr(str(observations)) + '\nWINDOW = ' + repr(maximum_seconds)
    source += '''

def run(exchange, emit):
    import json, os
    from pathlib import Path
    directory = Path(OBSERVATIONS)
    if any(directory.iterdir()):
        raise RuntimeError('Manual observations already exist; never replay preparation')
    notices = 0
    def notify(kind, value):
        nonlocal notices
        notices += 1
        name = 'scene-ready.json' if kind == 'scene-ready' else ('%06d-%s.json' % (notices, kind))
        target = directory / name
        temporary = directory / (name + '.tmp')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump({'kind': kind, 'observedAt': time.time(), **value}, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.rename(temporary, target)
    commands = directory_commands(CONTROLS, WINDOW)
    return run_plan(SPEC, exchange, emit, lambda: next(commands), notify)
'''
    with (output / 'sequencer.py').open('x', encoding='utf-8') as stream: stream.write(source)
    manifest = {'schemaVersion': 1, 'kind': 'prepared-owned-manual-scene-not-launched',
        'inputs': [pin(base_config), pin(scene_inputs)], 'source': pin(ROOT / 'skyrim_autotest/manual_scene.py'),
        'files': [pin(output / name) for name in ('runner-config.json', 'scene-inputs.json',
                  'execution-plan.json', 'scenario.json', 'sequencer.py', 'command-channel.json')],
        'maximumWallSeconds': maximum_seconds + 300, 'maximumSeconds': maximum_seconds,
        'requiresOperatorAdmission': True, 'gameStarted': False, 'microphoneStarted': False,
        'optionalDebuggerRemoved': 'Manual session does not require a debugger; no crash-cause claim'}
    write(output / 'preparation-manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base-config', 'scene-inputs', 'output'): parser.add_argument('--' + name, required=True)
    parser.add_argument('--maximum-seconds', type=int, default=6900)
    args = parser.parse_args()
    print(json.dumps(prepare(args.base_config, args.scene_inputs, args.output, args.maximum_seconds), indent=2))
