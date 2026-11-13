"""Pinned, read-only native matrix CLI adapter; no Python matrix arithmetic.

The returned graph lists active edges, not every public output. The caller must
compare ``outputs`` with its separately frozen complete public target catalog.
Native arithmetic for unavailable traits is retained as diagnostics, not proof
that the unavailable input was observed. No game or provider is contacted here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import time

from .interactive_bindings import BindingError


_PIN = re.compile(r"[0-9a-f]{64}")
_GRAPH_SCHEMA = "claw-matrix-input-graph/1"
_KINDS = frozenset(("actor-weight", "human-face", "human-height", "skee-morph"))
_MAX_RESPONSE = 2 * 1024 * 1024


def _name(value, label):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128 or
            not value.strip() or any(not 32 <= ord(char) <= 126 for char in value)):
        raise BindingError(label + " must be bounded printable ASCII without control characters")
    return value


def _path(value, label):
    if not isinstance(value, str) or not value or "\0" in value or not Path(value).is_absolute():
        raise BindingError(label + " must be an explicit absolute path")
    return str(Path(value))


def validate_config(value):
    """Validate frozen data only; execution separately verifies every file pin."""
    required = {"executable", "executableSha256", "matrix", "matrixSha256"}
    if type(value) is not dict or not required <= set(value) or set(value) - required - {"sourcePins"}:
        raise BindingError("Native evaluator requires exact executable/matrix paths and SHA256 pins")
    result = copy.deepcopy(value)
    for field in ("executable", "matrix"):
        result[field] = _path(value[field], field)
        if not isinstance(value[field + "Sha256"], str) or not _PIN.fullmatch(value[field + "Sha256"]):
            raise BindingError(field + " requires a lowercase SHA256 pin")
    source_pins = value.get("sourcePins", [])
    if type(source_pins) is not list or len(source_pins) > 64:
        raise BindingError("Native evaluator sourcePins must be a bounded explicit list")
    seen = {os.path.normcase(str(Path(result[field]).resolve())) for field in ("executable", "matrix")}
    if len(seen) != 2:
        raise BindingError("Native evaluator executable and matrix must be different files")
    result["sourcePins"] = []
    for item in source_pins:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise BindingError("Native evaluator source pins require only path and sha256")
        path = _path(item["path"], "source pin")
        identity = os.path.normcase(str(Path(path).resolve()))
        if identity in seen or not isinstance(item["sha256"], str) or not _PIN.fullmatch(item["sha256"]):
            raise BindingError("Duplicate or invalid native evaluator source pin")
        seen.add(identity)
        result["sourcePins"].append({"path": path, "sha256": item["sha256"]})
    return result


def _pins(config):
    return [{"path": config["executable"], "sha256": config["executableSha256"], "maximumBytes": 64 * 1024 * 1024},
            {"path": config["matrix"], "sha256": config["matrixSha256"], "maximumBytes": 16 * 1024 * 1024}] + [
                {**row, "maximumBytes": 16 * 1024 * 1024} for row in config["sourcePins"]]


def _verify(pins, deadline):
    for item in pins:
        if time.monotonic() >= deadline:
            raise BindingError("Native evaluator input verification exceeded its original deadline")
        path = Path(item["path"])
        try:
            with path.open("rb") as source:
                before = os.fstat(source.fileno())
                if not 0 < before.st_size <= item["maximumBytes"]:
                    raise BindingError("Native evaluator input has invalid size: " + str(path))
                digest = hashlib.sha256()
                count = 0
                while chunk := source.read(1024 * 1024):
                    if time.monotonic() >= deadline:
                        raise BindingError("Native evaluator input verification exceeded its original deadline")
                    count += len(chunk)
                    if count > item["maximumBytes"]:
                        raise BindingError("Native evaluator input grew beyond its bound: " + str(path))
                    digest.update(chunk)
                after = os.fstat(source.fileno())
            current = path.stat()
        except OSError as error:
            raise BindingError("Native evaluator pinned input unavailable: " + str(path)) from error
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if (stamp(before) != stamp(after) or stamp(after) != stamp(current) or count != before.st_size or
                digest.hexdigest() != item["sha256"]):
            raise BindingError("Native evaluator input pin changed: " + str(path))


def _float32(value, label):
    if type(value) not in (int, float):
        raise BindingError(label + " requires a finite numeric observation")
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error):
        raise BindingError(label + " cannot be represented as finite float32") from None
    if not math.isfinite(result):
        raise BindingError(label + " requires a finite float32 observation")
    return result


def _json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise BindingError("Native evaluator returned duplicate JSON keys")
            result[key] = value
        return result
    def constant(value):
        raise BindingError("Native evaluator returned nonfinite JSON: " + value)
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise BindingError("Native evaluator returned invalid strict UTF-8 JSON") from error


def _run(argv, stdin, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BindingError("Native evaluator deadline expired before execution")
    try:
        result = subprocess.run(argv, input=stdin.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=remaining, check=False, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as error:
        raise BindingError("Native evaluator execution unavailable: " + str(error)) from error
    if time.monotonic() >= deadline:
        raise BindingError("Native evaluator completed after its original deadline")
    if len(result.stdout) > _MAX_RESPONSE or len(result.stderr) > _MAX_RESPONSE:
        raise BindingError("Native evaluator response exceeds its retained evidence bound")
    try:
        diagnostics = result.stderr.decode("utf-8")
    except UnicodeError as error:
        raise BindingError("Native evaluator diagnostics are not UTF-8") from error
    if result.returncode:
        raise BindingError("Native evaluator rejected input (exit " + str(result.returncode) + "): " + diagnostics)
    return _json(result.stdout), diagnostics


def _graph(value, family):
    if (type(value) is not dict or set(value) != {"schema", "profile", "sex", "activeRules", "sources", "targets"} or
            value["schema"] != _GRAPH_SCHEMA or value["profile"] != family or value["sex"] not in ("male", "female") or
            type(value["activeRules"]) is not int or not 0 <= value["activeRules"] <= 256 or
            type(value["sources"]) is not list or len(value["sources"]) > 256 or
            type(value["targets"]) is not list or len(value["targets"]) > 64):
        raise BindingError("Native evaluator returned a foreign or malformed matrix graph")
    sources, targets = set(), set()
    for row in value["sources"]:
        if (type(row) is not dict or set(row) != {"name", "kind"} or
                not isinstance(row["kind"], str) or row["kind"] not in _KINDS):
            raise BindingError("Native evaluator graph source is malformed")
        identity = _name(row["name"], "Native graph source").casefold()
        if identity in sources:
            raise BindingError("Native evaluator graph has duplicate source identities")
        sources.add(identity)
    for name in value["targets"]:
        identity = _name(name, "Native graph target").casefold()
        if identity in targets:
            raise BindingError("Native evaluator graph has duplicate target identities")
        targets.add(identity)
    return value


def evaluate(config, family, sources, weightRaw, timeoutSeconds):
    """Evaluate actual supplied inputs through the pinned CLI under one deadline.

    ``sources`` may be available-empty. Unavailable optional traits must be
    omitted by the caller, which retains their independent availability records.
    Missing ordinary graph sources are refused, rather than silently becoming0.
    ``weightRaw`` is actual NPC weight0..100, never an inferred BodySlide value.
    """
    config = validate_config(config)
    family = _name(family, "Matrix family")
    if type(timeoutSeconds) not in (int, float) or not math.isfinite(timeoutSeconds) or not 0 < timeoutSeconds <= 30:
        raise BindingError("Native evaluator timeout must be finite and in0..30 seconds")
    deadline = time.monotonic() + timeoutSeconds
    weight = _float32(weightRaw, "Actual NPC weight")
    if not 0 <= weightRaw <= 100:
        raise BindingError("Actual NPC weight must be in0..100")
    if type(sources) is not dict or len(sources) > 256:
        raise BindingError("Native evaluator sources require a bounded explicit map")
    normalized, identities = {}, set()
    for name, value in sources.items():
        _name(name, "Source name")
        if name.casefold() in identities or name.casefold() == "$actor.weight":
            raise BindingError("Duplicate source identity or raw/normalized actor-weight conflict")
        identities.add(name.casefold())
        normalized[name] = _float32(value, "Source " + name)
    pins = _pins(config)
    _verify(pins, deadline)
    info_argv = [config["executable"], "matrix-info", config["matrix"], family]
    matrix_argv = [config["executable"], "matrix", config["matrix"], family, "--actor-weight-raw", repr(weight)]
    graph, info_diagnostics = _run(info_argv, "", deadline)
    graph = _graph(graph, family)
    # The native CLI otherwise treats absent ordinary values as observed zero.
    # Optional typed human traits intentionally remain distinguishable as absent.
    missing = [row["name"] for row in graph["sources"]
               if row["kind"] == "skee-morph" and row["name"].casefold() not in identities]
    if missing:
        raise BindingError("Native evaluator lacks observed ordinary source values: " + ", ".join(missing))
    _verify(pins, deadline)
    stdin = "".join(name + "\t" + repr(value) + "\n" for name, value in sorted(normalized.items()))
    outputs, matrix_diagnostics = _run(matrix_argv, stdin, deadline)
    _verify(pins, deadline)
    if (type(outputs) is not dict or not 1 <= len(outputs) <= 64 or
            not set(graph["targets"]) <= set(outputs)):
        raise BindingError("Native evaluator output is missing active graph targets")
    output_ids = set()
    for name, value in outputs.items():
        identity = _name(name, "Output target").casefold()
        if identity in output_ids:
            raise BindingError("Native evaluator outputs contain duplicate target identities")
        output_ids.add(identity)
        _float32(value, "Output " + name)
    if time.monotonic() >= deadline:
        raise BindingError("Native evaluator verification exceeded its original deadline")
    return {"available": True, "family": family, "inputs": {"sources": normalized, "weightRaw": weight},
            "graph": graph, "outputs": outputs,
            "diagnostics": {"info": info_diagnostics, "matrix": matrix_diagnostics},
            "provenance": {"pins": [{key: item[key] for key in ("path", "sha256")} for item in pins],
                           "commands": [info_argv, matrix_argv], "gameContacted": False,
                           "publicTargetCatalogVerified": False,
                           "targetCoverage": "all-native-emitted-outputs; caller-verifies-frozen-public-catalog"}}
