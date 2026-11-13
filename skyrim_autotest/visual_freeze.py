"""Explicit AI/collision-off preparation of one witnessed disposable reference.

This is not a global toggle, animation freeze, collision-contact test or implicit
race/load hook. Reads remain possible after an uncertain mutation; writes do not.
"""
from __future__ import annotations

import copy
import hashlib
import re
import time
import uuid

from . import actor_domain, actor_inspection, fixture_actors
from .interactive_bindings import BindingError, bounded_deadline, frozen_policy
from .native_session import settings as native_settings
from .platform import Backend


DOMAIN = "actor-visual-freeze"
ACTION = "freeze-owned-reference-once"
PROTOCOL = "npc-visual-freeze/1"
GUARDS = ("providerSession", "worldGeneration", "currentVmHandle", "runtimeHandle",
          "parentCell", "raceForm", "sampledRootToken")


def validate(operation, request):
    if operation not in ("world.read", "object.perform") or type(request) is not dict:
        raise BindingError("Visual freeze requires world.read or object.perform")
    expected = {"domain", "actor"} | ({"action"} if operation == "object.perform" else set())
    if (set(request) != expected or request.get("domain") != DOMAIN or
            type(request.get("actor")) is not dict or set(request["actor"]) != {"fixtureTag"} or
            not isinstance(request["actor"]["fixtureTag"], str) or
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", request["actor"]["fixtureTag"]) or
            (operation == "object.perform" and request.get("action") != ACTION)):
        raise BindingError("Visual freeze accepts one owned fixture tag and its exact once-only action")
    return copy.deepcopy(request)


def _sample(backend, entry, policy):
    # Reuse the actual creation/VM/process/incarnation guards, not a caller's FF id.
    entry = copy.deepcopy(entry)
    session = backend.s
    game = copy.deepcopy(session.state.get("game"))
    run_id, generation = session.state.get("id"), session.state.get("ownedWorldGeneration")
    spec = {"reference": entry["reference"], "base": entry["base"]}

    def owned():
        frozen_policy(session, policy)
        fixture_actors._owned(backend, game)
        current = fixture_actors.require_fixture(session, spec)
        if (session.state.get("id") != run_id or session.state.get("game") != game or
                session.state.get("ownedWorldGeneration") != generation or current != entry):
            raise BindingError("Owned visual-freeze world or complete creation identity changed across the sample")

    owned()
    inspected = actor_inspection._sample(backend, entry, policy)
    native = inspected["native"]
    if type(native.get("worldGeneration")) is not int or native["worldGeneration"] <= 0:
        raise BindingError("Actual native visual-freeze world generation is unavailable")
    args = {"action": "visual_state", **spec,
            "providerSession": native["providerSession"], "currentVmHandle": native["currentVmHandle"],
            "worldGeneration": native["worldGeneration"],
            "runtimeHandle": native["runtimeHandle"], "parentCell": actor_domain.form(native.get("parentCell")),
            "raceForm": inspected["actor"]["race"],
            "timeoutMs": max(1, min(5000, int(backend.remaining() * 1000)))}
    raw = backend.call("npc_persistence", args)
    backend.remaining()
    if (type(raw) is not dict or raw.get("protocol") != PROTOCOL or type(raw.get("pid")) is not int or
            raw["pid"] != backend.s.state["game"]["pid"] or raw.get("currentReference") != spec["reference"] or
            raw.get("base") != spec["base"] or raw.get("persistent") is not True or
            raw.get("disabled") is not False or raw.get("loaded3D") is not True or
            any(raw.get(name) != args[name] for name in GUARDS if name in args) or
            any(type(raw.get(name)) is not int or raw[name] <= 0 for name in ("worldGeneration", "sampledRootToken")) or
            type(raw.get("aiEnabled")) is not bool or raw.get("collisionStateObserved") is not True or
            raw.get("collisionStatus") != "available" or type(raw.get("collisionsEnabled")) is not bool or
            type(raw.get("referenceCollisionsEnabled")) is not bool or
            type(raw.get("collisionFilter")) is not int or not 0 <= raw["collisionFilter"] < 2**32 or
            type(raw.get("visualFrozen")) is not bool):
        raise BindingError("Actual guarded AI/character-controller collision state is unavailable or incoherent")
    frozen = not (raw["aiEnabled"] or raw["collisionsEnabled"] or raw["referenceCollisionsEnabled"])
    if raw["visualFrozen"] != frozen:
        raise BindingError("Native visual-freeze summary disagrees with independently returned state facts")
    incarnation, row, unused = actor_domain.anchor(backend, spec["reference"])
    if (incarnation != inspected["incarnation"] or row.get("baseForm") != spec["base"] or
            row.get("loaded3D") is not True or actor_domain.form(row.get("cellForm")) != raw["parentCell"]):
        raise BindingError("Actor incarnation/cell changed across visual-freeze observation")
    fixture_actors.require_fixture(session, spec, inspected)
    owned()
    return {"actor": {**inspected["actor"], "aiEnabled": raw["aiEnabled"],
                      "collisionsEnabled": raw["collisionsEnabled"]},
            "incarnation": inspected["incarnation"], "native": copy.deepcopy(raw),
            "inspection": copy.deepcopy(inspected),
            "fixture": {"tag": entry["tag"], "creationId": entry["creationId"], "visualFrozen": frozen,
                        "dontMove": native["dontMove"]},
            "observedAtMonotonic": time.monotonic(), "physicalContactAbsenceAccepted": False}


