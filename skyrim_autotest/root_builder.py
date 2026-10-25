"""Narrow, hash-pinned Root Builder 5.1.1 copy-mode lifecycle for owned VR runs.

Root Builder alone deploys files through MO2. This module plans, journals,
verifies and restores its explicitly bounded managed view; it executes no plugin.
"""
import configparser
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time


SUPPORTED_PLUGIN_SHA256 = 'b1c2ae18837b625016a125d7e8897d6f7b73016bef6d64ddd398c7643b898e9f'
_EXCLUDED = {'data', 'data files', 'saves', 'morrowind.ini'}
_BUNDLE = {'sksevr_loader.exe', 'sksevr_1_4_15.dll', 'sksevr_steam_loader.dll'}
_DISABLED = {'OpenComposite Unleashed for Skyrim VR', 'OpenComposite Unleashed for Skyrim VR - No Grip Ready Weapon'}


class RootBuilderError(ValueError):
    pass


class RootBuilderUncertainty(RootBuilderError):
    """A shared immutable file changed; its aliases cannot be repaired safely."""


def _fail(message):
    raise RootBuilderError(message)


def _canonical(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def _safe(path):
    path = Path(path)
    if not path.is_absolute():
        _fail('Root Builder paths must be explicit and absolute')
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                _fail('Root Builder scope contains a link/reparse point: ' + str(part))
    if _canonical(path.resolve()) != _canonical(path):
        _fail('Root Builder path resolves outside its explicit identity')
    return path


def _relative(value):
    if type(value) is not str or not value or len(value) > 1024 or '\0' in value:
        _fail('Invalid Root Builder relative path')
    parts = re.split(r'[/\\]', value)
    if PureWindowsPath(value).drive or any(part in ('', '.', '..') or ':' in part for part in parts):
        _fail('Root Builder relative path escapes its anchor')
    return '/'.join(parts)


def _target(anchor, relative=''):
    anchor = _safe(anchor)
    target = _safe(anchor / _relative(relative)) if relative else anchor
    if not target.resolve().is_relative_to(anchor.resolve()):
        _fail('Root Builder target escapes its checked anchor')
    return target


def _excluded(relative):
    # Python's recursive glob used by this package does not include dot names.
    return (relative.split('/', 1)[0].casefold() in _EXCLUDED or
            any(part.startswith('.') for part in relative.split('/')))


def _hash(path, *, readonly_hardlink=False):
    path = _safe(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink != 1 and not readonly_hardlink:
            _fail('Root Builder mutable scope contains an unexpected hard-linked file: ' + str(path))
        if not stat.S_ISREG(before.st_mode) or before.st_size > 256 * 1024 * 1024:
            _fail('Root Builder file is not a bounded regular file')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        after = os.fstat(stream.fileno())
    stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_nlink)
    if stamp(before) != stamp(after) or stamp(before) != stamp(path.stat()):
        _fail('Root Builder input changed while hashing')
    return {'sha256': digest.hexdigest(), 'size': before.st_size}


def _directories(anchor, *, reject_hardlinks=False):
    """Directory/link inventory only, including excluded Data; never hash BSAs.

    The audited plugin's empty-folder cleanup traverses the entire game tree.
    Inventory those directories so original empty folders can be restored too.
    """
    anchor = _safe(anchor)
    if not anchor.exists():
        return []
    result, pending, entries = [], [(anchor, '')], 0
    while pending:
        directory, relative = pending.pop()
        result.append(relative)
        for child in directory.iterdir():
            _safe(child)
            if reject_hardlinks and child.is_file() and child.stat().st_nlink != 1:
                _fail('Root Builder mutable source scope contains an unexpected hard-linked file: ' + str(child))
            entries += 1
            if entries > 200000:
                _fail('Root Builder directory-only traversal exceeds its bound')
            if child.is_dir():
                pending.append((child, relative + '/' + child.name if relative else child.name))
            elif not child.is_file():
                _fail('Special game/root-source member is unsupported')
    return sorted(result)


def _tree(anchor, *, view=False, plugin=False, data=False, game=False):
    anchor = _safe(anchor)
    result = {'path': str(anchor), 'exists': anchor.exists(), 'files': {}, 'directories': [], 'immutableFiles': {}}
    if not anchor.exists():
        return result
    if not anchor.is_dir():
        _fail('Root Builder anchor must be a directory')
    if view:
        _directories(anchor, reject_hardlinks=not game)  # Also inspect excluded folders, without hashing BSAs.
    total = 0
    seen = set()
    pending = [(anchor, '')]
    while pending:
        directory, relative = pending.pop()
        result['directories'].append(relative)
        for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            rel = relative + '/' + child.name if relative else child.name
            if plugin and (child.name == '__pycache__' or child.suffix == '.pyc'):
                continue
            if view and _excluded(rel):
                continue
            if data and rel.lower().startswith('backup/') and _excluded(rel.split('/', 1)[1]):
                _fail('Unsupported excluded game-data content in Root Builder backup')
            _safe(child)
            identity = rel.casefold()
            if identity in seen:
                _fail('Case-ambiguous Root Builder tree membership')
            seen.add(identity)
            if child.is_dir():
                pending.append((child, rel))
            elif child.is_file():
                details = _hash(child, readonly_hardlink=game)
                info = child.stat()
                if info.st_nlink != 1:
                    result['immutableFiles'][rel] = {'sha256': details['sha256'], 'size': details['size'],
                        'device': info.st_dev, 'inode': info.st_ino, 'links': info.st_nlink,
                        'mode': info.st_mode, 'attributes': getattr(info, 'st_file_attributes', 0)}
                total += details['size']
                result['files'][rel] = details
            else:
                _fail('Unsupported special Root Builder filesystem member')
            if len(seen) > 20000 or total > 2 * 1024 * 1024 * 1024:
                _fail('Root Builder managed view exceeds its bounded inventory')
    result['directories'].sort()
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def plugin_fingerprint(directory):
    """Read-only source/package fingerprint; generated Python bytecode is excluded."""
    tree = _tree(directory, plugin=True)
    if not tree['exists'] or not tree['files']:
        _fail('Installed Root Builder package is unavailable')
    return _digest({'files': tree['files'], 'directories': tree['directories']})


def configuration(value):
    if type(value) is not dict or set(value) != {'mode', 'pluginTreeSha256', 'loaderMod', 'bundleSha256'}:
        _fail('Root Builder requires mode, pluginTreeSha256, loaderMod and bundleSha256')
    if value['mode'] != 'copy-5.1.1' or value['pluginTreeSha256'] != SUPPORTED_PLUGIN_SHA256:
        _fail('Only the audited pinned Root Builder 5.1.1 copy package is supported')
    name = value['loaderMod']
    if type(name) is not str or not name or len(name) > 200 or name in ('.', '..') or any(ch in name for ch in '/\\\0'):
        _fail('Root Builder loaderMod must name one mod directory')
    bundle = value['bundleSha256']
    if (type(bundle) is not dict or set(bundle) != _BUNDLE or
            any(type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None for value in bundle.values())):
        _fail('The exact three-file SKSEVR root bundle must have lowercase SHA256 pins')
    return copy.deepcopy(value)


def _json(path):
    path = _safe(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        _fail('Root Builder metadata is oversized')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail('Duplicate Root Builder metadata key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda value: _fail('Nonfinite Root Builder metadata'))


def _cache(path):
    data = _json(path)
    if type(data) is not dict or len(data) > 20000:
        _fail('Root Builder game-cache layout is unsupported')
    for key, record in data.items():
        if type(record) is not dict or set(record) != {'Relative', 'Hash', 'Modified', 'Size'}:
            _fail('Unsupported Root Builder game-cache record')
        relative = _relative(record['Relative'])
        if _excluded(relative) or key.replace('\\', '/').casefold() != relative.casefold():
            _fail('Root Builder game cache includes excluded or ambiguous paths')
        if (type(record['Hash']) is not str or len(record['Hash']) > 128 or
                type(record['Modified']) not in (int, float) or not math.isfinite(record['Modified']) or
                type(record['Size']) is not int or record['Size'] < 0):
            _fail('Malformed Root Builder game-cache facts')
    return data


def preflight(value, profile_dir):
    """Read-only complete plan before any setup mutation or owned MO2 launch."""
    policy = configuration(value.get('root_builder'))
    if value.get('game_edition', 'vr') != 'vr' or value.get('reuse_test_profile'):
        _fail('Explicit Root Builder mode supports only cold-owned Skyrim VR MO2')
    paths = {key: _safe(value[key]) for key in ('game', 'mo2', 'mo2_ini', 'mo2_exe', 'mods', 'overwrite', 'profiles', 'root_builder_data')}
    profile = _safe(profile_dir)
    if profile.parent != paths['profiles'] or not profile.is_dir():
        _fail('Root Builder source profile must belong to the configured profiles directory')
    if (paths['mo2_exe'] != paths['mo2'] / 'ModOrganizer.exe' or paths['mo2_ini'] != paths['mo2'] / 'ModOrganizer.ini' or
            not paths['mo2_exe'].is_file() or not (paths['game'] / 'SkyrimVR.exe').is_file()):
        _fail('Only the configured portable MO2 and actual SkyrimVR executable are supported')
    plugin = paths['mo2'] / 'plugins/rootbuilder'
    if plugin_fingerprint(plugin) != policy['pluginTreeSha256']:
        _fail('Installed Root Builder package fingerprint changed')
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.read_string(paths['mo2_ini'].read_text(encoding='utf-8-sig'))
    entries = ini['customExecutables'] if ini.has_section('customExecutables') else {}
    prefixes = [key.split('\\', 1)[0] + '\\' for key, text in entries.items() if key.endswith('\\title') and text == 'SKSE']
    if len(prefixes) != 1:
        _fail('Exactly one registered SKSE entry is required')
    prefix = prefixes[0]
    loader = paths['game'] / 'sksevr_loader.exe'
    if (_canonical(entries.get(prefix + 'binary', '')) != _canonical(loader) or
            _canonical(entries.get(prefix + 'workingdirectory', '')) != _canonical(paths['game']) or
            entries.get(prefix + 'arguments', '').strip()):
        _fail('Registered SKSE must target the game-root loader/cwd with no arguments')
    settings = ini['Plugins'] if ini.has_section('Plugins') else {}
    required = {'copyfiles': '**', 'linkfiles': '', 'usvfsfiles': '', 'autobuild': 'true',
                'hash': 'true', 'backup': 'true', 'cache': 'true', 'migrated': 'true'}
    for key, expected in required.items():
        if settings.get('rootbuilder\\' + key, '').strip().lower() != expected:
            _fail('Unsupported or missing Root Builder setting: ' + key)
    if settings.get('rootbuilder\\enabled', 'true').lower() != 'true':
        _fail('Root Builder is disabled')
    exclusions = settings.get('rootbuilder\\exclusions', '').strip('"')
    if {part.strip().casefold() for part in exclusions.split(',')} != _EXCLUDED:
        _fail('Root Builder exclusions differ from the supported managed view')
    safe_game = str(paths['game']).replace(' ', '_').replace('.', '_')
    for character in '<>:|*\\/?"':
        safe_game = safe_game.replace(character, '')
    expected_data = paths['mo2'] / 'plugins/data/RootBuilder' / safe_game / '1_4_15_0'
    if paths['root_builder_data'] != expected_data or not expected_data.is_dir():
        _fail('root_builder_data must identify this exact Skyrim VR game/version directory')
    if (expected_data / 'BuildData.json').exists() or not (expected_data / 'Backup').is_dir():
        _fail('Root Builder must have a clean inactive build and its existing Backup directory')
    cache = _cache(expected_data / 'GameData.json')
    source_text = (profile / 'modlist.txt').read_text(encoding='utf-8-sig')
    enabled = [line[1:] for line in source_text.splitlines() if line.startswith('+')]
    if len(enabled) != len(set(enabled)) or policy['loaderMod'] not in enabled:
        _fail('The named SKSEVR source mod must be enabled exactly once')
    effective_text = '\n'.join('-' + line[1:] if line.startswith('+') and line[1:] in _DISABLED else line
                               for line in source_text.splitlines()) + '\n'
    active = [name for name in enabled if name not in _DISABLED]
    trees, roots = [], {}
    for mod in sorted(paths['mods'].iterdir()):
        _safe(mod)
        root = mod / 'Root'
        if root.exists():
            tree = _tree(root, view=True)
            roots[mod.name] = tree
            trees.append(tree)
    overwrite = _tree(paths['overwrite'] / 'Root', view=True)
    game_tree = _tree(paths['game'], view=True, game=True)
    trees.extend([overwrite, game_tree, _tree(expected_data, data=True)])
    winners = {}
    for name in reversed(active):  # modlist.txt starts with the highest-priority mod.
        if name in roots:
            for relative, facts in roots[name]['files'].items():
                winners[relative.casefold()] = {'source': str(Path(roots[name]['path']) / relative), 'relative': relative, **facts}
    for relative, facts in overwrite['files'].items():
        winners[relative.casefold()] = {'source': str(Path(overwrite['path']) / relative), 'relative': relative, **facts}
    for item in value.get('staged_plugins', []):
        destination = _relative(item['destination'])
        if destination.split('/', 1)[0].casefold() == 'root':
            if '/' not in destination:
                _fail('A staged Root destination must identify a file')
            relative = _relative(destination.split('/', 1)[1])
            if _excluded(relative) or _hash(item['source'])['sha256'] != item['sha256']:
                _fail('Invalid staged overwrite Root input')
            winners[relative.casefold()] = {'source': str(paths['overwrite'] / 'Root' / relative),
                                           'relative': relative, **_hash(item['source'])}
    root = roots.get(policy['loaderMod'])
    if root is None:
        _fail('Enabled SKSEVR source Root directory is absent')
    for relative, digest in policy['bundleSha256'].items():
        contenders = [str(Path(tree['path']) / rel) for name, tree in roots.items() if name in active
                      for rel in tree['files'] if rel.casefold() == relative]
        if (len(contenders) != 1 or relative not in winners or
                _canonical(winners[relative]['source']) != _canonical(Path(root['path']) / relative) or
                winners[relative]['sha256'] != digest):
            _fail('SKSEVR bundle is missing, shadowed, ambiguous or changed: ' + relative)
    possible_writes = {relative.casefold() for tree in roots.values() for relative in tree['files']}
    possible_writes.update(relative.casefold() for relative in overwrite['files'])
    possible_writes.update(winners)
    possible_writes.add('openvr_api.dll')  # The existing VR setup explicitly writes this file.
    extra = {_canonical(path) for path in value.get('extra_files', [])}
    cached = {_relative(record['Relative']).casefold() for record in cache.values()}
    for relative, immutable in game_tree['immutableFiles'].items():
        if (relative.casefold() != 'skyrimvr.exe' or relative.casefold() not in cached or
                relative.casefold() in possible_writes or _canonical(paths['game'] / relative) in extra or
                not immutable['mode'] & stat.S_IWRITE or immutable['attributes'] & 1):
            _fail('Hard-linked game file is not the reviewed immutable non-write executable case')
    anchors = [Path(tree['path']).resolve() for tree in trees]
    if any(a != b and (a.is_relative_to(b) or b.is_relative_to(a)) for index, a in enumerate(anchors) for b in anchors[index + 1:]):
        _fail('Root Builder restore anchors overlap')
    return {'schemaVersion': 1, 'mode': policy['mode'], 'policy': policy,
            'paths': {key: str(path) for key, path in paths.items()}, 'plugin': str(plugin),
            'profile': str(profile), 'effectiveModlistSha256': hashlib.sha256(effective_text.encode()).hexdigest(),
            'disabledMods': sorted(set(enabled).intersection(_DISABLED)), 'winners': winners, 'trees': trees,
            'cachePaths': [_relative(record['Relative']) for record in cache.values()],
            'gameDirectories': _directories(paths['game']),
            'versionManifest': str(expected_data.parent.parent / 'VersionManifest.json'),
            'versionManifestFacts': (_hash(expected_data.parent.parent / 'VersionManifest.json')
                                     if (expected_data.parent.parent / 'VersionManifest.json').exists() else None)}


def _record(session):
    record = session.state.get('rootBuilder')
    if (type(record) is not dict or record.get('runId') != session.state.get('id') or
            record.get('contractSha256') != _digest(record.get('contract'))):
        _fail('Root Builder journal/run identity is unavailable or changed')
    return record, record['contract']


def _snapshot_plan(contract):
    result = {_canonical(Path(tree['path']) / relative): (str(Path(tree['path']) / relative), facts)
              for tree in contract['trees'] for relative, facts in tree['files'].items() if relative not in tree['immutableFiles']}
    additional = [str(Path(contract['paths']['game']) / winner['relative']) for winner in contract['winners'].values()]
    additional += [str(Path(contract['paths']['root_builder_data']) / 'Backup' / relative) for relative in contract['cachePaths']]
    additional.append(str(Path(contract['paths']['root_builder_data']) / 'BuildData.json'))
    for path in additional:
        result.setdefault(_canonical(path), (path, None))
    result[_canonical(contract['versionManifest'])] = (contract['versionManifest'], contract['versionManifestFacts'])
    return result


def prepare(session, contract):
    if session.state.get('borrowedMO2') or session.state.get('rootBuilder'):
        _fail('Root Builder prepare requires a fresh cold-owned session')
    directory = _safe(session.dir)
    if any((parent / '.git').exists() for parent in (directory, *directory.parents)):
        _fail('Root Builder journals/backups must remain outside Git')
    for tree in contract['trees']:
        if directory.resolve().is_relative_to(Path(tree['path']).resolve()):
            _fail('Root Builder journal overlaps a managed restore anchor')
        current = _tree(tree['path'], view=Path(tree['path']) != Path(contract['paths']['root_builder_data']),
                        data=Path(tree['path']) == Path(contract['paths']['root_builder_data']),
                        game=Path(tree['path']) == Path(contract['paths']['game']))
        if current != tree:
            _fail('Root Builder managed view changed after preflight')
    record = {'runId': session.state['id'], 'contract': copy.deepcopy(contract), 'contractSha256': _digest(contract),
              'phase': 'preparing', 'preparationComplete': False, 'snapshotPaths': [], 'restoreIntent': None}
    session.state['rootBuilder'] = record
    session.save()
    for path, expected in sorted(_snapshot_plan(contract).values()):
        if (_hash(path) if Path(path).is_file() else None) != expected:
            _fail('Root Builder snapshot preimage changed after planning')
        session.snapshot(_safe(path))
        entry = next(item for item in session.state['snapshots'] if _canonical(item['path']) == _canonical(path))
        if (entry.get('exists') is not (expected is not None) or
                expected is not None and entry.get('sha256') != expected['sha256']):
            _fail('Existing Root Builder snapshot has a different preimage')
        record['snapshotPaths'].append(str(Path(path).resolve()))
        session.save()
    record['phase'] = 'prepared'
    record['preparationComplete'] = True
    session.save()


def record_launch(session, launch, ping):
    from . import native
    record, contract = _record(session)
    process = launch.get('process', {})
    expected = Path(contract['paths']['game']) / 'sksevr_loader.exe'
    owned_mo2 = [row['identity'] for row in session.state.get('owned', []) if row.get('role') == 'mo2']
    matching = [identity for identity in owned_mo2 if identity['pid'] == ping.get('mo2Pid') and
                _canonical(identity['path']) == _canonical(contract['paths']['mo2_exe']) and native.identity(identity['pid']) == identity]
    if (record['phase'] != 'prepared' or record.get('loaderReceipt') or len(matching) != 1 or
            type(ping.get('serverBootId')) is not str or not 1 <= len(ping['serverBootId']) <= 128 or
            launch.get('serverBootId') != ping['serverBootId'] or type(launch.get('pid')) is not int or
            launch.get('started') is not True or launch.get('applied') is not True or launch.get('processHandleOwned') is not True or
            process.get('role') != 'loader' or type(process.get('pid')) is not int or process['pid'] <= 0 or
            process['pid'] != launch.get('pid') or type(process.get('creationTime')) is not int or not 0 < process['creationTime'] < 1 << 64 or
            _canonical(process.get('path', '')) != _canonical(expected)):
        _fail('No exact handle-backed loader receipt from this owned MO2 Bridge boot')
    identity = {'pid': process['pid'], 'birth': process['creationTime'], 'path': process['path']}
    actual = native.identity(identity['pid'])
    if actual is not None and actual != identity:
        _fail('Loader PID was reused or its identity differs from the retained-handle receipt')
    exit_time = process.get('exitTime')
    if exit_time is not None and (type(exit_time) is not int or not identity['birth'] <= exit_time < 1 << 64):
        _fail('Malformed retained loader exit time')
    if not any(row.get('identity') == identity for row in session.state.get('owned', [])):
        session.state.setdefault('owned', []).append({'role': 'loader', 'identity': identity})
    record['loaderReceipt'] = {'serverBootId': ping['serverBootId'], 'mo2': matching[0], 'identity': identity,
                               'processHandleOwned': True, 'exitTime': exit_time, 'key': launch.get('key')}
    session.save()


def verify_started(session):
    from . import native
    record, contract = _record(session)
    game = session.state.get('game')
    if (record['phase'] != 'prepared' or not record.get('loaderReceipt') or not game or
            native.identity(game['pid']) != game or not any(row.get('identity') == game for row in session.state.get('owned', [])) or
            _canonical(game['path']) != _canonical(Path(contract['paths']['game']) / 'SkyrimVR.exe')):
        _fail('Root Builder start needs the exact owned loader receipt and live owned game')
    if plugin_fingerprint(contract['plugin']) != contract['policy']['pluginTreeSha256']:
        _fail('Root Builder package changed during launch')
    _immutable_check(contract)
    profile = _safe(session.state['testProfile'])
    effective_text = (profile / 'modlist.txt').read_text(encoding='utf-8-sig')
    if hashlib.sha256(effective_text.encode()).hexdigest() != contract['effectiveModlistSha256']:
        _fail('Actual copied profile differs from the declared OpenComposite-disabled plan')
    manifest = _json(Path(contract['paths']['root_builder_data']) / 'BuildData.json')
    if type(manifest) is not dict or set(manifest) != {'Copy', 'Link', 'USVFS'} or manifest['Link'] or manifest['USVFS']:
        _fail('Root Builder did not produce the supported copy-only build manifest')
    copied = manifest['Copy']
    if (type(copied) is not dict or len(copied) != len(contract['winners']) or
            set(key.replace('\\', '/').casefold() for key in copied) != set(contract['winners'])):
        _fail('Actual Root Builder winning-source manifest differs from the pinned plan')
    for key, item in copied.items():
        if (type(item) is not dict or set(item) != {'Source', 'Relative', 'Hash'} or
                type(item['Hash']) is not str or re.fullmatch('[0-9a-f]{32}', item['Hash']) is None):
            _fail('Unsupported Root Builder build record')
        relative = _relative(item['Relative'])
        expected = contract['winners'].get(relative.casefold())
        if (expected is None or key.replace('\\', '/').casefold() != relative.casefold() or
                _canonical(item['Source']) != _canonical(expected['source']) or
                _hash(item['Source'])['sha256'] != expected['sha256']):
            _fail('Root Builder manifest source escaped or changed')
        _target(contract['paths']['game'], relative)
    deployed = {}
    for relative, digest in contract['policy']['bundleSha256'].items():
        target = _target(contract['paths']['game'], relative)
        if _hash(target)['sha256'] != digest:
            _fail('Deployed SKSEVR root bundle does not match its source pin')
        deployed[relative] = digest
    record.update(phase='started', startEvidence={'game': copy.deepcopy(game), 'bundleSha256': deployed,
                  'buildManifestSha256': _hash(Path(contract['paths']['root_builder_data']) / 'BuildData.json')['sha256']})
    session.save()


def _validate_restore_scope(session, record, contract):
    plan = _snapshot_plan(contract)
    registered = record['snapshotPaths']
    if (type(registered) is not list or len(registered) != len(set(map(_canonical, registered))) or
            any(_canonical(path) not in plan for path in registered) or
            record.get('preparationComplete') is True and set(map(_canonical, registered)) != set(plan)):
        _fail('Root Builder snapshot paths escaped or differ from the prepared scope')
    snapshots = {_canonical(entry['path']): entry for entry in session.state['snapshots']}
    for path in registered:
        entry = snapshots.get(_canonical(path))
        expected = plan[_canonical(path)][1]
        if (entry is None or entry.get('exists') is not (expected is not None) or
                expected is not None and entry.get('sha256') != expected['sha256']):
            _fail('Root Builder snapshot preimage or ownership changed')
    intent = record['restoreIntent']
    anchors = {_canonical(tree['path']): tree for tree in contract['trees']}
    if type(intent) is not dict or set(intent) != {'createdFiles', 'createdDirectories', 'removedFiles', 'removedDirectories'}:
        _fail('Malformed Root Builder recovery intent')
    for key in intent:
        if type(intent[key]) is not list or len(intent[key]) > 200000:
            _fail('Unbounded Root Builder recovery intent')
    for item in intent['createdFiles']:
        if type(item) is not dict or set(item) != {'anchor', 'relative', 'sha256', 'size'}:
            _fail('Malformed owned-created Root Builder file record')
        tree = anchors.get(_canonical(item['anchor']))
        relative = _relative(item['relative'])
        if (tree is None or relative in tree['files'] or relative in tree['directories'] or
                Path(tree['path']) != Path(contract['paths']['root_builder_data']) and _excluded(relative)):
            _fail('Created-file recovery record escaped its original absent managed scope')
    for item in intent['createdDirectories']:
        if type(item) is not dict or set(item) != {'anchor', 'relative'}:
            _fail('Malformed owned-created Root Builder directory record')
        tree = anchors.get(_canonical(item['anchor']))
        relative = _relative(item['relative']) if item['relative'] else ''
        original = (contract['gameDirectories'] if tree and tree['path'] == contract['paths']['game'] else
                    tree['directories'] if tree else [])
        if tree is None or relative in original or relative in tree['files']:
            _fail('Created-directory recovery record escaped its original absent scope')
    files = {str(_target(item['anchor'], item['relative'])) for item in intent['createdFiles']}
    directories = {str(_target(item['anchor'], item['relative'])) for item in intent['createdDirectories']}
    if (any(path not in files for path in intent['removedFiles']) or
            any(path not in directories for path in intent['removedDirectories'])):
        _fail('Recovery completion markers escaped the owned-created records')
    return snapshots


def _immutable_check(contract):
    for tree in contract['trees']:
        for relative, expected in tree['immutableFiles'].items():
            path = _target(tree['path'], relative)
            if not path.is_file():
                raise RootBuilderUncertainty('Immutable hard-linked executable is missing: restoration is uncertain; no repair attempted')
            before = path.stat()
            facts = _hash(path, readonly_hardlink=True)
            info = path.stat()
            current = {**facts, 'device': info.st_dev, 'inode': info.st_ino, 'links': info.st_nlink,
                       'mode': info.st_mode, 'attributes': getattr(info, 'st_file_attributes', 0)}
            if current != expected or (before.st_dev, before.st_ino, before.st_nlink) != (info.st_dev, info.st_ino, info.st_nlink):
                raise RootBuilderUncertainty('Immutable hard-linked executable changed/reappeared: restoration is uncertain; no repair attempted')


def restore(session):
    """Restore only after exact owned processes ended; write-ahead every deletion."""
    from . import native
    record, contract = _record(session)
    if record['phase'] == 'restored':
        return
    marker = session.state.get('rootBuilderMO2Finished', {})
    owned_mo2 = [row['identity'] for row in session.state.get('owned', []) if row.get('role') == 'mo2']
    if (marker.get('verified') is not True or marker.get('game') != session.state.get('game') or
            marker.get('ownedMO2') != owned_mo2 or type(marker.get('at')) not in (int, float) or not math.isfinite(marker['at'])):
        _fail('Root Builder restoration requires exact verified MO2-finished evidence')
    for row in session.state.get('owned', []):
        if row.get('role') in ('mo2', 'game', 'loader') and native.alive(row['identity']):
            _fail('Owned MO2/game/loader is still alive; Root Builder may still be writing')
    protected = {_canonical(contract['paths']['mo2_exe']), _canonical(Path(contract['paths']['game']) / 'SkyrimVR.exe'),
                 _canonical(Path(contract['paths']['game']) / 'sksevr_loader.exe')}
    for process in native.processes():
        if process['name'].casefold() in ('modorganizer.exe', 'skyrimvr.exe', 'sksevr_loader.exe'):
            identity = native.identity(process['pid'])
            if identity is None or _canonical(identity['path']) in protected:
                _fail('Unknown or active process may own this Root Builder installation')
    data_path = Path(contract['paths']['root_builder_data'])
    _immutable_check(contract)
    current_trees = [_tree(tree['path'], view=Path(tree['path']) != data_path, data=Path(tree['path']) == data_path,
                          game=Path(tree['path']) == Path(contract['paths']['game']))
                     for tree in contract['trees']]
    if record['phase'] == 'preparing' and (current_trees != contract['trees'] or
            _directories(contract['paths']['game']) != contract['gameDirectories']):
        _fail('Incomplete preparation with changed managed files requires separate recovery review')
    if record['restoreIntent'] is None:
        created = []
        directories = []
        for before, after in zip(contract['trees'], current_trees):
            for relative in set(after['files']) - set(before['files']):
                created.append({'anchor': before['path'], 'relative': relative, **after['files'][relative]})
            for relative in set(after['directories']) - set(before['directories']):
                directories.append({'anchor': before['path'], 'relative': relative})
        for relative in set(_directories(contract['paths']['game'])) - set(contract['gameDirectories']):
            item = {'anchor': contract['paths']['game'], 'relative': relative}
            if item not in directories:
                directories.append(item)
        record['restoreIntent'] = {'createdFiles': created, 'createdDirectories': directories, 'removedFiles': [], 'removedDirectories': []}
        record['phase'] = 'restoring'
        session.save()
    intent = record['restoreIntent']
    snapshots = _validate_restore_scope(session, record, contract)
    for item in intent['createdFiles']:
        path = _target(item['anchor'], item['relative'])
        identity = str(path)
        if identity in intent['removedFiles']:
            if path.exists():
                _fail('An already removed owned-created Root Builder file reappeared')
            continue
        if path.exists():
            if _hash(path) != {'sha256': item['sha256'], 'size': item['size']}:
                _fail('Owned-created Root Builder file changed during restoration')
            path.unlink()
        intent['removedFiles'].append(identity)
        session.save()
    for path in reversed(record['snapshotPaths']):
        _safe(path)
        entry = snapshots.get(_canonical(path))
        if entry is None:
            _fail('Root Builder durable file snapshot is missing')
        if entry.get('exists'):
            backup = _safe(entry['backup'])
            if not backup.resolve().is_relative_to(_safe(session.dir).resolve()):
                _fail('Root Builder backup escapes its owned journal')
        session.restore_file(entry)
    for tree in contract['trees']:
        for relative in tree['directories']:
            _target(tree['path'], relative).mkdir(parents=True, exist_ok=True)
    for relative in contract['gameDirectories']:
        _target(contract['paths']['game'], relative).mkdir(parents=True, exist_ok=True)
    for item in sorted(intent['createdDirectories'], key=lambda row: len(Path(row['relative']).parts), reverse=True):
        path = _target(item['anchor'], item['relative'])
        if str(path) in intent['removedDirectories']:
            if path.exists():
                _fail('Removed Root Builder directory reappeared')
            continue
        if path.exists():
            path.rmdir()  # Only an individually inventoried, checked EMPTY directory.
        intent['removedDirectories'].append(str(path))
        session.save()
    for before in contract['trees']:
        after = _tree(before['path'], view=Path(before['path']) != data_path, data=Path(before['path']) == data_path,
                      game=Path(before['path']) == Path(contract['paths']['game']))
        if after != before:
            _fail('Root Builder bytes or directory/file membership were not restored')
    if _directories(contract['paths']['game']) != contract['gameDirectories']:
        _fail('Root Builder game-directory membership was not restored')
    record['phase'] = 'restored'
    session.save()
