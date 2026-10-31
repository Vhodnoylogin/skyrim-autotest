"""Pinned passive Root Builder presence for a cold-owned portable SE instance.

No root deployment, plugin execution, cache clearing or third-party patching.
The two native MO2 INI settings are staged only after a durable ordinary backup.
This source candidate requires independent exact-platform qualification.
"""
import configparser
import copy
from pathlib import Path
import re
import time

from . import native, root_builder as rb

MODE = 'se-passive-5.1.1'
PROOF = 'cold-portable-native-ini/1'
REQUIRED = {'migrated': 'true', 'copyfiles': '**', 'linkfiles': '', 'usvfsfiles': ''}
OFF = {'autobuild': 'false', 'redirect': 'false'}
PROCESS_NAMES = {'modorganizer.exe', 'skyrimse.exe', 'skse64_loader.exe', 'skyrimvr.exe', 'sksevr_loader.exe',
                 'vrserver.exe', 'vrmonitor.exe', 'vrcompositor.exe', 'vrstartup.exe', 'vrdashboard.exe',
                 'vrwebhelper.exe', 'vrprismhost.exe'}


def configuration(value):
    fields = {'mode', 'pluginTreeSha256', 'dataTreeSha256', 'loaderSha256', 'mo2ExeSha256', 'settingsProof', 'mutableGameFiles'}
    if type(value) is not dict or set(value) != fields or value.get('mode') != MODE or value.get('settingsProof') != PROOF:
        raise ValueError('Explicit passive SE mode, exact pins and cold native-INI proof required')
    if value['pluginTreeSha256'] != rb.SUPPORTED_PLUGIN_SHA256:
        raise ValueError('Passive mode requires the audited Root Builder 5.1.1 package')
    for name in ('dataTreeSha256', 'loaderSha256', 'mo2ExeSha256'):
        if type(value[name]) is not str or not re.fullmatch('[0-9a-f]{64}', value[name]):
            raise ValueError('Exact lowercase SHA256 pin required: ' + name)
    names = value['mutableGameFiles']
    if (type(names) is not list or len(names) > 32 or
            any(type(name) is not str or not re.fullmatch(r'[A-Za-z0-9_. -]{1,128}\.log', name) or name.startswith('.') for name in names) or
            len({name.casefold() for name in names}) != len(names)):
        raise ValueError('Mutable game outputs require explicit distinct root-level .log filenames')
    return copy.deepcopy(value)


def _ini(path):
    parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=('=',))
    parser.optionxform = str
    parser.read_string(Path(path).read_text(encoding='utf-8-sig'))
    if any(key.casefold().startswith('rootbuilder\\') for key in parser.defaults()):
        raise ValueError('Inherited DEFAULT Root Builder settings are not native Plugins settings')
    if [name for name in parser.sections() if name.casefold() == 'plugins'] != ['Plugins']:
        raise ValueError('One exact native Plugins section is required')
    settings = {}
    for key, value in parser.items('Plugins'):
        if key.casefold().startswith('rootbuilder\\'):
            name = key.split('\\', 1)[1].casefold()
            if name in settings:
                raise ValueError('Case-ambiguous Root Builder INI setting')
            settings[name] = value.strip()
    for key, expected in REQUIRED.items():
        if settings.get(key, '').lower() != expected:
            raise ValueError('Passive mode requires existing audited Root Builder setting: ' + key)
    if settings.get('enabled', 'true').lower() != 'true':
        raise ValueError('Passive proof requires the enabled audited plugin, not a guessed disabled state')
    return settings


def stage_text(text):
    headers = list(re.finditer(r'(?m)^[ \t]*\[([^\]\r\n]+)\][ \t]*\r?$', text))
    matches = [index for index, match in enumerate(headers) if match[1] == 'Plugins']
    if len(matches) != 1:
        raise ValueError('Cannot stage without one exact local Plugins section')
    index = matches[0]
    start = headers[index].end()
    end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
    section = text[start:end]
    for key, wanted in OFF.items():
        pattern = re.compile(r'(?im)^[ \t]*RootBuilder\\' + key + r'[ \t]*=.*$')
        line = 'RootBuilder\\' + key + '=' + wanted
        if pattern.search(section):
            section = pattern.sub(lambda _: line, section)
        else:
            section = '\n' + line + '\n' + section
    return text[:start] + section + text[end:]


def _off(path):
    settings = _ini(path)
    if any(settings.get(key, '').lower() != expected for key, expected in OFF.items()):
        raise ValueError('Root Builder autobuild/redirect are not explicitly false')