def execute(session, args, deadline, policy):
    if type(args) is not dict or set(args) != {"operation", "request"}:
        raise BindingError("Visual freeze execution requires exact operation and request")
    req = validate(args["operation"], args["request"])
    policy = frozen_policy(session, policy)
    configuration = session.state.get("configuration", {})
    settings = native_settings(configuration)
    matrix = settings.get("matrixLifecycle")
    matrix_enabled = (configuration.get("game_edition") == "se" and type(matrix) is dict and
                      matrix.get("freezeActors") is True)
    from .npc_persistence import generic_roster, _generic_fixtures
    generic = generic_roster(configuration)
    if settings.get("npcPersistence") is not True or not (settings.get("morphSession") or matrix_enabled or generic):
        raise BindingError("Visual freeze requires explicit frozen NPC-persistence and morph, SE matrix-freeze or generic-roster opt-ins")
    bounded_deadline(deadline)
    if generic is not None:
        fixtures = session.state.get("interactiveActorFixtures")
        _generic_fixtures(session, fixtures, complete=False)
        for current in fixtures.values():
            fixture_actors.require_fixture(session, {"reference": current.get("reference"), "base": current.get("base")})
    entry = session.state.get("interactiveActorFixtures", {}).get(req["actor"]["fixtureTag"])
    if not isinstance(entry, dict):
        raise BindingError("Visual freeze has no actual owned creation witness")
    entry = copy.deepcopy(entry)
    backend = Backend(session, deadline)
    if args["operation"] == "world.read":
        return _sample(backend, entry, policy)
    command_id = session.state.get("activeSemanticCommandId")
    if not isinstance(command_id, str) or not 1 <= len(command_id) <= 160:
        raise BindingError("Visual freeze requires the actual active held command identity")
    state = session.state.setdefault("visualFreeze", {"commands": {}})
    commands = state["commands"]
    key = hashlib.sha256((session.state["id"] + "\0" + command_id + "\0" + entry["creationId"]).encode("utf-8")).hexdigest()
    if key in commands or len(commands) >= 128:
        raise BindingError("Visual-freeze command already attempted or command bound reached; never replay")
    if any(row.get("creationId") == entry.get("creationId") and row.get("status") != "completed" for row in commands.values()):
        raise BindingError("An uncertain visual-freeze intent blocks further mutation of this creation identity")
    before = _sample(backend, entry, policy)
    command = {"status": "intent", "commandId": command_id, "requestId": uuid.uuid4().hex,
               "creationId": entry["creationId"], "reference": entry["reference"], "base": entry["base"],
               "request": req, "before": copy.deepcopy(before)}
    commands[key] = command
    # Failure to persist intent is terminal and cannot authorize a native call.
    session.save()
    try:
        raw = before["native"]
        request = {"action": "freeze_visual", "reference": entry["reference"], "base": entry["base"],
                   **{name: raw[name] for name in GUARDS}, "requestId": command["requestId"],
                   "expectedAIEnabled": raw["aiEnabled"], "expectedCollisionsEnabled": raw["collisionsEnabled"],
                   "expectedReferenceCollisionsEnabled": raw["referenceCollisionsEnabled"],
                   "timeoutMs": max(1, min(5000, int(backend.remaining() * 1000)))}
        receipt = backend.call("npc_persistence", request)
        backend.remaining()
        if (type(receipt) is not dict or receipt.get("protocol") != PROTOCOL or
                receipt.get("requestId") != command["requestId"] or receipt.get("mutationIssued") is not True or
                receipt.get("pid") != session.state["game"]["pid"] or
                receipt.get("currentReference") != entry["reference"] or receipt.get("base") != entry["base"] or
                any(receipt.get(name) != raw[name] for name in GUARDS)):
            raise BindingError("Visual-freeze call lacks its exact native completion witness; never replay")
        command["nativeReceipt"] = copy.deepcopy(receipt)
        session.save()
        while True:
            after = _sample(backend, entry, policy)
            if any(after["native"][name] != raw[name] for name in GUARDS):
                raise BindingError("Race/model/world identity changed while observing visual-freeze completion")
            if after["fixture"]["visualFrozen"]:
                break
            backend.pause(.1)
        command.update(status="completed", after=copy.deepcopy(after),
                       completionBasis="Fresh native AI, reference flag and character-controller filter all observed off")
        session.save()
        after["preparation"] = {"completed": True, "requestId": command["requestId"],
                                "mutationCallCount": 1, "toggleUsed": False,
                                "freezeWasAlreadyObservedBeforeCall": before["fixture"]["visualFrozen"]}
        return after
    except BaseException as error:
        command.update(status="uncertain", reason=str(error))
        try:
            session.save()
        except Exception:
            pass
        raise


def require_frozen(session, tag, deadline, policy):
    """Read the owned actor's current flags and hold; never prepare during a read."""
    result = execute(session, {"operation": "world.read", "request": {
        "domain": DOMAIN, "actor": {"fixtureTag": tag}}}, deadline, policy)
    if result["fixture"]["visualFrozen"] is not True or result["fixture"]["dontMove"] is not True:
        raise BindingError("Owned actor requires observed AI/collision off and an actual locomotion hold")
    return result
