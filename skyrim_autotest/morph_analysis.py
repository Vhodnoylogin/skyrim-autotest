"""Independent arithmetic over complete observed morph snapshots; no game access.

The aggregate is an actual provider observation. Enumerated keys establish
presence/preservation; their values never replace or reconstruct that aggregate.
"""
from __future__ import annotations

import copy
import math


def _object(value, label):
    if type(value) is not dict:
        raise ValueError(f"{label}: require an observation object")
    return value


def _name(value, label):
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512 or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{label}: require a bounded explicit name")
    return value


def _number(value, label):
    if type(value) not in (int, float):
        raise ValueError(f"{label}: require a finite numeric observation")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{label}: require a finite numeric observation")
    return value


def _record(value, label):
    value = _object(value, label)
    if value.get("available") is not True or type(value.get("present")) is not bool:
        raise ValueError(f"{label}: unavailable observation or missing real presence")
    number = _number(value.get("value"), label)
    if not value["present"] and number != 0:
        raise ValueError(f"{label}: absent observation has a nonzero value")
    return value


def _keys(value, label):
    if type(value) is not list or len(value) > 256:
        raise ValueError(f"{label}: require bounded complete independent key enumeration")
    out = {}
    for entry in value:
        entry = _record(entry, label)
        key = _name(entry.get("key"), label + "/key")
        if key in out:
            raise ValueError(f"{label}: duplicate enumerated key {key}")
        out[key] = entry
    return out


def _snapshot(raw):
    raw = _object(raw, "raw")
    sources = _object(raw.get("sources"), "sources")
    own = _object(raw.get("own"), "own")
    targets = _object(raw.get("targetKeys"), "targetKeys")
    own_key = _name(raw.get("ownKey"), "ownKey")
    if not sources or len(sources) > 256 or not own or len(own) > 256 or set(targets) != set(own):
        raise ValueError("Complete bounded sources, own targets and corresponding target key enumerations required")
    source_keys, target_keys = {}, {}
    for name, entry in sources.items():
        _name(name, "source name")
        entry = _record(entry, "source/" + name)
        source_keys[name] = _keys(entry.get("keys"), "source keys/" + name)
        # This checks presence only. Numeric source aggregation remains entirely
        # independent, including cancellation and a provider's aggregation mode.
        if not entry["present"] and any(item["present"] for item in source_keys[name].values()):
            raise ValueError(f"{name}: absent source contains a present key")
    for name, entry in own.items():
        _name(name, "target name")
        entry = _record(entry, "own/" + name)
        target_keys[name] = _keys(targets[name], "target keys/" + name)
        enumerated = target_keys[name].get(own_key)
        present = enumerated is not None and enumerated["present"]
        value = enumerated["value"] if present else 0
        if present != entry["present"] or value != entry["value"]:
            raise ValueError(f"{name}: own-key observation disagrees with independent target-key enumeration")
    raw_weight = _number(raw.get("weightRaw"), "NPC raw weight")
    normalized = _number(raw.get("weightNormalized"), "NPC normalized weight")
    if not 0 <= raw_weight <= 100 or not 0 <= normalized <= 1:
        raise ValueError("NPC weight outside documented units; unknown -1 remains unavailable")
    _name(raw.get("stage"), "stage")
    return raw, source_keys, target_keys


def evaluate(raw, rows, publicTargets):
    """Return full independent vectors and nested semantic observation metrics.

    All configured sources/public targets and each independent key enumeration
    are mandatory. Missing/unavailable observations raise ValueError. The return
    retains a deep copy under ``raw`` for later exact snapshot comparisons.
    """
    raw, source_keys, unused = _snapshot(raw)
    if type(publicTargets) not in (list, tuple) or not 1 <= len(publicTargets) <= 256:
        raise ValueError("publicTargets: require the complete bounded public target list")
    public = [_name(name, "public target") for name in publicTargets]
    if len(public) != len(set(public)) or set(raw["own"]) != set(public):
        raise ValueError("Duplicate public targets or incomplete/extraneous own-key target coverage")
    if type(rows) not in (list, tuple) or not 1 <= len(rows) <= 2048:
        raise ValueError("rows: require a nonempty bounded mapping")
    terms, caps, contributions, source_names = {}, {}, [], set()
    for index, row in enumerate(rows):
        row = _object(row, f"row {index}")
        source = _name(row.get("sourceMorph"), "row source")
        target = _name(row.get("targetMorph"), "row target")
        if source not in raw["sources"] or target not in public:
            raise ValueError("Mapping references an unobserved source or nonpublic target")
        gain = _number(row.get("gain"), "row gain")
        cap = _number(row.get("cap"), "row cap")
        if cap < 0 or (target in caps and cap != caps[target]):
            raise ValueError("Negative or inconsistent target cap")
        aggregate = raw["sources"][source]["value"]
        contribution = _number(aggregate * gain, "signed contribution")
        terms.setdefault(target, []).append(contribution)
        caps[target] = cap
        source_names.add(source)
        contributions.append({"rowIndex": index, "source": source, "target": target,
                              "actualAggregate": aggregate, "gain": gain, "cap": cap,
                              "signedContribution": contribution})
    if source_names != set(raw["sources"]):
        raise ValueError("Raw source coverage differs from the complete configured source set")
    try:
        sums = {target: _number(math.fsum(values), "raw target sum") for target, values in terms.items()}
    except OverflowError as error:
        raise ValueError("Nonfinite raw target sum") from error
    expected = {target: _number(min(1.0, max(0.0, sums.get(target, 0.0))) * caps.get(target, 0.0),
                                "expected target coefficient") for target in public}
    if raw["stage"] in ("human-own-clear", "suppressed-own-clear"):
        expected = dict.fromkeys(public, 0.0)
    actual = {name: raw["own"][name]["value"] for name in public}
    errors = {name: _number(abs(actual[name] - expected[name]), "absolute target error") for name in public}
    aggregates = [raw["sources"][name] for name in source_names]
    return {
        "sex": raw.get("sex"), "familyId": raw.get("familyId"), "stage": raw["stage"],
        "mapping": {"evaluatedTargetCount": len(public), "maxAbsoluteError": max(errors.values()),
                    "unmappedOwnMaxAbsolute": max((abs(actual[name]) for name in public if name not in terms), default=0.0)},
        "sources": {"count": len(source_names), "aggregateReadCount": len(source_names), "unavailableReadCount": 0,
                    "negativeAggregateCount": sum(item["value"] < 0 for item in aggregates),
                    "zeroAggregateCount": sum(item["value"] == 0 for item in aggregates),
                    "zeroPresentAggregateCount": sum(item["value"] == 0 and item["present"] for item in aggregates),
                    "absentAggregateCount": sum(not item["present"] for item in aggregates),
                    "multipleKeySourceCount": sum(sum(item["present"] for item in keys.values()) > 1 for keys in source_keys.values())},
        "own": {"count": len(public), "targetReadCount": len(public), "unavailableReadCount": 0,
                "maxAbsoluteCoefficient": max(abs(value) for value in actual.values())},
        "actor": {"weightRaw": raw["weightRaw"], "weightNormalized": raw["weightNormalized"],
                  "weightNormalizationAbsoluteError": abs(raw["weightNormalized"] - raw["weightRaw"] / 100)},
        "expected": expected, "actualOwnKey": actual, "absoluteErrors": errors,
        "contributions": contributions, "rawTargetSums": sums,
        "sourceAggregationWasReconstructedFromKeys": False,
        "renderedGeometryOrPhysicsAccepted": False, "raw": copy.deepcopy(raw),
    }