def _no_root(value, profile):
    enabled = [line[1:] for line in (Path(profile) / 'modlist.txt').read_text(encoding='utf-8-sig').splitlines() if line.startswith('+')]
    if len(enabled) != len(set(enabled)):
        raise ValueError('Ambiguous duplicate enabled mod')
    for name in enabled:
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('Enabled mod escapes source directory')
        root = rb._safe(Path(value['mods']) / name / 'Root')
        if root.exists():
            raise ValueError('Passive mode forbids enabled Root mod: ' + name)
    overwrite = rb._safe(Path(value['overwrite']) / 'Root')
    if overwrite.exists() and any(overwrite.iterdir()):
        raise ValueError('Passive mode forbids nonempty overwrite Root')
    for item in value.get('staged_plugins', []):
        if item['destination'].replace('\\', '/').split('/', 1)[0].casefold() == 'root':
            raise ValueError('Passive mode forbids staged Root files')


def _inventory(value, policy):
    data = rb._tree(Path(value['mo2']) / 'plugins/data/RootBuilder')
    if not data['exists'] or any(Path(name).name.casefold() == 'builddata.json' for name in data['files']):
        raise ValueError('Passive mode requires existing data and no active BuildData anywhere')
    if rb._digest(data) != policy['dataTreeSha256']:
        raise ValueError('Pinned Root Builder data tree changed')
    game = static_game_tree(value['game'])
    mutable = {name.casefold() for name in policy['mutableGameFiles']}
    for name in list(game['files']):
        if name.casefold() in mutable:
            if name in game['immutableFiles']:
                raise ValueError('Mutable log cannot be hard linked')
            del game['files'][name]
    return data, game


def static_game_tree(anchor):
    """Non-Data root inventory includes hidden names; no VR plugin exclusions."""
    anchor = rb._safe(Path(anchor))
    result = {'path': str(anchor), 'exists': anchor.exists(), 'files': {}, 'directories': [], 'immutableFiles': {}}
    if not anchor.is_dir():
        raise ValueError('Passive static game directory unavailable')
    pending, seen, total = [(anchor, '')], set(), 0
    while pending:
        directory, relative = pending.pop()
        result['directories'].append(relative)
        for path in sorted(directory.iterdir(), key=lambda entry: entry.name.casefold()):
            rb._safe(path)
            if not relative and path.name.casefold() in {'data', 'data files'}:
                continue
            name = relative + '/' + path.name if relative else path.name
            if name.casefold() in seen:
                raise ValueError('Case-ambiguous passive static root path')
            seen.add(name.casefold())
            if path.is_dir():
                pending.append((path, name))
            elif path.is_file():
                facts = rb._hash(path, readonly_hardlink=True)
                result['files'][name] = facts
                total += facts['size']
                stat = path.stat()
                if stat.st_nlink != 1:
                    result['immutableFiles'][name] = {'device': stat.st_dev, 'inode': stat.st_ino,
                                                     'links': stat.st_nlink, **facts}
            else:
                raise ValueError('Special passive static root member')
            if len(seen) > 20000 or total > 2 * 1024 * 1024 * 1024:
                raise ValueError('Passive static root inventory exceeds its bound')
    result['directories'].sort()
    return result


def cold_idle():
    processes = native.processes()
    if type(processes) is not list or not processes:
        raise ValueError('Native process inventory unavailable; cold absence is not proven')
    if any(row['name'].lower() in PROCESS_NAMES for row in processes):
        raise ValueError('Passive Root Builder requires no existing MO2/game/VR process')


def guard_snapshot_target(value, path):
    """No writable snapshot target may alias static roots or another file."""
    path = rb._safe(Path(path))
    if path.exists():
        rb._hash(path)
    game = Path(value['game']).resolve()
    if path.is_relative_to(game):
        relative = path.relative_to(game)
        mutable = {name.casefold() for name in value['root_builder_passive']['mutableGameFiles']}
        if relative.parts[0].casefold() not in {'data', 'data files'} and relative.as_posix().casefold() not in mutable:
            raise ValueError('Static game root cannot be a writable snapshot target')
    return path


def _generic_write_targets(value):
    targets = [Path(value['mo2_ini']), *(Path(path) for path in value.get('extra_files', []))]
    overwrite = Path(value['overwrite'])
    for item in value.get('staged_plugins', []):
        target = overwrite / rb._relative(item['destination'])
        if not target.resolve().is_relative_to(overwrite.resolve()):
            raise ValueError('Staged target escapes overwrite')
        if any(target.resolve().is_relative_to((Path(value['mo2']) / root).resolve())
               for root in ('plugins/data/RootBuilder', 'plugins/rootbuilder')):
            raise ValueError('Staged target overlaps protected Root Builder state')
        targets.append(target)
    return targets


