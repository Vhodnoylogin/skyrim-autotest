"""Offline, immutable external setup. This module never launches or installs a game."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import sys
import tempfile
from urllib.parse import urlsplit

from . import __version__, config
from .editions import target, validate_mo2_loader

SCHEMA = 1
PROVIDER_DESTINATION = 'SKSE/Plugins/devbench/config.json'
CORE_DEPENDENCIES = {'game', 'skse', 'mo2', 'mo2-api-bridge', 'devbench', 'address-library'}
VR_DEPENDENCIES = {'steamvr', 'physical-driver', 'openvr-header'}
TOP_KEYS = {'schemaVersion', 'game_edition', 'config_directory', 'paths', 'bridge_port',
            'required_mods', 'dependencies', 'provider', 'configuration',
            'staged_plugins', 'destination_allowlist', 'command_bus'}


class SetupError(ValueError):
    """A preparation refusal; no launch or recovery is implied."""


def _bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _object(value, label, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise SetupError(label + ' has missing or unknown fields')
    return value


def _absolute(value, label):
    if not isinstance(value, str) or not value or not Path(value).is_absolute() or 'REPLACE' in value:
        raise SetupError(label + ' must be an explicit absolute path')
    path = Path(value)
    if any(part in ('.', '..') for part in path.parts):
        raise SetupError(label + ' must not contain path traversal')
    _no_links(path)
    return path.resolve()


def _no_links(path):
    """Refuse links/junctions at existing ancestors, before resolving a path."""
    for item in [Path(path), *Path(path).parents]:
        try:
            stat = item.lstat()
        except FileNotFoundError:
            continue
        if item.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
            raise SetupError('Symlink/reparse-point paths are not admitted: ' + str(item))


def _outside_git(path, label):
    if any((ancestor / '.git').exists() for ancestor in [path, *path.parents]):
        raise SetupError(label + ' must be outside Git check-outs')
    package = Path(__file__).resolve().parent.parent
    if path.is_relative_to(package):
        raise SetupError(label + ' must be outside the distribution')


def _source(value):
    if not isinstance(value, str):
        raise SetupError('Artifact source must be an HTTPS acquisition URL')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError('Artifact source must be an HTTPS acquisition URL without credentials/query/fragment')
    return value


def _pin(value, label):
    _object(value, label, {'path', 'sha256', 'source'}, {'path', 'sha256', 'source'})
    if not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        raise SetupError(label + ' needs an actual lower-case SHA256 pin')
    path = _absolute(value['path'], label + '.path')
    return dict(path=str(path),
                sha256=value['sha256'], source=_source(value['source']))


def _destination(value):
    if (not isinstance(value, str) or not value or '\\' in value or
            PureWindowsPath(value).drive or value.startswith('/') or
            any(part in ('', '.', '..') for part in value.split('/')) or
            not value.casefold().startswith('skse/plugins/')):
        raise SetupError('Staged destinations must be explicit safe SKSE/Plugins relative paths')
    return value


def _load_spec(spec_path):
    path = _absolute(str(spec_path), 'specification')
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as error:
        raise SetupError('Setup specification is not valid UTF-8 JSON') from error
    _object(value, 'Setup specification', TOP_KEYS,
            {'schemaVersion', 'game_edition', 'config_directory', 'paths', 'bridge_port',
             'required_mods', 'dependencies', 'provider', 'destination_allowlist'})
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != SCHEMA or value['game_edition'] not in ('se', 'vr'):
        raise SetupError('Setup requires schemaVersion 1 and explicit game_edition se or vr')
    paths = value['paths']
    required = (config.REQUIRED - {'openvr_paths'}) | {'mo2_exe', 'mo2_ini'}
    if value['game_edition'] == 'vr':
        required.add('openvr_paths')
    _object(paths, 'paths', config.PATH_KEYS, required)
    normalized = {key: str(_absolute(item, 'paths.' + key)) for key, item in paths.items()}
    output = _absolute(value['config_directory'], 'config_directory')
    for key in ('runtime',):
        _outside_git(Path(normalized[key]), key)
    _outside_git(output, 'config_directory')
    live = [Path(normalized[key]) for key in ('game', 'mo2', 'mods', 'profiles', 'overwrite')]
    for candidate, label in ((output, 'config_directory'), (Path(normalized['runtime']), 'runtime')):
        if any(candidate.is_relative_to(directory) for directory in live):
            raise SetupError(label + ' must be outside live game/MO2 directories')
    if output == Path(normalized['runtime']):
        raise SetupError('config_directory and runtime must be separate directories')
    selected = target(value)
    if Path(normalized['mo2_exe']).name.casefold() != 'modorganizer.exe':
        raise SetupError('paths.mo2_exe must select ModOrganizer.exe explicitly')
    extras = value.get('configuration', {})
    if not isinstance(extras, dict) or set(extras) & (config.PATH_KEYS | {'schemaVersion', 'game_edition', 'bridge_port', 'required_mods', 'staged_plugins'}):
        raise SetupError('configuration may contain only optional non-path runner settings')
    # All additional path-bearing fields must also use explicit absolute paths.
    for key in ('extra_files', 'collected_files', 'devbench_runtime_files'):
        if key in extras:
            if not isinstance(extras[key], list):
                raise SetupError(key + ' must be a list')
            for entry in extras[key]:
                _absolute(entry, key)
    allowed = value['destination_allowlist']
    if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
        raise SetupError('destination_allowlist must contain exact relative paths')
    allowed = [_destination(item) for item in allowed]
    if len({item.casefold() for item in allowed}) != len(allowed) or PROVIDER_DESTINATION not in allowed:
        raise SetupError('destination_allowlist must uniquely include ' + PROVIDER_DESTINATION)
    plugins = []
    if not isinstance(value.get('staged_plugins', []), list):
        raise SetupError('staged_plugins must be a list')
    destinations = {PROVIDER_DESTINATION.casefold()}
    for item in value.get('staged_plugins', []):
        _object(item, 'staged plugin', {'source', 'destination', 'sha256'}, {'source', 'destination', 'sha256'})
        destination = _destination(item['destination'])
        if destination not in allowed or destination.casefold() in destinations:
            raise SetupError('Staged destination is duplicate or outside destination_allowlist')
        destinations.add(destination.casefold())
        if not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise SetupError('Staged source requires lower-case SHA256')
        source = _absolute(item['source'], 'staged source')
        _no_links(Path(normalized['overwrite']) / destination)
        plugins.append(dict(source=str(source),
                            destination=destination, sha256=item['sha256']))
    _no_links(Path(normalized['overwrite']) / PROVIDER_DESTINATION)
    dependencies = value['dependencies']
    if not isinstance(dependencies, list):
        raise SetupError('dependencies must be a list of pinned external artifacts')
    deps = []
    for item in dependencies:
        _object(item, 'dependency', {'id', 'path', 'sha256', 'source', 'kind', 'required'},
                {'id', 'path', 'sha256', 'source'})
        if not isinstance(item['id'], str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', item['id']):
            raise SetupError('Dependency id must be a stable lower-case name')
        if item.get('kind', 'file') not in ('file', 'pe', 'header') or type(item.get('required', True)) is not bool:
            raise SetupError('Invalid dependency kind/required value')
        pin = _pin({key: item[key] for key in ('path', 'sha256', 'source')}, 'dependency ' + item['id'])
        deps.append(dict(pin, id=item['id'], kind=item.get('kind', 'file'), required=item.get('required', True)))
    if len({item['id'] for item in deps}) != len(deps):
        raise SetupError('Duplicate dependency id')
    provider = value['provider']
    _object(provider, 'provider', {'artifact', 'configuration', 'capability_manifest'},
            {'artifact', 'configuration', 'capability_manifest'})
    if provider['artifact'] != 'devbench':
        raise SetupError('provider.artifact must name the pinned devbench dependency')
    provider = {'artifact': 'devbench', 'configuration': _pin(provider['configuration'], 'provider.configuration'),
                'capability_manifest': _pin(provider['capability_manifest'], 'provider.capability_manifest')}
    bus = value.get('command_bus')
    if bus is not None:
        _object(bus, 'command_bus', {'api_url', 'token_path'}, {'api_url', 'token_path'})
        url = urlsplit(bus['api_url']) if isinstance(bus['api_url'], str) else None
        if (not url or url.scheme != 'http' or url.hostname != '127.0.0.1' or url.port is None or
                url.path not in ('/v1', '/v1/') or url.username or url.password or url.query or url.fragment):
            raise SetupError('command_bus.api_url must be http://127.0.0.1:<explicit port>/v1 without credentials/query/fragment')
        bus = {'api_url': bus['api_url'], 'token_path': str(_absolute(bus['token_path'], 'command_bus.token_path'))}
        _outside_git(Path(bus['token_path']), 'command_bus.token_path')
        if Path(bus['token_path']) == Path(normalized['runtime']) / 'command-channel/commands.sqlite3':
            raise SetupError('Command channel token and database paths must be separate')
    secrets = {Path(normalized['bridge_token'])}
    if bus:
        secrets.add(Path(bus['token_path']))
    if any(item.is_relative_to(output) for item in secrets):
        raise SetupError('Private token files must stay outside the immutable config_directory')
    read_sources = [Path(item['path']) for item in deps] + [Path(item['source']) for item in plugins]
    read_sources += [Path(provider[key]['path']) for key in ('configuration', 'capability_manifest')]
    if any(item in secrets for item in read_sources) or path in secrets:
        raise SetupError('Token files cannot be used as setup specifications or artifact sources')
    if any(item.is_relative_to(output) for item in read_sources) or path.is_relative_to(output):
        raise SetupError('Setup inputs must be immutable external sources outside config_directory')
    configuration = dict(extras, schemaVersion=1, game_edition=value['game_edition'], **normalized,
                         bridge_port=value['bridge_port'], required_mods=value['required_mods'], staged_plugins=plugins)
    previous = config.P.snapshot()
    try:
        config.configure(configuration, output)
    finally:
        config.P.value = previous
    return {'spec_path': path, 'spec_sha256': _digest(raw), 'specification': value,
            'output': output, 'configuration': configuration, 'dependencies': deps,
            'provider': provider, 'command_bus': bus, 'selected': selected}


def _pe(path):
    with Path(path).open('rb') as stream:
        prefix = stream.read(64)
        if len(prefix) < 64 or prefix[:2] != b'MZ':
            raise SetupError('Expected a Windows PE executable header')
        offset = struct.unpack_from('<I', prefix, 60)[0]
        if offset < 64 or offset > 16 * 1024 * 1024:
            raise SetupError('Invalid Windows PE header offset')
        stream.seek(offset)
        header = stream.read(26)
    if len(header) < 26 or header[:4] != b'PE\0\0' or struct.unpack_from('<H', header, 4)[0] != 0x8664 or struct.unpack_from('<H', header, 24)[0] != 0x20b:
        raise SetupError('Expected an AMD64 PE32+ executable')


def _read_pin(pin):
    path = Path(pin['path'])
    _no_links(path)
    if not path.is_file():
        raise SetupError('Missing pinned external artifact: ' + str(path))
    if _sha(path) != pin['sha256']:
        raise SetupError('SHA256 mismatch: ' + str(path))
    return path


def _provider_config(context):
    path = _read_pin(context['provider']['configuration'])
    try:
        original = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError) as error:
        raise SetupError('Pinned provider configuration is not valid UTF-8 JSON') from error
    if not isinstance(original, dict):
        raise SetupError('Pinned provider configuration must be a JSON object')
    prepared = dict(original, alwaysActive=True)
    return _bytes(prepared)


def _assess(context):
    checks = []
    def check(name, action, remedy, required=True):
        try:
            action()
            checks.append({'id': name, 'status': 'ok', 'required': required})
        except (OSError, ValueError, KeyError, TypeError, configparser.Error) as error:
            checks.append({'id': name, 'status': 'missing-or-invalid', 'required': required,
                           'detail': str(error), 'action': remedy})
    def require(condition, message):
        if not condition:
            raise SetupError(message)
    cfg = context['configuration']
    selected = context['selected']
    root_policy = cfg.get('root_builder')
    source_loader = (Path(cfg['mods']) / root_policy['loaderMod'] / 'Root' / selected['loader']
                     if root_policy else Path(cfg['game']) / selected['loader'])
    check('python', lambda: require(sys.version_info >= (3, 11), 'Python 3.11+ is required'), 'Install Python 3.11+ from python.org; rerun doctor.')
    for key in ('game', 'mo2', 'mods', 'profiles', 'overwrite', 'skse_logs'):
        check('directory.' + key, lambda key=key: require(Path(cfg[key]).is_dir(), 'Declared directory does not exist: ' + cfg[key]),
              'Create or explicitly correct this external installation path; setup never guesses an instance.')
    token_path = Path(cfg['bridge_token'])
    installed_bridge = next((item for item in context['dependencies'] if item['id'] == 'mo2-api-bridge'), None)
    deferred_token = False
    if not token_path.exists() and not cfg.get('reuse_test_profile') and installed_bridge:
        try:
            deferred_token = _read_pin(installed_bridge).is_relative_to(Path(cfg['mo2']) / 'plugins')
        except (OSError, ValueError):
            pass
    if deferred_token:
        checks.append({'id': 'file.bridge_token', 'status': 'deferred-to-owned-mo2-start', 'required': False,
            'detail': 'Cold-owned MO2 has a verified installed Bridge pin; its lifecycle may remove this token while stopped.',
            'action': 'Preserve the declared token path. The later owned MO2 startup must regenerate it and prove the exact Bridge identity before use. Setup creates no Bridge credential.'})
    else:
        check('file.bridge_token', lambda: require(token_path.is_file() and token_path.stat().st_size > 0, 'Declared token file is absent or empty'),
              'Let the separately installed MO2 Bridge provision its private token; borrowed/reuse mode requires the existing token. Do not put the token in the spec.')
    for name, path in [('game', Path(cfg['game']) / selected['executable']), ('skse', source_loader), ('mo2', Path(cfg['mo2_exe']))]:
        check('executable.' + name, lambda path=path: _pe(path), 'Acquire the correct edition-specific x64 executable through its official source.')
    if root_policy:
        def root_source():
            from .root_builder import plugin_fingerprint
            require(plugin_fingerprint(Path(cfg['mo2']) / 'plugins/rootbuilder') == root_policy['pluginTreeSha256'],
                    'Installed Root Builder package differs from the audited copy-5.1.1 pin')
            source = source_loader.parent
            for name, digest in root_policy['bundleSha256'].items():
                path = _read_pin({'path': str(source / name), 'sha256': digest})
                _pe(path)
            # This is the exact existing declared cache, not a guessed/new cache.
            game_key = str(Path(cfg['game'])).replace(' ', '_').replace('.', '_')
            for character in '<>:|*\\/?"':
                game_key = game_key.replace(character, '')
            expected = Path(cfg['mo2']) / 'plugins/data/RootBuilder' / game_key / '1_4_15_0'
            data = Path(cfg['root_builder_data'])
            require(data == expected and data.is_dir(), 'Root Builder data must be the existing exact game/version directory')
            require((data / 'Backup').is_dir() and (data / 'GameData.json').is_file() and not (data / 'BuildData.json').exists(),
                    'Root Builder needs existing backup/cache and no active BuildData')
        check('root-builder.source', root_source,
              'Preserve the audited plugin, exact existing game/version cache and all three pinned SKSEVR source files. A later run preflight must verify the explicit enabled source profile and unique winning bundle; do not copy a loader into the game manually.')
    def mo2_contract():
        text = Path(cfg['mo2_ini']).read_text(encoding='utf-8-sig')
        validate_mo2_loader(text, cfg)
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)
        if parser.has_section('Settings'):
            for ini_key, key in [('mod_directory', 'mods'), ('profiles_directory', 'profiles'), ('overwrite_directory', 'overwrite')]:
                if parser.has_option('Settings', ini_key):
                    raw = parser['Settings'][ini_key].replace('%BASE_DIR%', str(Path(cfg['mo2_ini']).parent))
                    actual = Path(raw)
                    if not actual.is_absolute():
                        raise SetupError('MO2 setting ' + ini_key + ' must resolve to an explicit absolute path')
                    require(actual.resolve() == Path(cfg[key]), 'MO2 instance path mismatch: ' + ini_key)
    check('mo2.instance', mo2_contract, 'Configure this declared MO2 instance and register one SKSE entry with the correct loader, exact game working directory and no arguments.')
    for name in cfg['required_mods']:
        check('required-mod.' + name, lambda name=name: require((Path(cfg['mods']) / name).is_dir(), 'Required mod directory is absent: ' + name),
              'Acquire/install this edition-compatible mod separately under exclusive operator ownership; setup never activates it.')
    deps = {item['id']: item for item in context['dependencies']}
    mandatory = CORE_DEPENDENCIES | (VR_DEPENDENCIES if selected['edition'] == 'vr' else set())
    for name in sorted(mandatory - deps.keys()):
        check('dependency.' + name, lambda name=name: require(False, 'No pinned acquisition declaration for ' + name),
              'Add the acquired artifact absolute path, actual SHA256 and official HTTPS source to dependencies; see dependencies.json.')
    expected = {'game': Path(cfg['game']) / selected['executable'], 'skse': source_loader, 'mo2': Path(cfg['mo2_exe'])}
    for item in context['dependencies']:
        def artifact(item=item):
            path = _read_pin(item)
            if item['id'] in expected:
                require(path == expected[item['id']], 'Dependency pin selects a different declared executable')
            if item['kind'] == 'pe' or item['id'] in {'game', 'skse', 'mo2', 'devbench', 'steamvr', 'physical-driver'}:
                _pe(path)
            if item['kind'] == 'header' or item['id'] == 'openvr-header':
                data = path.read_bytes()
                require(bool(data) and b'\0' not in data and re.search(rb'#\s*(pragma|ifndef|include|define)|\btypedef\b', data) is not None,
                        'Expected a C/C++ SDK header')
        check('dependency.' + item['id'], artifact, 'Acquire/build the exact external artifact from ' + item['source'] + '; record the resulting actual hash. No download was attempted.',
              item['required'] or item['id'] in mandatory)
    check('provider.configuration', lambda: _provider_config(context),
          'Pin the actual winning full DevBench JSON configuration. Setup preserves its settings and stages an external copy with alwaysActive:true.')
    def capabilities():
        manifest = json.loads(_read_pin(context['provider']['capability_manifest']).read_text(encoding='utf-8-sig'))
        _object(manifest, 'provider capability manifest', {'schemaVersion', 'game_edition', 'providerSha256', 'capabilities', 'source'},
                {'schemaVersion', 'game_edition', 'providerSha256', 'capabilities'})
        require(manifest['schemaVersion'] == 1 and manifest['game_edition'] == selected['edition'], 'Capability declaration has wrong schema/edition')
        require('devbench' in deps and manifest['providerSha256'] == deps['devbench']['sha256'], 'Capability declaration does not pin this DevBench binary')
        values = manifest['capabilities']
        require(isinstance(values, list) and all(isinstance(item, str) for item in values), 'Explicit capability names are required')
        needed = {'native-menu-flags'}
        if cfg.get('se_new_game_ui'):
            needed.add('devbench-startup-ui/1')
        require(needed <= set(values), 'Missing declared native provider capabilities: ' + ', '.join(sorted(needed - set(values))))
    check('provider.capabilities', capabilities, 'Build/acquire the matching native provider; pin an edition-specific capability manifest for its exact DLL. Version strings do not establish native startup/menu support.')
    for item in cfg['staged_plugins']:
        check('staged.' + item['destination'], lambda item=item: _read_pin({'path': item['source'], 'sha256': item['sha256']}),
              'Supply the exact immutable external staged source; runtime staging occurs only in a later separately admitted owned session.')
    if selected['edition'] == 'vr':
        def openvr():
            value = json.loads(Path(cfg['openvr_paths']).read_text(encoding='utf-8-sig'))
            for key in ('runtime', 'config'):
                require(isinstance(value.get(key), list) and len(value[key]) == 1, 'OpenVR needs one explicit ' + key + ' directory')
                require(_absolute(value[key][0], 'OpenVR ' + key).is_dir(), 'OpenVR ' + key + ' directory is absent')
        check('openvr.paths', openvr, 'Install SteamVR separately and explicitly select its actual openvrpaths.vrpath; SE needs no VR setup.')
    if context['command_bus']:
        path = Path(context['command_bus']['token_path'])
        check('command-bus.token', lambda: require(path.is_file() and path.stat().st_size > 0, 'External API token file is absent or empty'),
              'Connect the separate voice/command adapter through its API and token file; no microphone or listener is installed here.', required=False)
    result = {'schemaVersion': 1, 'game_edition': selected['edition'], 'preparationReady': all(row['status'] == 'ok' or not row['required'] for row in checks),
            'liveQualified': False, 'scope': 'Offline preparation only; no process, API, game, microphone or queue was contacted.',
            'checks': checks,
            'acquisition': context['dependencies']}
    if root_policy:
        result['rootBuilder'] = {'mode': root_policy['mode'], 'sourceLoader': str(source_loader),
            'sourceReady': next(row['status'] for row in checks if row['id'] == 'root-builder.source') == 'ok',
            'deployment': 'pending-owned-autobuild', 'sourceProfileChecked': False,
            'instruction': 'Run separately admitted preflight --profile NAME to verify enabled unique source winners, settings and complete restoration scope before any owned autobuild. No deployed game-root loader is required by this offline source check.'}
    return result


def _source_identity():
    return {'version': __version__, 'module': 'skyrim_autotest.setup',
            'setupSha256': _sha(Path(__file__)), 'configurationSha256': _sha(Path(config.__file__))}


def _prepared_configuration(context, prepared):
    value = dict(context['configuration'])
    value['staged_plugins'] = [*value['staged_plugins'],
        {'source': str(context['output'] / 'prepared-devbench-config.json'),
         'destination': PROVIDER_DESTINATION, 'sha256': _digest(prepared)}]
    return value


def _bus_bytes(context):
    return _bytes(dict(schemaVersion=1, **context['command_bus'],
        configuration=str(context['output'] / 'config.json'), adapter='external',
        instruction='Use a separately installed adapter through this API. No microphone, model or listener is installed or started.'))


def _channel_bytes(context):
    return _bytes({'schemaVersion': 1,
        'database': str(Path(context['configuration']['runtime']) / 'command-channel/commands.sqlite3'),
        'tokenFile': context['command_bus']['token_path'], 'host': '127.0.0.1',
        'port': urlsplit(context['command_bus']['api_url']).port,
        'maxRequestBytes': 65536, 'claimTimeoutSeconds': 300})


def _verify_outputs(context):
    directory = context['output']
    _no_links(directory)
    manifest_path = directory / 'setup-manifest.json'
    _no_links(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise SetupError('Existing config_directory has no valid setup manifest; existing files were preserved') from error
    _object(manifest, 'Existing setup manifest',
            {'schemaVersion', 'source', 'specification', 'game_edition', 'files', 'providerSources', 'dependencies', 'liveQualified'},
            {'schemaVersion', 'source', 'specification', 'game_edition', 'files', 'providerSources', 'dependencies', 'liveQualified'})
    if (manifest.get('schemaVersion') != 1 or manifest.get('specification') != {'path': str(context['spec_path']), 'sha256': context['spec_sha256']} or
            manifest.get('source') != _source_identity()):
        raise SetupError('Setup inputs/source changed; choose a new config_directory. Existing configuration was preserved')
    if (manifest['providerSources'] != context['provider'] or manifest['dependencies'] != context['dependencies'] or
            manifest['game_edition'] != context['selected']['edition'] or manifest['liveQualified'] is not False):
        raise SetupError('Existing setup manifest provenance changed; existing files were preserved')
    files = manifest.get('files')
    expected = {'config.json', 'prepared-devbench-config.json', 'dependencies-report.json'} | ({'command-bus.json', 'command-channel.json'} if context['command_bus'] else set())
    if not isinstance(files, dict) or set(files) != expected:
        raise SetupError('Existing setup manifest output inventory changed')
    if set(item.name for item in directory.iterdir()) != expected | {'setup-manifest.json'}:
        raise SetupError('Existing config_directory contains changed/unexpected outputs')
    for name, digest in files.items():
        path = directory / name
        _no_links(path)
        if not path.is_file() or _sha(path) != digest:
            raise SetupError('Existing setup output changed: ' + name + '; it was preserved')
    # Verify generated settings and current sources as well as frozen output bytes.
    value = json.loads((directory / 'config.json').read_text(encoding='utf-8'))
    prepared = _provider_config(context)
    if (directory / 'prepared-devbench-config.json').read_bytes() != prepared:
        raise SetupError('Prepared provider configuration no longer matches its pinned source')
    if value != _prepared_configuration(context, prepared):
        raise SetupError('Existing configuration no longer matches its setup specification')
    if context['command_bus'] and (directory / 'command-bus.json').read_bytes() != _bus_bytes(context):
        raise SetupError('Existing command-bus reference no longer matches its setup specification')
    if context['command_bus'] and (directory / 'command-channel.json').read_bytes() != _channel_bytes(context):
        raise SetupError('Existing command-channel configuration no longer matches its setup specification')
    previous = config.P.snapshot()
    try:
        config.load(directory / 'config.json')
    finally:
        config.P.value = previous
    context['configuration'] = value
    return manifest


def doctor(spec_path):
    """Return actionable filesystem/pin checks. Never contact a live endpoint."""
    context = _load_spec(spec_path)
    if context['output'].exists():
        _verify_outputs(context)
    result = _assess(context)
    result.update(configuration=str(context['output'] / 'config.json'), installed=context['output'].exists())
    return result


def install(spec_path):
    """Atomically create one new config bundle, or verify an identical existing one."""
    context = _load_spec(spec_path)
    output = context['output']
    if output.exists():
        _verify_outputs(context)
        result = _assess(context)
        return dict(result, installed=True, idempotent=True, configuration=str(output / 'config.json'))
    if not output.parent.is_dir():
        raise SetupError('config_directory parent must already exist; no directory tree was created')
    lock = output.parent / ('.' + output.name + '.setup.lock')
    _no_links(lock)
    stage = None
    owned_lock = False
    try:
        with lock.open('x', encoding='utf-8'):
            owned_lock = True
            if output.exists():
                raise SetupError('config_directory appeared during preparation; no existing files were changed')
            prepared = _provider_config(context)
            configuration = _prepared_configuration(context, prepared)
            previous = config.P.snapshot()
            try:
                config.configure(configuration, output)
            finally:
                config.P.value = previous
            report = _assess(context)
            payloads = {'config.json': _bytes(configuration), 'prepared-devbench-config.json': prepared,
                        'dependencies-report.json': _bytes(report)}
            if context['command_bus']:
                payloads['command-bus.json'] = _bus_bytes(context)
                payloads['command-channel.json'] = _channel_bytes(context)
            manifest = {'schemaVersion': 1, 'source': _source_identity(),
                        'specification': {'path': str(context['spec_path']), 'sha256': context['spec_sha256']},
                        'game_edition': configuration['game_edition'],
                        'files': {name: _digest(data) for name, data in payloads.items()},
                        'providerSources': context['provider'], 'dependencies': context['dependencies'],
                        'liveQualified': False}
            payloads['setup-manifest.json'] = _bytes(manifest)
            stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.setup-', dir=output.parent))
            for name, data in payloads.items():
                with (stage / name).open('xb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            # Use the actual public loader on the staged config, without leaving
            # its process-global configuration changed for callers.
            previous = config.P.snapshot()
            try:
                config.load(stage / 'config.json')
                if context['command_bus']:
                    from .command_bus import load_config as load_channel_config
                    load_channel_config(stage / 'command-channel.json')
            finally:
                config.P.value = previous
            _no_links(output)
            if output.exists():
                raise SetupError('config_directory appeared during preparation; existing files were preserved')
            os.rename(stage, output)
            stage = None
            return dict(report, installed=True, idempotent=False, configuration=str(output / 'config.json'))
    finally:
        if stage is not None:
            _no_links(stage)
            if stage.resolve().parent != output.parent:
                raise SetupError('Refusing cleanup outside the owned staging parent')
            shutil.rmtree(stage)
        if owned_lock:
            lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='skyrim-autotest setup')
    parser.add_argument('operation', choices=['install', 'doctor'])
    parser.add_argument('--spec', required=True, type=Path, help='Explicit absolute schema-1 setup specification')
    args = parser.parse_args(argv)
    try:
        result = install(args.spec) if args.operation == 'install' else doctor(args.spec)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result['preparationReady'] else 2
    except (SetupError, config.ConfigurationError, OSError, ValueError, TypeError) as error:
        print(json.dumps({'result': 'blocked', 'preparationReady': False, 'liveQualified': False, 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