def _comparison_snapshot(value):
    value = _object(value, "comparison snapshot")
    raw = value.get("raw", value)
    raw, source_keys, target_keys = _snapshot(raw)
    expected = _object(value.get("expected"), "independently evaluated expected vector")
    if set(expected) != set(raw["own"]):
        raise ValueError("Comparison requires independently evaluated expected values for every public target")
    for name, number in expected.items():
        _number(number, "expected/" + name)
    return raw, source_keys, target_keys, expected


def _absent():
    return {"available": True, "present": False, "value": 0.0}


def _different(before, after):
    return before["present"] != after["present"] or before["value"] != after["value"]


def _diff(before, after, **identity):
    return {**identity, "before": copy.deepcopy(before), "after": copy.deepcopy(after)}


def compare(before, after):
    """Compare evaluate() results; preserve full values and presence in each diff.

    Raw input is also accepted when it carries an independently evaluated
    ``expected`` vector. Missing key entries imply absence only within the complete
    validated enumeration, never from an unavailable read or missing morph name.
    """
    left, left_sources, left_targets, left_expected = _comparison_snapshot(before)
    right, right_sources, right_targets, right_expected = _comparison_snapshot(after)
    if (set(left["sources"]) != set(right["sources"]) or set(left["own"]) != set(right["own"]) or
            left["ownKey"] != right["ownKey"]):
        raise ValueError("Snapshots differ in source/public-target coverage or own-key identity")
    differences = {"sourceAggregates": [], "sourceKeys": [], "ownTargets": [],
                   "expectedTargets": [], "targetKeys": [], "foreignTargetKeys": []}
    for name in sorted(left["sources"]):
        old, new = left["sources"][name], right["sources"][name]
        if _different(old, new):
            differences["sourceAggregates"].append(_diff(old, new, morph=name))
        old_keys, new_keys = left_sources[name], right_sources[name]
        for key in sorted(set(old_keys) | set(new_keys)):
            old, new = old_keys.get(key, _absent()), new_keys.get(key, _absent())
            if _different(old, new):
                differences["sourceKeys"].append(_diff(old, new, morph=name, key=key))
    for name in sorted(left["own"]):
        old, new = left["own"][name], right["own"][name]
        if _different(old, new):
            differences["ownTargets"].append(_diff(old, new, morph=name, key=left["ownKey"]))
        if left_expected[name] != right_expected[name]:
            differences["expectedTargets"].append({"morph": name, "before": left_expected[name], "after": right_expected[name]})
        old_keys, new_keys = left_targets[name], right_targets[name]
        for key in sorted(set(old_keys) | set(new_keys)):
            old, new = old_keys.get(key, _absent()), new_keys.get(key, _absent())
            if _different(old, new):
                item = _diff(old, new, morph=name, key=key)
                differences["targetKeys"].append(item)
                if key != left["ownKey"]:
                    differences["foreignTargetKeys"].append(copy.deepcopy(item))
    return {
        "comparison": {"changedActualHumanSourceCount": len(differences["sourceAggregates"]),
                       "changedAggregateCount": len(differences["sourceAggregates"]),
                       "changedSourceKeyEntryCount": len(differences["sourceKeys"]),
                       "changedFullSourceKeyEntryCount": len(differences["sourceKeys"]),
                       "changedExpectedTargetCount": len(differences["expectedTargets"]),
                       "changedOwnTargetEntryCount": len(differences["ownTargets"])},
        "preservation": {"changedHumanKeyEntryCount": len(differences["sourceKeys"]),
                         "changedForeignTargetEntryCount": len(differences["foreignTargetKeys"])},
        "beforeSnapshot": left.get("snapshotLabel", left.get("snapshot")),
        "afterSnapshot": right.get("snapshotLabel", right.get("snapshot")),
        "rawDiffs": differences,
    }