def preflight(value, profile):
    policy = configuration(value.get('root_builder_passive'))
    if (value.get('game_edition') != 'se' or value.get('root_builder') or value.get('root_builder_data') or
            value.get('reuse_test_profile')):
        raise ValueError('Passive Root Builder is separate cold-owned SE-only policy')
    mo2 = rb._safe(Path(value['mo2']))
    ini = rb._safe(Path(value['mo2_ini']))
    portable = rb._safe(mo2 / 'portable.txt')
    if ini != mo2 / 'ModOrganizer.ini' or Path(value['mo2_exe']) != mo2 / 'ModOrganizer.exe' or not portable.is_file():
        raise ValueError('Cold native-INI proof requires this exact portable MO2 instance')
    if rb._hash(Path(value['mo2_exe']))['sha256'] != policy['mo2ExeSha256']:
        raise ValueError('Native portable MO2 executable differs from the pinned settings implementation')
    cold_idle()
    plugin = mo2 / 'plugins/rootbuilder'
    if rb.plugin_fingerprint(plugin) != policy['pluginTreeSha256']:
        raise ValueError('Installed passive Root Builder package changed')
    _ini(ini)
    _no_root(value, profile)
    loader = rb._safe(Path(value['game']) / 'skse64_loader.exe')
    if rb._hash(loader)['sha256'] != policy['loaderSha256']:
        raise ValueError('Physical SE SKSE loader absent/changed; passive mode cannot deploy it')
    extra = {str(Path(path).resolve()).casefold() for path in value.get('extra_files', [])}
    for name in policy['mutableGameFiles']:
        if str((Path(value['game']) / name).resolve()).casefold() not in extra:
            raise ValueError('Every declared mutable game log must use ordinary extra_files snapshots')
    for path in value.get('extra_files', []):
        path = Path(path).resolve()
        if path.is_relative_to((mo2 / 'plugins/data/RootBuilder').resolve()) or path.is_relative_to(plugin.resolve()):
            raise ValueError('Passive Root Builder inventories own their protected snapshots; no generic extra_files there')
        if path.is_relative_to(Path(value['game']).resolve()):
            relative = path.relative_to(Path(value['game']).resolve())
            if relative.parts[0].casefold() not in {'data', 'data files'} and relative.as_posix().casefold() not in {name.casefold() for name in policy['mutableGameFiles']}:
                raise ValueError('Static game root cannot enter generic extra_files restoration in passive mode')
    data, game = _inventory(value, policy)
    for path in _generic_write_targets(value):
        guard_snapshot_target(value, path)
    return {'schemaVersion': 1, 'policy': policy, 'paths': {key: value[key] for key in ('mo2', 'mo2_ini', 'mo2_exe', 'mods', 'overwrite', 'game')},
            'profile': str(Path(profile)), 'profileModlistSha256': rb._hash(Path(profile) / 'modlist.txt')['sha256'],
            'iniPreimage': rb._hash(ini), 'portablePin': rb._hash(portable), 'data': data, 'game': game}


def before_setup_writes(session, contract):
    if session.state.get('rootBuilderPassive') or session.state.get('borrowedMO2'):
        raise ValueError('Passive write barrier already registered or session is borrowed')
    if preflight(session.state['configuration'], contract['profile']) != contract:
        raise ValueError('Passive policy or write-target identity changed before setup writes')
    session.state['rootBuilderPassive'] = {'runId': session.state['id'], 'contract': copy.deepcopy(contract),
        'contractSha256': rb._digest(contract), 'phase': 'write-barrier', 'snapshotPaths': []}
    session.state['rootBuilderPassiveWriteBarrier'] = {'contractSha256': rb._digest(contract)}
    session.save()


def _record(session):
    record = session.state.get('rootBuilderPassive')
    if (type(record) is not dict or record.get('runId') != session.state.get('id') or
            record.get('contractSha256') != rb._digest(record.get('contract'))):
        raise ValueError('Passive Root Builder journal/run identity changed')
    return record, record['contract']


def prepare(session, contract):
    if session.state.get('borrowedMO2'):
        raise ValueError('Passive preparation requires a new cold-owned session')
    existing = session.state.get('rootBuilderPassive')
    if existing:
        unused, recorded = _record(session)
        if existing.get('phase') != 'write-barrier' or recorded != contract:
            raise ValueError('Passive preparation intent already consumed or changed')
    cold_idle()
    value = session.state['configuration']
    if preflight(value, contract['profile']) != contract:
        raise ValueError('Passive preflight identity drift before preparation')
    ini = Path(contract['paths']['mo2_ini'])
    snapshots = [row for row in session.state['snapshots'] if Path(row['path']) == ini]
    if len(snapshots) != 1 or snapshots[0].get('sha256') != contract['iniPreimage']['sha256']:
        raise ValueError('Ordinary durable original MO2 INI snapshot required before passive staging')
    record = existing or {'runId': session.state['id'], 'contract': copy.deepcopy(contract), 'contractSha256': rb._digest(contract),
                          'snapshotPaths': []}
    record['phase'] = 'intent'
    session.state['rootBuilderPassive'] = record
    session.save()
    for name in sorted(contract['data']['files']):
        path = Path(contract['data']['path']) / name
        session.snapshot(path)
        record['snapshotPaths'].append(str(path.resolve()))
        session.save()
    session.write(ini, stage_text(ini.read_text(encoding='utf-8-sig')))
    _off(ini)
    record.update(phase='prepared', stagedIniSha256=rb._hash(ini)['sha256'])
    session.save()


