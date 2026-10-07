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

PATH_KEYS = {"runtime", "mo2", "mo2_exe", "mo2_ini", "game", "mods", "profiles", "overwrite", "bridge_token", "openvr_paths", "skse_logs", "fixture_dir"}
REQUIRED = {"runtime", "mo2", "game", "mods", "profiles", "overwrite", "bridge_token", "openvr_paths", "skse_logs"}
P = Paths()

def configure(value, base=None):
    if value.get("schemaVersion") != SCHEMA:
        raise ConfigurationError("Configuration needs schemaVersion 1")
    missing = sorted(k for k in REQUIRED if not value.get(k))
    if missing:
        raise ConfigurationError("Missing configuration fields: " + ", ".join(missing))
    unknown = set(value) - PATH_KEYS - {"schemaVersion", "bridge_port", "required_mods", "extra_files", "staged_plugins", "devbench_runtime_files", "controller_start_positions_metres", "allow_background_physical_vr", "reuse_test_profile", "allow_owned_save_load", "physical_grip_geometry"}
    if unknown:
        raise ConfigurationError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
    base = Path(base or Path.cwd()).resolve()
    result = dict(value)
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
    mods = result.setdefault("required_mods", ["DevBench", "VRIK Player Avatar", "HIGGS - Enhanced VR Interaction"])
    if not isinstance(mods, list) or not mods or any(not isinstance(m, str) or not m or m in (".", "..") or "/" in m or "\\" in m for m in mods):
        raise ConfigurationError("required_mods must contain safe mod directory names")
    for key in ("extra_files", "devbench_runtime_files"):
        files = result.setdefault(key, [])
        if not isinstance(files, list) or any(not isinstance(f, str) or not f for f in files):
            raise ConfigurationError(key + " must be a list of file paths")
        result[key] = [str((base / Path(f).expanduser()).resolve()) for f in files]
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

def template():
    return {"schemaVersion": 1, "runtime": str(default_runtime()), "mo2": "REPLACE/MO2", "game": "REPLACE/SkyrimVR", "mods": "REPLACE/MO2/mods", "profiles": "REPLACE/MO2/profiles", "overwrite": "REPLACE/MO2/overwrite", "bridge_token": "REPLACE/MO2/plugins/mo2aibridge/mo2aibridge-token.txt", "bridge_port": 8930, "openvr_paths": str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "openvr/openvrpaths.vrpath"), "skse_logs": "REPLACE/Documents/My Games/Skyrim VR/SKSE", "fixture_dir": "REPLACE/authorized-fixture", "required_mods": ["DevBench", "VRIK Player Avatar", "HIGGS - Enhanced VR Interaction"], "extra_files": [], "staged_plugins": [], "devbench_runtime_files": []}
