"""Single-attempt disposable NPC creation with durable same-run witnesses.

No photography, inventory, console, AI/collision disable, adoption or replay path.
"""
from __future__ import annotations

import copy
from contextlib import nullcontext
import hashlib
import json
import math
import re
import time
import uuid

from . import actor_domain, native
from .api_contract import validate_description
from .interactive_bindings import BindingError, _native_call, bounded_deadline, frozen_policy, validate
from .platform import Backend
from .readiness_state import gameplay_ready


PLAYER = {"reference": "0x00000014", "base": "0x00000007"}
_SIGNATURES = {
    "ObjectReference": {
        "PlaceAtMe": (["form", "int", "bool", "bool"], "objectreference"),
        "MoveTo": (["objectreference", "float", "float", "float", "bool"], "none"),
        "SetAngle": (["float", "float", "float"], "none"),
        **{name: ([], "float") for name in ("GetPositionX", "GetPositionY", "GetPositionZ", "GetAngleZ")},
    },
    "Actor": {"GetActorBase": ([], "actorbase"), "GetRace": ([], "race"), "SetDontMove": (["bool"], "none")},
    "ActorBase": {"GetSex": ([], "int"), "GetRace": ([], "race"), "GetWeight": ([], "float")},
}


def validate_request(request, policy):
    policy = validate(policy)
    if policy is None:
        raise BindingError("Fixture creation requires explicit nativeBindings policy")
    required = {"tag", "base", "forwardGameUnits", "rightGameUnits"}
    if (type(request) is not dict or not required <= set(request) or
            set(request) - required - {"persistentForOwnedSave"}):
        raise BindingError("Fixture creation requires exact tag, base and player-relative offsets")
    if "persistentForOwnedSave" in request and type(request["persistentForOwnedSave"]) is not bool:
        raise BindingError("persistentForOwnedSave requires an explicit Bool")
    tag = request["tag"]
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", tag):
        raise BindingError("Fixture tag must be one bounded explicit identifier")
    base = actor_domain.form(request["base"])
    if base == PLAYER["base"] or base not in policy["fixtureActorBases"]:
        raise BindingError("Fixture base is outside the disposable-NPC whitelist")
    forward = actor_domain.bounded(request["forwardGameUnits"], 0, 1000)
    right = actor_domain.bounded(request["rightGameUnits"], -1000, 1000)
    if not 50 <= math.hypot(forward, right) <= 1000:
        raise BindingError("Player-relative fixture distance must be 50..1000 game units")
    result = {"tag": tag, "base": base, "forwardGameUnits": float(forward), "rightGameUnits": float(right)}
    if "persistentForOwnedSave" in request:
        result["persistentForOwnedSave"] = request["persistentForOwnedSave"]
    return result