def _unchanged(session, contract):
    value = session.state['configuration']
    if rb.plugin_fingerprint(Path(value['mo2']) / 'plugins/rootbuilder') != contract['policy']['pluginTreeSha256']:
        raise rb.RootBuilderUncertainty('Passive Root Builder package drift')
    if rb._hash(value['mo2_exe'])['sha256'] != contract['policy']['mo2ExeSha256']:
        raise rb.RootBuilderUncertainty('Passive native MO2 executable drift')
    data, game = _inventory(value, contract['policy'])
    if data != contract['data'] or game != contract['game']:
        raise rb.RootBuilderUncertainty('Passive Root Builder data/static game-root drift; no automatic root repair')
    if rb._hash(Path(value['mo2']) / 'portable.txt') != contract['portablePin']:
        raise rb.RootBuilderUncertainty('Portable MO2 identity changed')


def before_launch(session):
    record, contract = _record(session)
    cold_idle()
    _unchanged(session, contract)
    _no_root(session.state['configuration'], session.state['testProfile'])
    _off(contract['paths']['mo2_ini'])
    if record['phase'] != 'prepared':
        raise ValueError('Passive cold-start proof already consumed')
    record.update(phase='cold-start-proof', coldStartProof={'iniSha256': rb._hash(contract['paths']['mo2_ini'])['sha256'],
                  'minimumProcessBirth': 116444736000000000 + time.time_ns() // 100, 'method': PROOF})
    session.save()


def verify_boot(session, bridge):
    record, contract = _record(session)
    proof = record.get('coldStartProof', {})
    owned = [row['identity'] for row in session.state.get('owned', []) if row.get('role') == 'mo2']
    if (record['phase'] != 'cold-start-proof' or len(owned) != 1 or native.identity(owned[0]['pid']) != owned[0] or
            Path(owned[0]['path']) != Path(contract['paths']['mo2_exe']) or type(owned[0]['birth']) is not int or owned[0]['birth'] < proof['minimumProcessBirth'] or
            bridge.get('mo2Pid') != owned[0]['pid'] or type(bridge.get('serverBootId')) is not str or not bridge['serverBootId'] or
            type(bridge.get('instanceId')) is not str or not bridge['instanceId'] or
            Path(bridge.get('profilesPath', '')) != Path(session.state['configuration']['profiles'])):
        raise ValueError('Passive proof needs exact newly cold-started owned portable MO2 Bridge instance')
    _off(contract['paths']['mo2_ini'])
    if rb._hash(contract['paths']['mo2_ini'])['sha256'] != proof['iniSha256']:
        raise ValueError('Cold-staged native MO2 INI changed before SKSE launch')
    _unchanged(session, contract)
    _no_root(session.state['configuration'], session.state['testProfile'])
    record.update(phase='verified-before-game', effectiveSettingsProof={**proof, 'mo2': owned[0], 'bridge': copy.deepcopy(bridge),
                  'basis': 'Pinned portable native MO2 INI existed before process birth; unchanged after exact owned Bridge boot; audited plugin reads organizer.pluginSetting'})
    session.save()


def restore(session):
    record, contract = _record(session)
    cold_idle()
    _unchanged(session, contract)
    if rb._hash(contract['paths']['mo2_ini']) != contract['iniPreimage']:
        raise rb.RootBuilderUncertainty('Ordinary restoration did not restore the original MO2 INI bytes')
    record['phase'] = 'restored-unchanged'
    session.save()


def restore_precheck(session):
    """Reject alias/drift hazards before the generic writer restores even logs."""
    unused, contract = _record(session)
    cold_idle()
    _unchanged(session, contract)
    targets = [Path(contract['paths']['mo2_ini'])]
    targets.extend(Path(contract['paths']['game']) / name for name in contract['policy']['mutableGameFiles'])
    for target in targets:
        rb._safe(target)
        if target.exists():
            # No readonly-hardlink exception: ordinary recovery would write it.
            rb._hash(target)
    protected = {str(Path(path).resolve()).casefold() for path in session.state['rootBuilderPassive']['snapshotPaths']}
    for snapshot in session.state.get('snapshots', []):
        if str(Path(snapshot['path']).resolve()).casefold() not in protected:
            guard_snapshot_target(session.state['configuration'], snapshot['path'])
