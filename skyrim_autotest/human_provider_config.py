"""Strict observations of OBody's fixed VFS file and native preset catalog.

This module performs no writes and infers no in-memory distribution policy from
file contents. OBody can merge include files; the fixed main file is one input.
The caller owns process/world guards, deadlines and official readiness evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import PureWindowsPath
import re

from .interactive_bindings import BindingError


COUNT_FIELDS = {"female": "female", "female_blacklisted": "femaleBlacklisted",
                "male": "male", "male_blacklisted": "maleBlacklisted"}
CONFIG_SUFFIX = ("Data", "SKSE", "Plugins", "OBody_presetDistributionConfig.json")
MAX_CONFIG_BYTES = 1024 * 1024


def _text(value, label):
    try:
        valid = isinstance(value, str) and bool(value) and len(value.encode("utf-8")) <= 512 and "\0" not in value
    except UnicodeError:
        valid = False
    if not valid:
        raise BindingError(label + " requires bounded explicit UTF-8 text")
    return value


def _available(value, label):
    if (type(value) is not dict or "error" in value or
            "ok" in value and value["ok"] is not True or
            "available" in value and value["available"] is not True or
            "status" in value and value["status"] not in ("available", "complete")):
        raise BindingError(label + " is unavailable or returned an error")


def _counts(value):
    if (type(value) is not dict or set(value) != set(COUNT_FIELDS.values()) or
            any(type(total) is not int or not 0 <= total <= 4096 for total in value.values())):
        raise BindingError("Complete bounded native catalog counts unavailable")
    return value


def read_catalog(call, expected_pid):
    """Read each category independently through a guarded, deadline-bound call.

    ``call(request)`` must invoke the native morph_provider through the caller's
    ordinary ownership guards. A failed page is terminal and is never retried.
    """
    if type(expected_pid) is not int or expected_pid <= 0:
        raise BindingError("Exact owned process identity required for native catalog")
    categories, pages, identity, counts = {}, [], None, None
    previous_frame = None
    for category, count_field in COUNT_FIELDS.items():
        names, offset = [], 0
        while True:
            page = call({"action": "catalog", "category": category, "offset": offset, "limit": 256})
            _available(page, "Native catalog page")
            if (type(page.get("pid")) is not int or page["pid"] != expected_pid or
                    page.get("schemaVersion") != 1 or type(page.get("schemaVersion")) is not int or
                    page.get("protocol") != "morph-provider/1" or
                    type(page.get("providerEpoch")) is not int or page["providerEpoch"] <= 0 or
                    type(page.get("worldGeneration")) is not int or page["worldGeneration"] <= 0 or
                    page.get("worldLoading") is not False or page.get("phase") != "skse_main_thread_task" or
                    type(page.get("frame")) is not int or page["frame"] < 0 or
                    page.get("category") != category or type(page.get("offset")) is not int or page["offset"] != offset or
                    type(page.get("limit")) is not int or page["limit"] != 256):
                raise BindingError("Native catalog process/world/category/page identity unavailable")
            page_counts = _counts(page.get("counts"))
            current_identity = (page["pid"], page["providerEpoch"], page["worldGeneration"])
            if identity is None:
                identity, counts = current_identity, copy.deepcopy(page_counts)
            if (current_identity != identity or page_counts != counts or
                    previous_frame is not None and page["frame"] < previous_frame):
                raise BindingError("Catalog changed during bounded paging")
            previous_frame = page["frame"]
            total, values = counts[count_field], page.get("names")
            if (type(values) is not list or type(page.get("returnedCount")) is not int or
                    page["returnedCount"] != len(values) or len(values) != min(256, total - offset)):
                raise BindingError("Complete bounded catalog page unavailable")
            names.extend(_text(name, "catalog name") for name in values)
            if len(set(names)) != len(names):
                raise BindingError("Catalog count/unique-name mismatch within category")
            pages.append(copy.deepcopy(page))
            if len(names) == total:
                break
            offset = len(names)
        categories[category] = names
    return {"categories": categories, "counts": counts, "providerEpoch": identity[1],
            "pid": identity[0], "worldGeneration": identity[2], "pages": pages,
            "coherence": "sampled_bounded_provider_catalog_not_configuration_or_actor_generation"}


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BindingError("Actual stock configuration contains duplicate JSON object keys")
        value[key] = item
    return value


def _nonfinite(value):
    raise BindingError("Actual stock configuration contains a non-finite JSON value: " + value)


def _local_form(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{3,8}", value):
        raise BindingError("Actual stock base mapping requires a plugin-local hexadecimal FormID")
    number = int(value, 16)
    if not 0 < number <= 0xFFFFFF:
        raise BindingError("Actual stock base mapping requires a nonzero plugin-local FormID")
    return f"0x{number:08X}"


def _pool(value):
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise BindingError("Actual stock base preset pool must be a bounded nonempty array")
    names = [_text(name, "base preset name") for name in value]
    if len(set(names)) != len(names):
        raise BindingError("Actual stock base preset pool contains duplicate names")
    return frozenset(names)


def _mappings(value):
    if type(value) is not dict:
        raise BindingError("Actual stock base mapping is missing or malformed")
    mappings, identities = {}, set()
    for plugin, forms in value.items():
        _text(plugin, "base plugin")
        if type(forms) is not dict or not forms:
            raise BindingError("Actual stock base mapping is malformed")
        for form, names in forms.items():
            form = _local_form(form)
            normalized = (plugin.casefold(), form)
            if normalized in identities:
                raise BindingError("Actual stock base mapping contains duplicate normalized identities")
            identities.add(normalized)
            mappings[(plugin, form)] = _pool(names)
    return mappings


def _expected_mappings(request, maximum_fixtures):
    policies = request.get("baseSelectionPolicy")
    if (type(maximum_fixtures) is not int or maximum_fixtures not in (6, 12) or
            type(policies) is not list or len(policies) not in (6, 12) or len(policies) > maximum_fixtures):
        raise BindingError("Complete base policy exceeds the frozen platform fixture opt-in")
    expected, identities = {}, set()
    for item in policies:
        if type(item) is not dict or set(item) != {"plugin", "baseFormId", "allowedHumanPresets"}:
            raise BindingError("Invalid complete base selection policy")
        plugin = _text(item["plugin"], "base plugin")
        form = item["baseFormId"]
        if not isinstance(form, str) or not form.startswith("0x"):
            raise BindingError("Reviewed base policy requires an explicit plugin-local FormID")
        form = _local_form(form[2:].zfill(3))
        normalized = (plugin.casefold(), form)
        if normalized in identities:
            raise BindingError("Reviewed base policy contains duplicate normalized identities")
        identities.add(normalized)
        expected[(plugin, form)] = _pool(item["allowedHumanPresets"])
    return expected


def _catalog_identities(catalog, expected_pid):
    _available(catalog, "Native preset catalog")
    categories = catalog.get("categories")
    if (type(categories) is not dict or set(categories) != set(COUNT_FIELDS) or
            type(catalog.get("providerEpoch")) is not int or catalog["providerEpoch"] <= 0 or
            type(catalog.get("pid")) is not int or catalog["pid"] != expected_pid):
        raise BindingError("Complete native four-category catalog unavailable")
    counts = _counts(catalog.get("counts"))
    observed = set()
    for category, names in categories.items():
        if type(names) is not list or len(names) != counts[COUNT_FIELDS[category]]:
            raise BindingError("Native catalog category count mismatch")
        names = [_text(name, "catalog name") for name in names]
        if len(set(names)) != len(names):
            raise BindingError("Native catalog contains duplicate names within a category")
        observed.update((category, name) for name in names)
    return observed


def _target_identities(request, requested_presets, expected_names):
    if "allowedAdditionalLoadedPresets" not in request:
        return None
    if type(requested_presets) is not list or len(requested_presets) != 6:
        raise BindingError("Pinned additional catalog requires a prior declaration of exactly six targets")
    targets, names = set(), set()
    for item in requested_presets:
        if (type(item) is not dict or set(item) != {"name", "sex", "set"} or item["sex"] not in ("male", "female")):
            raise BindingError("Target declaration requires an exact active category/name/source set")
        name = _text(item["name"], "target preset")
        _text(item["set"], "preset source set")
        if name in names:
            raise BindingError("Six target names must be unique across their declared sexes")
        names.add(name)
        targets.add((item["sex"], name))
    if names != expected_names:
        raise BindingError("Six target declarations must exactly cover the complete base policy")
    return targets


def _additional_identities(request, expected_names):
    entries = request["allowedAdditionalLoadedPresets"]
    if type(entries) is not list or len(entries) > 4096:
        raise BindingError("Additional catalog requires at most4096 explicit identities")
    additional = set()
    for item in entries:
        if (type(item) is not dict or set(item) != {"category", "name"} or
                not isinstance(item["category"], str) or item["category"] not in COUNT_FIELDS):
            raise BindingError("Additional preset requires an exact native category/name")
        name = _text(item["name"], "additional preset")
        identity = (item["category"], name)
        if identity in additional or name in expected_names:
            raise BindingError("Duplicate additional identity or target preset overlap")
        additional.add(identity)
    return additional


def _identities(values):
    return [{"category": category, "name": name} for category, name in sorted(values)]


def inspect_config(raw, request, *, expected_pid, expected_sha256, maximum_fixtures,
                   requested_presets, catalog, expected_game_path=None):
    """Validate fixed-file provenance and compare exact policy/catalog identities.

    A recognized distribution value is observed even when it differs from the
    requested value; that mismatch remains an explicit result for assertions.
    Missing/malformed provenance and unavailable catalog reads raise BindingError.
    """
    _available(raw, "Actual game-VFS stock configuration")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise BindingError("Actual VFS configuration read requires a frozen expected config SHA256")
    text = raw.get("rawText")
    try:
        encoded = text.encode("utf-8") if isinstance(text, str) else b""
    except UnicodeError as error:
        raise BindingError("Actual VFS configuration text is not UTF-8") from error
    digest = hashlib.sha256(encoded).hexdigest()
    if (type(expected_pid) is not int or expected_pid <= 0 or type(raw.get("pid")) is not int or raw["pid"] != expected_pid or
            not 1 <= len(encoded) <= MAX_CONFIG_BYTES or type(raw.get("bytes")) is not int or raw["bytes"] != len(encoded) or
            raw.get("inMemoryConfigObserved") is not False or digest != expected_sha256):
        raise BindingError("Actual game-VFS stock configuration differs from its frozen staged pin")
    path = raw.get("path")
    if (not isinstance(path, str) or "\0" in path or not PureWindowsPath(path).is_absolute() or
            any(part in (".", "..") for part in re.split(r"[/\\]", path)) or
            tuple(part.casefold() for part in PureWindowsPath(path).parts[-4:]) != tuple(part.casefold() for part in CONFIG_SUFFIX)):
        raise BindingError("Actual configuration path is not the fixed game-VFS main file")
    if expected_game_path is not None:
        game_path = PureWindowsPath(expected_game_path)
        if not game_path.is_absolute() or PureWindowsPath(path) != game_path.parent.joinpath(*CONFIG_SUFFIX):
            raise BindingError("Actual configuration path differs from the owned game VFS path")
    basis = raw.get("basis")
    if not isinstance(basis, str) or not basis or "\0" in basis:
        raise BindingError("Actual game-VFS configuration provenance basis unavailable")
    try:
        parsed = json.loads(encoded.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (ValueError, UnicodeError) as error:
        if isinstance(error, BindingError):
            raise
        raise BindingError("Actual stock configuration is not a complete JSON object") from error
    if type(parsed) is not dict or parsed.get("disablePresetDistribution") not in ("none", "all", "male", "female"):
        raise BindingError("Actual stock distribution setting is missing/unknown")
    expected = _expected_mappings(request, maximum_fixtures)
    mappings = _mappings(parsed.get("npcFormID"))
    if mappings != expected:
        raise BindingError("Actual stock base preset selections differ from the reviewed complete base policy")
    observed = _catalog_identities(catalog, expected_pid)
    expected_names = set().union(*expected.values())
    targets = _target_identities(request, requested_presets, expected_names)
    if targets is None:
        active = {name for category, name in observed if category in ("male", "female")}
        missing_targets = sorted(expected_names - active)
        missing_extras = []
        unexpected = sorted({name for _, name in observed} - expected_names)
    else:
        additional = _additional_identities(request, expected_names)
        missing_targets = _identities(targets - observed)
        missing_extras = _identities(additional - observed)
        unexpected = _identities(observed - targets - additional)
    actual = parsed["disablePresetDistribution"]
    return {"disablePresetDistribution": actual,
            "requiredDisablePresetDistributionMatch": actual == request["requiredDisablePresetDistribution"],
            "unexpectedLoadedPresetCount": len(unexpected), "missingExpectedPresetCount": len(missing_targets),
            "missingAllowedAdditionalPresetCount": len(missing_extras), "unexpectedLoadedPresets": unexpected,
            "missingExpectedPresets": missing_targets, "missingAllowedAdditionalPresets": missing_extras,
            "sha256": digest, "inMemoryConfigObserved": False, "baseSelectionMatch": True,
            "baseSelectionCount": len(mappings), "configObservationScope": "fixed_main_game_vfs_file_only",
            "includeConfigurationObserved": False, "actualVfsRead": copy.deepcopy(raw)}