def require_fixture(session, spec, observation=None):
    """Check a trusted creation record, never create/adopt one from caller data."""
    spec = actor_domain.actor_spec(spec)
    records = session.state.get("interactiveActorFixtures")
    if not isinstance(records, dict):
        raise BindingError("Actor has no same-run creation witness")
    matches = [entry for entry in records.values() if isinstance(entry, dict) and entry.get("reference") == spec["reference"]]
    if len(matches) != 1:
        raise BindingError("Actor does not have one exact owned creation witness")
    entry = matches[0]
    witness = entry.get("creationWitness", {})
    original_reference = entry.get("createdReference", spec["reference"])
    if original_reference != spec["reference"] or "restorationWitness" in entry:
        from .npc_persistence import require_restoration
        require_restoration(session, entry)
    if (spec["reference"] == PLAYER["reference"] or int(spec["reference"], 16) >> 24 != 0xFF or
            entry.get("status") != "created" or entry.get("base") != spec["base"] or
            not isinstance(session.state.get("id"), str) or entry.get("runId") != session.state["id"] or
            entry.get("game") != session.state.get("game") or
            type(entry.get("worldGeneration")) is not int or entry["worldGeneration"] <= 0 or
            entry["worldGeneration"] != session.state.get("ownedWorldGeneration") or
            not isinstance(entry.get("creationId"), str) or not re.fullmatch(r"[0-9a-f]{32}", entry["creationId"]) or
            not isinstance(witness, dict) or witness.get("method") != "ObjectReference.PlaceAtMe" or
            witness.get("runId") != entry["runId"] or witness.get("creationId") != entry["creationId"] or
            witness.get("reference") != original_reference or witness.get("base") != spec["base"] or
            witness.get("anchor") != PLAYER["reference"] or type(witness.get("count")) is not int or witness["count"] != 1 or
            witness.get("nativeReturned") is not True or
            type(witness.get("priorActorCount")) is not int or witness["priorActorCount"] < 0 or
            not isinstance(witness.get("priorActorsSha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", witness["priorActorsSha256"])):
        raise BindingError("Actor creation witness is incomplete, foreign, stale or uncertain")
    if observation is not None:
        actor = observation.get("actor", {})
        if (observation.get("incarnation") != entry.get("incarnation") or actor.get("reference") != spec["reference"] or
                actor.get("base") != spec["base"] or actor.get("loaded3D") is not True or
                actor.get("sex") != entry.get("actor", {}).get("sex")):
            raise BindingError("Actual actor differs from its created reference/base/sex/loaded 3D/incarnation witness")
    return entry


def _owned(backend, game):
    state = backend.s.state
    if (not game or state.get("game") != game or not native.alive(game) or not state.get("testProfile") or
            state.get("gameplayBootstrap", {}).get("completed") is not True or
            type(state.get("ownedWorldGeneration")) is not int or state["ownedWorldGeneration"] <= 0):
        raise BindingError("Fixture operation requires the exact owned disposable gameplay world")
    backend.remaining()
    backend.guard_world()
    backend.remaining()


def guard(session, spec, deadline, policy):
    """Reusable actual witness guard for existing semantic NPC mutations."""
    policy = frozen_policy(session, policy)
    bounded_deadline(deadline)
    spec = actor_domain.actor_spec(spec)
    if spec["base"] not in policy["fixtureActorBases"]:
        raise BindingError("Actor base is outside the frozen fixture allowlist")
    require_fixture(session, spec)
    backend = Backend(session, deadline)
    game = copy.deepcopy(session.state.get("game"))
    _owned(backend, game)
    observed = actor_domain.observe_actor(backend, spec)
    require_fixture(session, spec, observed)
    _owned(backend, game)
    return observed


def _qualify(backend):
    for script, methods in _SIGNATURES.items():
        description = backend.call("papyrus", {"action": "describe", "script": script})
        for function, (params, return_type) in methods.items():
            # Stock Actor.GetActorBase is a zero-argument Papyrus read wrapper,
            # observed native:false in the retained SE qualification metadata.
            # This exception does not admit scripted setters or other getters.
            read_wrapper = (script, function) == ("Actor", "GetActorBase")
            rows = description.get("memberFunctions") if isinstance(description, dict) else None
            matches = [row for row in rows or [] if isinstance(row, dict) and str(row.get("name", "")).casefold() == function.casefold()]
            actual = {"script": description.get("name") if isinstance(description, dict) else None,
                      "matches": [{"params": row.get("params"), "returnType": row.get("returnType"), "native": row.get("native")} for row in matches]}
            expected = {"script": script, "scope": "memberFunctions", "params": params, "returnType": return_type,
                        "native": "true or false for this stock read wrapper only" if read_wrapper else True}
            reason = f"Fixture API metadata mismatch for {script}.{function}: actual={actual!r}; expected={expected!r}"
            if len(matches) != 1:
                raise BindingError(reason)
            try:
                item = validate_description(script, description, "memberFunctions", {function: params})[0]
            except (AssertionError, AttributeError, TypeError) as error:
                raise BindingError(reason) from error
            native_flag = item["native"]
            if (not (native_flag is True or (read_wrapper and native_flag is False)) or
                    str(item["returnType"]).casefold() != return_type):
                raise BindingError(reason)


def _pose(backend, ref):
    xyz = [actor_domain.bounded(backend.pap("ObjectReference", "GetPosition" + axis, target=ref), -1e7, 1e7) for axis in "XYZ"]
    angle = actor_domain.bounded(backend.pap("ObjectReference", "GetAngleZ", target=ref), -36000, 36000)
    return xyz, float(angle % 360)


def _persistent_identity(backend, spec, observation, expected=None):
    """Actual native persistence and VM object correspondence, never an argument echo."""
    raw = backend.call("npc_persistence", {"action": "identity", **spec,
        "timeoutMs": max(1, min(5000, int(backend.remaining() * 1000)))})
    backend.remaining()
    handle = raw.get("currentVmHandle") if isinstance(raw, dict) else None
    if (not isinstance(raw, dict) or raw.get("protocol") != "npc-persistence/1" or
            type(raw.get("pid")) is not int or raw["pid"] != backend.s.state["game"]["pid"] or
            not isinstance(raw.get("providerSession"), str) or not 1 <= len(raw["providerSession"]) <= 128 or
            raw.get("persistent") is not True or raw.get("currentReference") != spec["reference"] or
            raw.get("base") != spec["base"] or type(raw.get("runtimeHandle")) is not int or
            raw["runtimeHandle"] != observation["incarnation"]["runtimeHandle"] or
            not isinstance(handle, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", handle) or int(handle) >= 2**64):
        raise BindingError("Actual persistent native reference/VM identity is unavailable")
    identity = {key: raw[key] for key in ("protocol", "pid", "providerSession", "persistent", "currentReference", "base",
                                         "currentVmHandle", "runtimeHandle")}
    if expected is not None and identity != expected:
        raise BindingError("Persistent native reference/VM identity changed during creation")
    backend.s.log("interactive-fixture-native-persistent-identity", identity=identity)
    return identity


def create(session, request, deadline, policy):
    policy = frozen_policy(session, policy)
    request = validate_request(request, policy)
    bounded_deadline(deadline)
    if (request.get("persistentForOwnedSave") is True and
            session.state.get("configuration", {}).get("interactive_session", {}).get("npcPersistence") is not True):
        raise BindingError("Persistent NPC creation requires the frozen npcPersistence opt-in")
    if not isinstance(session.state.get("id"), str) or not session.state["id"]:
        raise BindingError("Fixture creation requires an exact current run id")
    records = session.state.setdefault("interactiveActorFixtures", {})
    if not isinstance(records, dict) or request["tag"] in records or len(records) >= 16:
        raise BindingError("Fixture tag already attempted or sixteen-actor limit reached; never replay")
    backend = Backend(session, deadline)
    game = copy.deepcopy(session.state.get("game"))
    def ready():
        _owned(backend, game)
        scene = backend.call("inspect", {"kind": "scene"})
        menus = backend.call("menu", {"action": "list", "includeFlags": True})
        if not gameplay_ready(scene, menus):
            raise BindingError("Fixture mutation requires actual current gameplay/menu readiness")
    ready()
    _qualify(backend)
    base = request["base"]
    rows = backend.call("inspect", {"kind": "refs", "formId": base}).get("refs", [])
    if (len(rows) != 1 or actor_domain.form(rows[0].get("formId")) != base or rows[0].get("formType") not in ("NPC_", "NPC")):
        raise BindingError("Whitelisted fixture base is not one actual NPC base")
    expected = actor_domain.base_state(backend, base)
    player = actor_domain.observe_actor(backend, PLAYER)
    if player["actor"]["loaded3D"] is not True:
        raise BindingError("Actual player anchor is not loaded")
    pos, heading = _pose(backend, PLAYER["reference"])
    prior = backend.call("inspect", {"kind": "refs", "formType": "Actor", "radius": 0, "limit": 1024})
    rows = prior.get("refs")
    if (not isinstance(rows, list) or prior.get("truncated") is not False or type(prior.get("count")) is not int or
            type(prior.get("returned")) is not int or prior["count"] != len(rows) or prior["returned"] != len(rows)):
        raise BindingError("Complete bounded pre-creation actor census is unavailable")
    prior_refs = [actor_domain.form(row.get("formId")) for row in rows]
    if len(set(prior_refs)) != len(prior_refs):
        raise BindingError("Pre-creation actor census contains duplicate identities")
    radians = math.radians(heading)
    forward, right = request["forwardGameUnits"], request["rightGameUnits"]
    dx, dy = math.sin(radians) * forward + math.cos(radians) * right, math.cos(radians) * forward - math.sin(radians) * right
    destination = [pos[0] + dx, pos[1] + dy, pos[2]]
    creation_id = uuid.uuid4().hex
    entry = {"status": "intent", "tag": request["tag"], "base": base, "runId": session.state["id"],
             "creationId": creation_id, "game": game, "worldGeneration": session.state["ownedWorldGeneration"],
             "destination": destination, "headingDegrees": heading, "steps": {}, "createdAt": time.time()}
    with getattr(session, "lock", nullcontext()):
        if request["tag"] in records or len(records) >= 16:
            raise BindingError("Fixture tag was already attempted; no replacement or replay")
        records[request["tag"]] = entry
    def save():
        session.save()
    def stable_world():
        ready()
        incarnation, row, _ = actor_domain.anchor(backend, PLAYER["reference"])
        if incarnation != player["incarnation"] or row["loaded3D"] is not True or session.state["ownedWorldGeneration"] != entry["worldGeneration"]:
            raise BindingError("Player anchor or owned world changed during fixture creation")
    def invoke(function, arguments, target, script="ObjectReference"):
        entry["steps"][function] = "intent"
        save()
        value = _native_call(backend, {"script": script, "function": function,
                                       "returnType": _SIGNATURES[script][function][1]}, arguments, target)
        entry["steps"][function] = "returned"
        save()
        return value
    try:
        save()  # Durable intent precedes the first mutation, including a lost ACK.
        stable_world()
        persistent = request.get("persistentForOwnedSave", False)
        returned = invoke("PlaceAtMe", [{"form": base}, 1, persistent, False], PLAYER["reference"])
        ref = actor_domain.returned_form(returned)
        if (int(ref, 16) >> 24 != 0xFF or ref in prior_refs or ref in [value.get("reference") for value in records.values()]):
            raise BindingError("PlaceAtMe did not return one distinct new dynamic reference")
        entry["reference"] = ref
        entry["createdReference"] = ref
        entry["creationWitness"] = {"method": "ObjectReference.PlaceAtMe", "runId": entry["runId"], "creationId": creation_id,
            "reference": ref, "base": base, "anchor": PLAYER["reference"], "count": 1, "nativeReturned": True,
            "forcePersist": persistent,
            "priorActorCount": len(prior_refs), "priorActorsSha256": hashlib.sha256(json.dumps(sorted(prior_refs)).encode("ascii")).hexdigest()}
        save()
        spec = {"reference": ref, "base": base}
        def observe_new():
            stable_world()
            observed = actor_domain.observe_actor(backend, spec)
            inc = observed["incarnation"]
            observer_rows = observed.get("providerObservation", {}).get("refs", [])
            if len(observer_rows) != 1 or actor_domain.form(observer_rows[0].get("baseForm")) != base:
                raise BindingError("Observer did not confirm the created NPC base")
            if any(inc[key] != player["incarnation"][key] for key in ("sessionId", "loadGeneration")):
                raise BindingError("Created actor belongs to another observer session/world")
            if any(observed["actor"][key] != expected[key] for key in ("sex", "race")):
                raise BindingError("Created actor sex/race does not match its actual pinned base")
            return observed
        while True:
            observed = observe_new()
            if observed["actor"]["loaded3D"] is True:
                break
            backend.pause(.1)
        entry["incarnation"] = observed["incarnation"]
        if persistent:
            entry["nativePersistentIdentity"] = _persistent_identity(backend, spec, observed)
        save()
        stable_world()
        invoke("SetDontMove", [True], ref, script="Actor")
        stationary_actor = observe_new()
        if stationary_actor["incarnation"] != entry["incarnation"] or stationary_actor["actor"]["loaded3D"] is not True:
            raise BindingError("Created actor incarnation/loaded state changed before placement")
        current, _ = _pose(backend, PLAYER["reference"])
        if math.dist(current, pos) > 1:
            raise BindingError("Player moved before relative fixture placement; never repeat creation")
        stable_world()
        invoke("MoveTo", [{"form": PLAYER["reference"]}, float(dx), float(dy), 0.0, False], ref)
        current_actor = observe_new()
        if current_actor["incarnation"] != entry["incarnation"]:
            raise BindingError("Created actor incarnation changed before orientation")
        invoke("SetAngle", [0.0, 0.0, heading], ref)
        readback = {"requestedPosition": destination, "requestedHeadingDegrees": heading,
                    "positionToleranceGameUnits": 4, "headingToleranceDegrees": 1, "samples": []}
        entry["placementReadback"] = readback
        settle_end = min(deadline, time.monotonic()+3)
        previous = None
        while True:
            final = observe_new()
            if final["incarnation"] != entry["incarnation"] or final["actor"]["loaded3D"] is not True:
                raise BindingError("Created actor incarnation/loaded state changed during placement")
            actual_pos, actual_heading = _pose(backend, ref)
            sample = {"atMonotonic": time.monotonic(), "position": actual_pos, "headingDegrees": actual_heading,
                      "positionErrorGameUnits": math.dist(actual_pos, destination),
                      "headingErrorDegrees": abs((actual_heading-heading+180) % 360-180)}
            readback["samples"].append(sample)
            save()
            session.log("interactive-fixture-placement-readback", tag=request["tag"], reference=ref,
                        requestedPosition=destination, requestedHeadingDegrees=heading, **sample)
            if sample["positionErrorGameUnits"] > 4 or sample["headingErrorDegrees"] > 1:
                raise BindingError("Actual fixture placement/orientation readback differs from its requested position: "
                                   + repr({"requestedPosition": destination, "requestedHeadingDegrees": heading, **sample}))
            if sample["atMonotonic"] > settle_end:
                raise BindingError("Actual fixture placement readback exceeded its settling deadline: " + repr(readback))
            if previous and sample["atMonotonic"]-previous["atMonotonic"] >= .2:
                if (math.dist(actual_pos, previous["position"]) <= 1
                        and abs((actual_heading-previous["headingDegrees"]+180) % 360-180) <= 1):
                    readback["stableSampleSpanSeconds"] = sample["atMonotonic"]-previous["atMonotonic"]
                    break
            if time.monotonic() >= settle_end:
                raise BindingError("Actual fixture placement did not stabilize within its original tolerance: " + repr(readback))
            previous = sample
            backend.pause(.2)
        stable_world()
        if actor_domain.anchor(backend, ref)[0] != entry["incarnation"]:
            raise BindingError("Created actor incarnation changed across placement readback")
        if persistent:
            _persistent_identity(backend, spec, final, entry["nativePersistentIdentity"])
            stable_world()
        entry.update(status="created", actor=final["actor"], position=actual_pos, headingDegrees=actual_heading)
        save()
        session.log("interactive-fixture-created", tag=request["tag"], reference=ref, base=base,
                    creationId=creation_id, incarnation=entry["incarnation"], position=actual_pos, atomicSnapshot=False)
        result = {"fixture": {"tag": request["tag"], "status": "created", "creationId": creation_id},
                  "actor": dict(final["actor"]), "incarnation": entry["incarnation"],
                  "placement": {"position": actual_pos, "headingDegrees": actual_heading, "units": "Skyrim game units"}}
        if persistent:
            result["actor"]["persistentSaveWitnessAvailable"] = True
            result["nativePersistentIdentity"] = copy.deepcopy(entry["nativePersistentIdentity"])
        return result
    except BaseException as error:
        entry.update(status="uncertain", reason=str(error))
        try:
            save()
        except Exception:
            pass  # Preserve original failure; durable earlier intents still prohibit reuse.
        raise
