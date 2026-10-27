"""Explicit external configuration; no project or machine-specific path provider."""
from __future__ import annotations
import json
import os
from pathlib import Path, PureWindowsPath
import re
import math

SCHEMA = 1

def default_runtime():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "Skyrim Autotest"

class ConfigurationError(ValueError):
    pass

class Paths:
    def __init__(self):
        self.value = {"schemaVersion": 1, "runtime": str(default_runtime())}
    def __getattr__(self, key):
        if key == "local":
            return self.runtime
        if key in self.value:
            value = self.value[key]
            return Path(value) if key in PATH_KEYS and value else value
        raise ConfigurationError("Configure required field: " + key)
    def snapshot(self):
        return dict(self.value)

PATH_KEYS = {"runtime", "mo2", "mo2_exe", "mo2_ini", "game", "mods", "profiles", "overwrite", "bridge_token", "openvr_paths", "skse_logs", "fixture_dir", "steam_exe", "root_builder_data"}
REQUIRED = {"runtime", "mo2", "game", "mods", "profiles", "overwrite", "bridge_token", "openvr_paths", "skse_logs"}
P = Paths()

def configure(value, base=None):
    if value.get("schemaVersion") != SCHEMA:
        raise ConfigurationError("Configuration needs schemaVersion 1")
    from .editions import target
    try:
        selected = target(value)
    except (ValueError, TypeError) as error:
        raise ConfigurationError(str(error)) from error
    required = REQUIRED - ({'openvr_paths'} if selected['edition'] == 'se' else set())
    missing = sorted(k for k in required if not value.get(k))
    if missing:
        raise ConfigurationError("Missing configuration fields: " + ", ".join(missing))
    unknown = set(value) - PATH_KEYS - {"schemaVersion", "game_edition", "bridge_port", "required_mods", "extra_files", "collected_files", "staged_plugins", "devbench_runtime_files", "controller_start_positions_metres", "allow_background_physical_vr", "reuse_test_profile", "allow_owned_save_load", "physical_grip_geometry", "native_runtime_fixtures", "subject_state_bindings", "allow_steam_client_restart", "boundary_collection", "fixture_actor_allowlist", "fixture_actor_base_allowlist", "photography", "native14_live", "root_builder", "se_new_game_ui", "se_fixture_anchor", "interactive_session"}
    if unknown:
        raise ConfigurationError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
    base = Path(base or Path.cwd()).resolve()
    result = dict(value)
    result['game_edition'] = selected['edition']
    if 'interactive_session' in result:
        from .interactive import validate as validate_interactive
        try:
            result['interactive_session'] = validate_interactive(result['interactive_session'])
        except (ValueError, TypeError, KeyError) as error:
            raise ConfigurationError('Invalid interactive-session policy: ' + str(error)) from error
    if 'se_new_game_ui' in result:
        if type(result['se_new_game_ui']) is not bool or selected['edition'] != 'se':
            raise ConfigurationError('se_new_game_ui is an explicit SE-only boolean startup policy')
    if 'se_fixture_anchor' in result:
        if (result['se_fixture_anchor'] != 'qasmoke-west-navmesh-v1' or
                selected['edition'] != 'se' or result.get('se_new_game_ui') is not True):
            raise ConfigurationError('se_fixture_anchor requires the explicit SE New Game route and qasmoke-west-navmesh-v1')
    if 'root_builder' in result:
        from .root_builder import configuration
        try:
            result['root_builder'] = configuration(result['root_builder'])
        except (ValueError, TypeError, KeyError) as error:
            raise ConfigurationError('Invalid Root Builder policy: ' + str(error)) from error
        if not result.get('root_builder_data') or selected['edition'] != 'vr' or result.get('reuse_test_profile'):
            raise ConfigurationError('Explicit Root Builder requires VR, root_builder_data and a cold-owned MO2 profile')
    if 'native14_live' in result:
        if selected['edition'] != 'vr':
            raise ConfigurationError('Native14 observations require the VR target')
        from .native14_live import configuration
        try:
            result['native14_live'] = configuration(result['native14_live'])
        except (ValueError, TypeError, KeyError) as error:
            raise ConfigurationError('Invalid native14 observation policy: ' + str(error)) from error
    if selected['edition'] == 'se' and (result.get('root_builder_data') or result.get('reuse_test_profile')):
        raise ConfigurationError('SE Root Builder and borrowed/reusable MO2 profiles need separate qualification; keep them disabled')
    if selected['edition'] == 'se' and any(result.get(k) for k in (
            'controller_start_positions_metres', 'physical_grip_geometry',
            'allow_background_physical_vr', 'allow_steam_client_restart')):
        raise ConfigurationError('Skyrim SE must not configure VR controls or SteamVR recovery')
    if 'photography' in result:
        from .photography import configuration
        try:configuration(result['photography'])
        except (ValueError,TypeError,KeyError) as error:raise ConfigurationError('Invalid photography configuration: '+str(error)) from error
    if 'fixture_actor_base_allowlist' in result:
        from .actor_scene import selector
        allowed=result['fixture_actor_base_allowlist']
        try:
            if not isinstance(allowed,list) or len(allowed)>16:raise ValueError('At most16 explicit NPC bases required')
            keys=[selector(v) for v in allowed]
            if len(set(keys))!=len(keys):raise ValueError('Duplicate NPC bases')
        except (ValueError,TypeError,AttributeError) as error:raise ConfigurationError('Invalid fixture NPC base allowlist: '+str(error)) from error
    if 'fixture_actor_allowlist' in result:
        from .actor_scene import selector
        allowed=result['fixture_actor_allowlist']
        try:
            if not isinstance(allowed,list) or len(allowed)>16:raise ValueError('At most16 explicit fixture actors required')
            keys=[selector(v) for v in allowed]
            if len(set(keys))!=len(keys):raise ValueError('Duplicate fixture actors')
        except (ValueError,TypeError,AttributeError) as error:
            raise ConfigurationError('Invalid fixture actor allowlist: '+str(error)) from error
    if 'boundary_collection' in result:
        from .boundary_collection import validate as validate_collection
        try:
            validate_collection(result['boundary_collection'])
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise ConfigurationError('Invalid boundary collection: ' + str(error)) from error
    if 'allow_steam_client_restart' in result and type(result['allow_steam_client_restart']) is not bool:
        raise ConfigurationError('allow_steam_client_restart must be boolean')
    if result.get('allow_steam_client_restart') and (not isinstance(result.get('steam_exe'), str) or not result['steam_exe'] or Path(result['steam_exe']).name.lower() != 'steam.exe'):
        raise ConfigurationError('Graceful Steam restart requires explicit steam_exe path')
    if 'native_runtime_fixtures' in result and type(result['native_runtime_fixtures']) is not bool:
        raise ConfigurationError('native_runtime_fixtures must be boolean')
    if 'physical_grip_geometry' in result:
        geometry=result['physical_grip_geometry']
        if not isinstance(geometry,dict) or set(geometry)!={'palmPositionGameUnits','palmDirection','nearCastDistanceMetres'}:
            raise ConfigurationError('Physical grip geometry requires explicit palm position/direction and near distance')
        for name,limit in [('palmPositionGameUnits',100),('palmDirection',1)]:
            values=geometry[name]
            if not isinstance(values,list) or len(values)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>limit for v in values):
                raise ConfigurationError('Physical grip geometry vector unavailable')
        if sum(v*v for v in geometry['palmDirection'])<.01:
            raise ConfigurationError('Physical grip palm direction is zero')
        distance=geometry['nearCastDistanceMetres']
        if type(distance) not in (int,float) or not math.isfinite(distance) or not 0<distance<=1:
            raise ConfigurationError('Physical grip near distance outside domain')
    if 'allow_background_physical_vr' in result and type(result['allow_background_physical_vr']) is not bool:
        raise ConfigurationError('allow_background_physical_vr must be boolean')
    if 'allow_owned_save_load' in result and type(result['allow_owned_save_load']) is not bool:
        raise ConfigurationError('allow_owned_save_load must be boolean')
    if 'reuse_test_profile' in result and type(result['reuse_test_profile']) is not bool:
        raise ConfigurationError('reuse_test_profile must be boolean')
    if 'controller_start_positions_metres' in result:
        positions = result['controller_start_positions_metres']
        if not isinstance(positions, dict) or set(positions) != {'left', 'right'}:
            raise ConfigurationError('Controller start positions require both explicit hands')
        for xyz in positions.values():
            if not isinstance(xyz, list) or len(xyz) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 2 for v in xyz):
                raise ConfigurationError('Controller start positions require three finite metre values within [-2,2]')
    for key in PATH_KEYS:
        if result.get(key):
            path = Path(result[key]).expanduser()
            result[key] = str((base / path).resolve())
    mo2 = Path(result["mo2"])
    result.setdefault("mo2_exe", str(mo2 / "ModOrganizer.exe"))
    result.setdefault("mo2_ini", str(mo2 / "ModOrganizer.ini"))
    result.setdefault("fixture_dir", None)
    port = result.setdefault("bridge_port", 8930)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ConfigurationError("bridge_port must be an integer in [1, 65535]")
    mods = result.setdefault("required_mods", ["DevBench"] if selected['edition'] == 'se' else ["DevBench", "VRIK Player Avatar", "HIGGS - Enhanced VR Interaction"])
    if not isinstance(mods, list) or not mods or any(not isinstance(m, str) or not m or m in (".", "..") or "/" in m or "\\" in m for m in mods):
        raise ConfigurationError("required_mods must contain safe mod directory names")
    for key in ("extra_files", "devbench_runtime_files", "collected_files"):
        files = result.setdefault(key, [])
        if not isinstance(files, list) or any(not isinstance(f, str) or not f for f in files):
            raise ConfigurationError(key + " must be a list of file paths")
        result[key] = [str((base / Path(f).expanduser()).resolve()) for f in files]
    if not {p.casefold() for p in result['collected_files']} <= {p.casefold() for p in result['extra_files']}:
        raise ConfigurationError('collected_files must be explicit snapshotted extra_files')
    if len(result['collected_files']) != len({p.casefold() for p in result['collected_files']}):
        raise ConfigurationError('Duplicate collected_files')
    bindings=result.get('subject_state_bindings',{})
    if not isinstance(bindings,dict) or len(bindings)>16:raise ConfigurationError('Bounded subject state bindings object required')
    normalized_bindings={}
    write_fields={'settingsDestination','bodySlotsDestination','bodySlotsSource','handednessProfileIni'}
    destinations=set()
    for subject,binding in bindings.items():
        if not isinstance(subject,str) or not 1<=len(subject)<=96 or any(ord(c)<32 for c in subject):raise ConfigurationError('Stable subject binding name required')
        if (not isinstance(binding,dict) or 'inspectKind' not in binding or set(binding)-{'inspectKind'}-write_fields or
                not isinstance(binding['inspectKind'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',binding['inspectKind'])):
            raise ConfigurationError('Subject binding requires exact inspect extension key')
        normalized_bindings[subject]=binding=dict(binding)
        if set(binding)&write_fields:
            if (not write_fields<=set(binding) or not isinstance(binding['handednessProfileIni'],str) or
                    binding['handednessProfileIni'].lower() not in ('skyrimprefs.ini','skyrimvr.ini')):
                raise ConfigurationError('Complete owned subject fixture write binding required')
            for key,suffix in (('settingsDestination','.json'),('bodySlotsDestination','.ini')):
                relative=binding[key]
                if (not isinstance(relative,str) or PureWindowsPath(relative).is_absolute() or PureWindowsPath(relative).drive or
                        not relative.lower().startswith('skse/plugins/') or not relative.lower().endswith(suffix) or
                        any(part in ('','.','..') for part in relative.replace('\\','/').split('/'))):
                    raise ConfigurationError('Fixture destination must be a safe explicit overwrite SKSE/Plugins path')
                target=Path(result['overwrite'])/relative
                if str(target).casefold() in destinations:raise ConfigurationError('Conflicting fixture write destinations')
                destinations.add(str(target).casefold())
                for path in (target,target.with_name(target.name+'.autotest-fixture.tmp')):
                    resolved=str(path.resolve())
                    if resolved.casefold() not in {x.casefold() for x in result['extra_files']}:result['extra_files'].append(resolved)
            source=binding['bodySlotsSource']
            if (not isinstance(source,dict) or set(source)!={'path','sha256'} or not isinstance(source['path'],str) or
                    not isinstance(source['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',source['sha256'])):
                raise ConfigurationError('Pinned immutable external body-slot baseline required')
            path=(base/Path(source['path'])).resolve()
            if any(path.is_relative_to(Path(result[key])) for key in ('mods','profiles','overwrite','game')):
                raise ConfigurationError('Body-slot baseline must be an immutable external copy')
            binding['bodySlotsSource']={**source,'path':str(path)}
    result['subject_state_bindings']=normalized_bindings
    plugins = result.setdefault("staged_plugins", [])
    if not isinstance(plugins, list):
        raise ConfigurationError("staged_plugins must be a list")
    normalized = []
    for plugin in plugins:
        if not isinstance(plugin, dict) or set(plugin) != {"source", "destination", "sha256"}:
            raise ConfigurationError("Each staged plugin needs source, destination and sha256")
        destination = plugin["destination"]
        if not isinstance(destination, str) or not destination or PureWindowsPath(destination).is_absolute() or PureWindowsPath(destination).drive or any(p in ("..", ".") for p in destination.replace("\\", "/").split("/")) or destination.startswith(("/", "\\")):
            raise ConfigurationError("Staged plugin destination must remain under overwrite")
        if not re.fullmatch(r"[0-9a-f]{64}", plugin["sha256"]):
            raise ConfigurationError("Staged plugin needs a lower-case SHA256")
        normalized.append({**plugin, "source": str((base / Path(plugin["source"]).expanduser()).resolve()), "destination": destination.replace("\\", "/")})
    result["staged_plugins"] = normalized
    runtime = Path(result["runtime"])
    package = Path(__file__).resolve().parent
    if runtime.is_relative_to(package.parent):
        raise ConfigurationError("Runtime data must be outside the distribution/check-out")
    if any((ancestor / ".git").exists() for ancestor in [runtime, *runtime.parents]):
        raise ConfigurationError("Runtime data must be outside Git check-outs")
    if any(runtime == Path(result[k]) or runtime.is_relative_to(Path(result[k])) for k in ("game", "mods", "profiles", "overwrite", "mo2")):
        raise ConfigurationError("Runtime data must be outside live MO2/game directories")
    P.value = result
    return result

def load(path):
    path = Path(path).resolve()
    return configure(json.loads(path.read_text(encoding="utf-8-sig")), path.parent)

def template(edition='vr'):
    from .editions import target
    selected = target({'game_edition': edition})
    result = {"schemaVersion": 1, "game_edition": edition, "runtime": str(default_runtime()), "mo2": "REPLACE/MO2", "game": "REPLACE/" + selected['bridgeGame'], "mods": "REPLACE/MO2/mods", "profiles": "REPLACE/MO2/profiles", "overwrite": "REPLACE/MO2/overwrite", "bridge_token": "REPLACE/MO2/plugins/mo2aibridge/mo2aibridge-token.txt", "bridge_port": 8930, "skse_logs": "REPLACE/Documents/My Games/" + ('Skyrim VR' if edition == 'vr' else 'Skyrim Special Edition') + "/SKSE", "fixture_dir": "REPLACE/authorized-fixture", "required_mods": ["DevBench"] + (["VRIK Player Avatar", "HIGGS - Enhanced VR Interaction"] if edition == 'vr' else []), "extra_files": [], "staged_plugins": [], "devbench_runtime_files": []}
    if edition == 'vr':
        result['openvr_paths'] = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "openvr/openvrpaths.vrpath")
    return result
