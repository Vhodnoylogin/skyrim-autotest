"""Explicit game targets; VR runtime resources never belong to a flat-game run."""
from pathlib import Path

TARGETS = {
    'vr': {'executable': 'SkyrimVR.exe', 'loader': 'sksevr_loader.exe',
           'bridgeGame': 'SkyrimVR', 'runtimeDirectory': 'vr'},
    'se': {'executable': 'SkyrimSE.exe', 'loader': 'skse64_loader.exe',
           'bridgeGame': 'SkyrimSE', 'runtimeDirectory': 'se'},
}


def target(configuration):
    edition = configuration.get('game_edition', 'vr')
    if edition not in TARGETS:
        raise ValueError('game_edition must be vr or se')
    return dict(TARGETS[edition], edition=edition)


def runtime_candidates(configuration):
    """Explicit deployment discovery takes precedence over conventional paths."""
    files = configuration.get('devbench_runtime_files')
    if files:
        return [Path(p) for p in files]
    import os
    return [Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'devbench' /
            target(configuration)['runtimeDirectory'] / 'runtime.json',
            Path(configuration['overwrite']) / 'SKSE/Plugins/devbench/runtime.json']


def validate_mo2_loader(text, configuration):
    """Check the closed-manager launch configuration; never guess an entry name."""
    import configparser
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(text)
    entries = parser['customExecutables'] if parser.has_section('customExecutables') else {}
    matches = [key.split('\\', 1)[0] for key, value in entries.items()
               if key.endswith('\\title') and value == 'SKSE']
    if len(matches) != 1:
        raise ValueError('Exactly one registered SKSE executable is required')
    prefix = matches[0] + '\\'
    binary = Path(entries.get(prefix + 'binary', '')).resolve()
    cwd = Path(entries.get(prefix + 'workingdirectory', '')).resolve()
    game = Path(configuration['game']).resolve()
    if (binary != game / target(configuration)['loader'] or cwd != game
            or entries.get(prefix + 'arguments', '').strip()):
        raise ValueError('Registered SKSE must use this edition loader, exact game directory and no hidden arguments')
    return {'binary': str(binary), 'workingDirectory': str(cwd), 'arguments': ''}


def validate_scenario(configuration, scenario, driver_backend, input_backend):
    edition = target(configuration)['edition']
    steps = [*scenario.get('steps', []), *scenario.get('postSteps', [])]
    if any(step.get('tool') == 'native14' for step in steps):
        if edition != 'vr':
            raise ValueError('Native14 scenario reads require the VR target')
        from .native14_live import configuration as native14_policy
        native14_policy(configuration.get('native14_live'))
    if edition != 'se':
        return
    if (scenario.get('kind') in ('vr-hand-probe', 'vr-mobility-probe') or
            scenario.get('allowBackgroundVR') or scenario.get('activationHandStartupFixture') or
            any(s.get('tool') == 'driver' for s in scenario.get('steps', []))):
        raise ValueError('VR controls/probes cannot run against Skyrim SE')
    if driver_backend != 'none' or input_backend != 'devbench':
        raise ValueError('Skyrim SE requires driver backend none and DevBench input')
    if any(s.get('tool') == 'platform' and s.get('args', {}).get('operation') == 'controller.perform'
           for s in scenario.get('steps', [])):
        raise ValueError('Physical VR controller operations cannot run against Skyrim SE')
    if scenario.get('startMode') == 'new-game':
        raise ValueError('SE New Game UI is not qualified; use a declared cell or pinned save fixture')
