"""Opt-in SE matrix lifecycle over owned NPCs, without an OBody dependency.

SKEE/weight observations, subject cached diagnostics and external native
predictions retain distinct provenance. This module never implements morph math.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct

from . import actor_domain, fixture_actors, interactive_bindings as bindings
from . import morph_session, npc_persistence
from .native_session import settings as native_settings
from .interactive_bindings import BindingError
from .platform import Backend


DOMAIN = "actor-matrix-state"
REUSED = frozenset(("actor-fixture", "actor-fixture-identity", "actor-race", "morph-link", "save-state"))
SIGNATURES = {
    "status": ([], "int", "read"), "error": ([], "string", "read"),
    "humanWeight": ([], "float", "read"), "beastWeight": ([], "float", "read"),
    "hasHumanTrait": (["string"], "bool", "read"),
    "getHumanTrait": (["string"], "float", "read"),
    "configure": (["string"], "bool", "mutate"),
    "refresh": ([], "bool", "mutate"), "clear": ([], "bool", "mutate"),
    "race": (["race"], "none", "mutate"),
}


def _names(value, label, minimum=0, maximum=256):
    if (type(value) is not list or not minimum <= len(value) <= maximum or
            any(not isinstance(v, str) for v in value) or len({v.casefold() for v in value}) != len(value)):
        raise BindingError(label + " requires a bounded unique explicit catalog")
    for name in value:
        morph_session._text(name, label)
        if any(ord(c) < 32 or ord(c) > 126 for c in name):
            raise BindingError(label + " requires printable ASCII provider identities")
    return value


def validate_config(value, policy=None):
    if value is None:
        return None
    required = {"maximumFixtures", "bindings", "sourceMorphs", "traitSources", "publicTargets", "ownKey", "evaluator", "beastRace"}
    if type(value) is not dict or not required <= set(value) or set(value) - required - {'counterfactualSourceMorphs'} or type(value["maximumFixtures"]) is not int or value["maximumFixtures"] != 2:
        raise BindingError("matrixLifecycle requires its exact fields and explicit maximumFixtures:2")
    source = _names(value["sourceMorphs"], "sourceMorphs")
    counterfactual = _names(value.get('counterfactualSourceMorphs', []), 'counterfactualSourceMorphs')
    targets = _names(value["publicTargets"], "publicTargets", 1, 64)
    if any(name.startswith("$") for name in source + targets + counterfactual):
        raise BindingError("SKEE source/target catalogs cannot contain typed scalar names")
    traits = _names(value["traitSources"], "traitSources", 0, 32)
    if any(not (name == "$human.height" or name.startswith("$human.face.")) for name in traits):
        raise BindingError("Traits must use the explicit human scalar namespace")
    morph_session._text(value["ownKey"], "ownKey")
    beast_race = actor_domain.form(value["beastRace"])
    mapping = value["bindings"]
    if (type(mapping) is not dict or not set(SIGNATURES) <= set(mapping) or
            set(mapping) - set(SIGNATURES) - {"selectedFamily"}):
        raise BindingError("matrixLifecycle requires exact typed binding roles")
    if any(not isinstance(v, str) or not v for v in mapping.values()) or len(set(mapping.values())) != len(mapping):
        raise BindingError("Matrix role bindings must be distinct explicit identifiers")
    if policy is not None:
        frozen = bindings.validate(policy)
        if frozen is None:
            raise BindingError("Matrix lifecycle requires frozen native bindings")
        if beast_race not in frozen['allowedRaceForms']:
            raise BindingError('Matrix beast race must be in the frozen race allowlist')
        by_id = {entry["id"]: entry for entry in frozen["bindings"]}
        for role, identifier in mapping.items():
            entry = by_id.get(identifier)
            extras, returned, effect = SIGNATURES.get(role, ([], "string", "read"))
            if (entry is None or entry["effect"] != effect or entry["returnType"] != returned or
                    len(entry["actorArgs"]) + int(entry["actorSelf"]) != 1 or
                    [kind for i, kind in enumerate(entry["params"]) if i not in entry["actorArgs"]] != extras or
                    (role == "race" and entry["completion"] != "actor-race")):
                raise BindingError("Matrix binding signature differs from role " + role)
    from . import matrix_evaluator
    result = copy.deepcopy(value)
    result['beastRace'] = beast_race
    result["evaluator"] = matrix_evaluator.validate_config(value["evaluator"])
    return result


def validate(operation, request):
    if type(request) is not dict or request.get("domain") != DOMAIN:
        return False
    required = {"domain", "actor", "stage", "captureSnapshot", "familyId"}
    if (operation != "world.read" or not required <= set(request) or
            set(request) - required - {"baselineSnapshot", "counterfactual"} or
            request["stage"] not in ("human", "beast")):
        raise BindingError("Matrix observation requires exact actor/stage/snapshot/family fields")
    morph_session._actor(request["actor"])
    morph_session._tag(request["captureSnapshot"])
    morph_session._text(request["familyId"], "familyId")
    if request["stage"] == "beast" and "baselineSnapshot" not in request:
        raise BindingError("Beast prediction requires a witnessed human baseline snapshot")
    if "baselineSnapshot" in request:
        morph_session._tag(request["baselineSnapshot"])
        if request["baselineSnapshot"] == request["captureSnapshot"]:
            raise BindingError("Current and baseline snapshot identities must differ")
    if "counterfactual" in request:
        cf = request["counterfactual"]
        if type(cf) is not dict or not cf or set(cf) - {"sources", "weightRaw"}:
            raise BindingError("Counterfactual accepts only separate source overrides/weight")
        if "weightRaw" in cf:
            actor_domain.bounded(cf["weightRaw"], 0, 100)
        if "sources" in cf:
            if type(cf["sources"]) is not dict or len(cf["sources"]) > 256:
                raise BindingError("Bounded ordinary source overrides required")
            for name, value in cf["sources"].items():
                morph_session._text(name, "counterfactual source")
                actor_domain.bounded(value, -1e100, 1e100)
    return True


def enabled(configuration):
    return native_settings(configuration).get("matrixLifecycle") is not None


def _state(session):
    return session.state.setdefault("matrixLifecycle", {"fixtures": {}, "snapshots": {}, "mutations": []})


def _begin(session, request):
    command = session.state.get("activeSemanticCommandId")
    if not isinstance(command, str) or not 1 <= len(command) <= 128 or "\0" in command:
        raise BindingError("Matrix mutations require the durable owned semantic command identity")
    state = _state(session)
    if any(row["commandId"] == command for row in state["mutations"]):
        raise BindingError("Matrix command already attempted; never replay")
    intent = {"commandId": command, "request": copy.deepcopy(request), "status": "intent"}
    state["mutations"].append(intent)
    session.save()
    return intent


def _fixture(session, tag):
    entry = session.state.get("interactiveActorFixtures", {}).get(tag)
    record = _state(session)["fixtures"].get(tag)
    if not isinstance(entry, dict) or not isinstance(record, dict) or record.get("creationId") != entry.get("creationId"):
        raise BindingError("Matrix actor has no matching adapter-owned creation witness")
    spec = {"reference": entry.get("reference"), "base": entry.get("base")}
    fixture_actors.require_fixture(session, spec)
    return entry, spec


def _binding(session, config, policy, role, spec, deadline, extras=()):
    unused, request = morph_session._binding_request(policy, config, role, spec, extras)
    return bindings.guarded_call(session, request, deadline, policy)


def _value(session, config, policy, role, spec, deadline, extras=()):
    return _binding(session, config, policy, role, spec, deadline, extras)["returned"]


def _same_bits(a, b):
    try:
        return struct.pack("<f", a) == struct.pack("<f", b)
    except (OverflowError, struct.error):
        return False


def observe(backend, config, policy, request):
    session = backend.s
    state = _state(session)
    tag = morph_session._actor(request["actor"])
    entry, spec = _fixture(session, tag)
    label = request["captureSnapshot"]
    if label in state["snapshots"]:
        raise BindingError("Snapshot already retained; select a new observation label")
    names = list(dict.fromkeys(config["sourceMorphs"] + config["publicTargets"]))
    measured, identity, raw = morph_session._read_morphs(backend, spec, names)
    human_race = state['fixtures'][tag].get('humanRace')
    actual_race = actor_domain.form(identity['actor'].get('race'))
    expected_race = human_race if request['stage'] == 'human' else config['beastRace']
    if not human_race or human_race == config['beastRace'] or actual_race != expected_race:
        raise BindingError('Matrix stage differs from witnessed original human/current beast race')
    weight = identity["actor"]["weight"]
    actual_weight = actor_domain.bounded(weight["rawNPCWeight"], 0, 100)
    normalized = actor_domain.bounded(weight["normalizedNPCWeight"], 0, 1)
    if not math.isclose(normalized, actual_weight / 100, rel_tol=0, abs_tol=1e-7):
        raise BindingError("Independent raw/normalized actor weights disagree")
    diagnostic = {role: _value(session, config, policy, role, spec, backend.end)
                  for role in ("status", "error", "humanWeight", "beastWeight")}
    traits = {}
    for name in config["traitSources"]:
        available = _value(session, config, policy, "hasHumanTrait", spec, backend.end, [name])
        value = _value(session, config, policy, "getHumanTrait", spec, backend.end, [name])
        confirmed = _value(session, config, policy, "hasHumanTrait", spec, backend.end, [name])
        if type(available) is not bool or confirmed is not available:
            raise BindingError("Human trait availability changed during observation")
        if available:
            actor_domain.bounded(value, -1e100, 1e100)
        traits[name] = {"available": available, "value": value if available else None,
                        "rawReturned": value, "basis": "subject-cached-human-trait; not independent engine measurement"}
    family = {"available": False, "value": None, "reason": "No qualified selected-family read binding configured"}
    if "selectedFamily" in config["bindings"]:
        value = _value(session, config, policy, "selectedFamily", spec, backend.end)
        morph_session._text(value, "selectedFamily", empty=True)
        family = {"available": bool(value), "value": value or None, "basis": "actual typed subject native callback"}
    family['matchesRequested'] = family['available'] and family['value'] == request['familyId']
    final, final_identity, final_raw = morph_session._read_morphs(backend, spec, names)
    if identity != final_identity or measured != final:
        raise BindingError("Actor/model/world or SKEE values changed during sequential matrix observation")
    sources = {name: copy.deepcopy(measured[name]) for name in config["sourceMorphs"]}
    baseline = None
    if "baselineSnapshot" in request:
        baseline = state["snapshots"].get(request["baselineSnapshot"])
        if (not isinstance(baseline, dict) or baseline.get("fixtureTag") != tag or
                baseline.get("creationId") != entry["creationId"] or baseline.get("stage") != "human" or
                baseline.get("familyId") != request["familyId"] or baseline.get("game") != session.state["game"]):
            raise BindingError("A same-actor/process/family witnessed human baseline is required")
    input_sources = baseline["sources"] if baseline else sources
    input_weight = baseline["weightRaw"] if baseline else actual_weight
    input_traits = baseline["traits"] if baseline else traits
    values = {name: record["value"] for name, record in input_sources.items()}
    values.update({name: row["value"] for name, row in input_traits.items() if row["available"]})
    from . import matrix_evaluator
    prediction = matrix_evaluator.evaluate(config["evaluator"], request["familyId"], values, input_weight, backend.remaining())
    if set(prediction["outputs"]) != set(config["publicTargets"]):
        raise BindingError("Native output does not cover the complete configured public target catalog")
    graph_sources = prediction["graph"].get("sources", [])
    for source in graph_sources:
        if source["kind"] == "skee-morph" and source["name"] not in config["sourceMorphs"]:
            raise BindingError("Native graph requires an unobserved ordinary source")
        if source["kind"] in ("human-face", "human-height") and source["name"] not in config["traitSources"]:
            raise BindingError("Native graph requires an undeclared human trait")
    targets = {}
    for name in config["publicTargets"]:
        observed = measured[name]
        matches = [row for row in observed["keys"] if row["key"].casefold() == config["ownKey"].casefold()]
        if len(matches) > 1:
            raise BindingError("Own morph key has ambiguous case-insensitive identity")
        actual = matches[0]["value"] if matches else 0.0
        expected = prediction["outputs"][name] if request["stage"] == "beast" else 0.0
        targets[name] = {"expected": expected, "ownValue": actual, "ownKeyPresent": bool(matches),
                         "namePresent": observed["present"], "aggregate": observed["value"],
                         "keys": copy.deepcopy(observed["keys"]), "float32Exact": _same_bits(actual, expected)}
    result = {"actor": {"reference": spec["reference"], "base": spec["base"], "identity": identity,
                         "weightRaw": actual_weight, "weightNormalized": normalized},
        "matrix": {"stage": request["stage"], "selectedFamily": family, "requestedFamily": request["familyId"],
                   "sources": sources, "sourceCatalogComplete": True, "sourceScope": "explicit configured names, not global name discovery",
                   "traits": traits, "targets": targets, "nativePrediction": prediction,
                   "publicTargetCount": len(targets), "mismatchCount": sum(not row["float32Exact"] for row in targets.values()),
                   "ownKeyPresentCount": sum(row['ownKeyPresent'] for row in targets.values()),
                   "zeroExpectedOwnKeyPresentCount": sum(row['ownKeyPresent'] and row['expected'] == 0 for row in targets.values()),
                   "sourcePreserved": sources == baseline["sources"] if baseline else None,
                   "traitsPreserved": traits == baseline["traits"] if baseline else None,
                   "weightPreserved": _same_bits(actual_weight, baseline["weightRaw"]) if baseline else None,
                   "inputBaseline": request.get("baselineSnapshot"),
                   "inputTraits": copy.deepcopy(input_traits),
                   "ordinarySourceMapAvailable": True, "ordinarySourceMapEmpty": not sources,
                   "subjectDiagnostics": diagnostic, "atomicSnapshot": False},
        "providerObservations": raw + final_raw}
    if "counterfactual" in request:
        cf = request["counterfactual"]
        overrides = cf.get("sources", {})
        if set(overrides) - (set(config["sourceMorphs"]) | set(config.get('counterfactualSourceMorphs', []))):
            raise BindingError("Counterfactual cannot override typed/unobserved ordinary sources")
        altered = dict(values, **overrides)
        result["matrix"]["counterfactual"] = matrix_evaluator.evaluate(config["evaluator"], request["familyId"], altered,
            cf.get("weightRaw", input_weight), backend.remaining())
        result['matrix']['counterfactual']['basis'] = 'explicit hypothetical native evaluator inputs, not observed SKEE or game mutations'
    # A CLI call cannot replace the game/fixture check after offline work.
    latest, latest_identity, latest_raw = morph_session._read_morphs(backend, spec, names)
    if latest_identity != identity or latest != measured:
        raise BindingError("Game observation changed while the external evaluator ran")
    result["providerObservations"].extend(latest_raw)
    missing = any(not row['available'] for row in list(traits.values()) + list(input_traits.values()))
    result["matrix"]["availability"] = "partial" if not family["available"] or missing else "complete"
    result['matrix']['nativeParityAvailable'] = family['matchesRequested'] and not missing
    snapshot = {"fixtureTag": tag, "creationId": entry["creationId"], "game": copy.deepcopy(session.state["game"]),
                "stage": request["stage"], "familyId": request["familyId"], "sources": sources, "traits": traits,
                "weightRaw": actual_weight, "identity": identity,
                "resultSha256": hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()}
    state["snapshots"][label] = snapshot
    session.log("matrix-lifecycle-observation", request=request, result=result)
    session.save()
    return result


def execute(session, args, deadline, policy):
    if type(args) is not dict or not morph_session.validate(args.get('operation'), args.get('request')):
        raise BindingError('Invalid matrix lifecycle semantic request')
    frozen = bindings.frozen_policy(session, policy)
    configuration = session.state.get("configuration", {})
    config = validate_config(native_settings(configuration).get("matrixLifecycle"), frozen)
    if configuration.get("game_edition") != "se" or config is None:
        raise BindingError("Matrix lifecycle requires the explicit frozen SE opt-in")
    backend = Backend(session, deadline)
    fixture_actors._owned(backend, session.state.get("game"))
    request = args["request"]
    domain, action = request["domain"], request.get("action")
    state = _state(session)
    owned = session.state.get('interactiveActorFixtures', {})
    if not isinstance(owned, dict) or set(owned) != set(state['fixtures']):
        raise BindingError('Matrix roster must contain all and only its own creation attempts')
    for tag in state['fixtures']:
        _fixture(session, tag)
    if domain == DOMAIN:
        return observe(backend, config, frozen, request)
    if domain == 'actor-fixture-inspection':
        from . import actor_inspection
        return actor_inspection.execute(session, args, deadline, frozen)
    if domain not in REUSED:
        raise BindingError("Domain is outside the OBody-free matrix lifecycle")
    if domain == "save-state":
        if action is None:
            return npc_persistence.observe(session, {"saveTag": request["saveLabel"]}, deadline, frozen)
        translated = {"action": "save" if action == "save-disposable-once" else "load", "saveTag": request["saveLabel"]}
        if translated["action"] == "save":
            translated["fixtureTags"] = request["actors"]
        intent = _begin(session, request)
        result = npc_persistence.perform(session, translated, deadline, frozen)
    elif domain == "actor-fixture":
        tag = morph_session._actor(request["actor"])
        if request["maximumCreations"] != 2 or tag in state["fixtures"] or len(state["fixtures"]) >= 2:
            raise BindingError("Matrix fixture requires at most two once-only creation attempts")
        base = actor_domain.form(backend.resolve({"plugin": request["base"]["plugin"], "localId": f'{int(request["base"]["formId"],16):06X}'}))
        if base not in frozen["fixtureActorBases"]:
            raise BindingError("Matrix fixture base is outside the frozen whitelist")
        intent = _begin(session, request)
        state["fixtures"][tag] = {"status": "creation-intent"}
        session.save()
        result = fixture_actors.create(session, {"tag": tag, "base": base, **request["placement"], "persistentForOwnedSave": True}, deadline, frozen)
        entry = session.state["interactiveActorFixtures"][tag]
        human_race = actor_domain.form(entry.get('actor', {}).get('race'))
        if human_race == config['beastRace']:
            raise BindingError('Matrix fixture was not created in a human race')
        state["fixtures"][tag].update(status="created", creationId=entry["creationId"], humanRace=human_race)
    else:
        tag = morph_session._actor(request["actor"])
        entry, spec = _fixture(session, tag)
        if domain == "actor-fixture-identity":
            observed = fixture_actors.guard(session, spec, deadline, frozen)
            return {"actor": observed["actor"], "creationWitness": copy.deepcopy(entry["creationWitness"]),
                    "restorationWitness": copy.deepcopy(entry.get("restorationWitness"))}
        role = "race" if domain == "actor-race" else {"clear-own": "clear", "refresh": "refresh", "bind-resource-family": "configure"}[action]
        if role == 'race' and actor_domain.form(request['race']) not in (state['fixtures'][tag]['humanRace'], config['beastRace']):
            raise BindingError('Matrix race change must use its witnessed human or configured beast race')
        extras = [request["race"]] if role == "race" else [request["familyId"]] if role == "configure" else []
        intent = _begin(session, request)
        result = _binding(session, config, frozen, role, spec, deadline, extras)
        if role != "race":
            result = {"request": {"admitted": result["returned"], "completed": False}, "bindingReceipt": result}
    intent.update(status="returned")
    session.save()
    return result
