"""Typed hide/show of witnessed persistent NPCs, including disabled references.

The ordinary loaded actor guards remain strict. Only this narrow operation can
resolve a disabled fixture through its retained native VM/runtime identity.
"""
from __future__ import annotations

import copy
import hashlib
import re
import uuid

from . import actor_domain, fixture_actors
from .interactive_bindings import BindingError, bounded_deadline, frozen_policy
from .platform import Backend


DOMAIN = "actor-fixture-visibility"
PROTOCOL = "npc-visibility/1"
IDENTITY_FIELDS = ("providerSession", "currentReference", "base", "currentVmHandle", "runtimeHandle", "parentCell", "worldGeneration")


def validate(operation, request):
    if (type(request) is not dict or set(request) != {"domain", "action", "actor"} or request["domain"] != DOMAIN or
            request["action"] not in ("read", "show", "hide") or type(request["actor"]) is not dict or
            set(request["actor"]) != {"fixtureTag"} or not isinstance(request["actor"]["fixtureTag"], str) or
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", request["actor"]["fixtureTag"])):
        raise BindingError("Visibility requires read/show/hide and one exact owned fixture tag")
    if operation != ("world.read" if request["action"] == "read" else "object.perform"):
        raise BindingError("Visibility read requires world.read; show/hide require object.perform")
    return copy.deepcopy(request)


def perform(session, request, deadline, policy):
    request = validate("world.read" if isinstance(request, dict) and request.get("action") == "read" else "object.perform", request)
    policy = frozen_policy(session, policy)
    bounded_deadline(deadline)
    backend = Backend(session, deadline)
    tag = request["actor"]["fixtureTag"]
    entry = session.state.get("interactiveActorFixtures", {}).get(tag)
    if not isinstance(entry, dict):
        raise BindingError("Visibility target has no actual owned creation witness")
    spec = {"reference": entry.get("reference"), "base": entry.get("base")}
    fixture_actors.require_fixture(session, spec)
    expected = copy.deepcopy(entry.get("nativePersistentIdentity", {}))
    stored_identity = copy.deepcopy(expected)
    restored = entry.get("restorationWitness", {}).get("native")
    stored_restoration = copy.deepcopy(entry.get("restorationWitness"))
    if restored:
        expected.update({key: restored.get(key) for key in ("currentReference", "currentVmHandle", "runtimeHandle")})
    if (session.state.get("configuration", {}).get("interactive_session", {}).get("npcPersistence") is not True or
            entry.get("creationWitness", {}).get("forcePersist") is not True or expected.get("protocol") != "npc-persistence/1" or
            expected.get("persistent") is not True or expected.get("currentReference") != spec["reference"] or
            expected.get("base") != spec["base"] or expected.get("pid") != session.state.get("game", {}).get("pid") or
            not isinstance(expected.get("providerSession"), str) or not expected["providerSession"] or
            not isinstance(expected.get("currentVmHandle"), str) or
            not re.fullmatch(r"[1-9][0-9]{0,19}", expected["currentVmHandle"]) or int(expected["currentVmHandle"]) >= 2**64 or
            type(expected.get("runtimeHandle")) is not int or expected["runtimeHandle"] <= 0):
        raise BindingError("Visibility requires the retained actual persistent reference/VM/runtime identity")
    initial = {key: copy.deepcopy(session.state.get(key)) for key in ("id", "game", "ownedWorldGeneration")}
    creation_id = entry["creationId"]
    incarnation = copy.deepcopy(entry["incarnation"])

    def owned():
        frozen = frozen_policy(session, policy)
        if spec["base"] not in frozen["fixtureActorBases"]:
            raise BindingError("Visibility fixture base is outside the frozen allowlist")
        current = fixture_actors.require_fixture(session, spec)
        fixture_actors._owned(backend, initial["game"])
        if (any(session.state.get(key) != value for key, value in initial.items()) or
                current.get("creationId") != creation_id or current.get("incarnation") != incarnation or
                current.get("nativePersistentIdentity") != stored_identity or
                current.get("restorationWitness") != stored_restoration):
            raise BindingError("Visibility owned world or creation identity changed")
        player_inc, row, _ = actor_domain.anchor(backend, fixture_actors.PLAYER["reference"])
        if (row.get("baseForm") != fixture_actors.PLAYER["base"] or row.get("loaded3D") is not True or
                any(player_inc[key] != incarnation[key] for key in ("sessionId", "loadGeneration"))):
            raise BindingError("Visibility current player belongs to another world")
        return player_inc, actor_domain.form(row.get("cellForm"))

    player, cell = owned()
    state = session.state.setdefault("fixtureVisibility", {"actors": {}, "commands": {}})
    if type(state) is not dict or set(state) != {"actors", "commands"} or any(type(state[key]) is not dict for key in state):
        raise BindingError("Visibility working state is malformed")
    previous = state["actors"].get(tag)
    native_generation = previous.get("worldGeneration") if previous else None
    if previous and (previous.get("creationId") != creation_id or previous.get("reference") != spec["reference"] or
                     type(native_generation) is not int or native_generation <= 0):
        raise BindingError("Visibility retained native world identity changed")

    def same_world():
        if owned() != (player, cell):
            raise BindingError("Visibility player incarnation or cell changed")

    def read(*, baseline=None):
        nonlocal native_generation
        same_world()
        args = {"action": "visibility_state", **spec, "providerSession": expected["providerSession"],
                "currentVmHandle": expected["currentVmHandle"], "runtimeHandle": expected["runtimeHandle"], "parentCell": cell,
                "timeoutMs": max(1, min(5000, int(backend.remaining() * 1000)))}
        if native_generation is not None:
            args["worldGeneration"] = native_generation
        raw = backend.call("npc_persistence", args)
        backend.remaining()
        checked(raw, baseline=baseline)
        same_world()
        native_generation = raw["worldGeneration"]
        return raw

    def checked(raw, *, baseline=None):
        if (type(raw) is not dict or raw.get("protocol") != PROTOCOL or type(raw.get("pid")) is not int or
                raw["pid"] != initial["game"]["pid"] or raw.get("persistent") is not True or
                any(raw.get(key) != expected[key] for key in ("providerSession", "currentReference", "base", "currentVmHandle", "runtimeHandle")) or
                raw.get("parentCell") != cell or type(raw.get("worldGeneration")) is not int or raw["worldGeneration"] <= 0 or
                type(raw.get("disabled")) is not bool or type(raw.get("loaded3D")) is not bool or
                native_generation is not None and raw["worldGeneration"] != native_generation or
                baseline is not None and any(raw.get(key) != baseline[key] for key in IDENTITY_FIELDS)):
            raise BindingError("Native visibility reference/base/VM/runtime/cell/world identity changed")

    before = read()
    state["actors"][tag] = {"creationId": creation_id, "reference": spec["reference"], "worldGeneration": native_generation,
                            "lastObservation": copy.deepcopy(before)}

    def result(raw, issued):
        return {"actor": dict(spec, disabled=raw["disabled"], loaded3D=raw["loaded3D"]), "fixtureTag": tag,
                "disabled": raw["disabled"], "loaded3D": raw["loaded3D"], "unchangedIdentity": True,
                "mutationIssued": issued, "nativeObservation": copy.deepcopy(raw),
                "completionBasis": "Exact retained reference/VM/runtime identity and sampled native visibility; no preset or appearance verdict"}

    if request["action"] == "read":
        session.save()
        return result(before, False)
    command = session.state.get("activeSemanticCommandId")
    if not isinstance(command, str) or not 1 <= len(command) <= 160:
        raise BindingError("Visibility mutation requires the actual active held command identity")
    key = hashlib.sha256((initial["id"] + "\0" + command).encode("utf-8")).hexdigest()
    if key in state["commands"] or len(state["commands"]) >= 256:
        raise BindingError("Visibility command already attempted or command bound reached; never replay")
    if any(value.get("creationId") == creation_id and value.get("status") != "completed" for value in state["commands"].values()):
        raise BindingError("Uncertain visibility action blocks further mutations of this fixture")
    visible = request["action"] == "show"
    record = {"status": "intent", "requestId": uuid.uuid4().hex, "commandId": command,
              "creationId": creation_id, "request": request, "before": copy.deepcopy(before)}
    state["commands"][key] = record
    session.save()
    issued = False
    try:
        if before["disabled"] == visible:
            same_world()
            args = {"action": "set_visibility", **spec, **{k: before[k] for k in IDENTITY_FIELDS if k not in ("currentReference", "base")},
                    "requestId": record["requestId"], "visible": visible, "expectedDisabled": before["disabled"],
                    "timeoutMs": max(1, min(5000, int(backend.remaining() * 1000)))}
            issued = True
            raw = backend.call("npc_persistence", args)
            backend.remaining()
            checked(raw, baseline=before)
            if raw.get("requestId") != record["requestId"] or raw.get("mutationIssued") is not True or raw.get("resetInventory") is not False:
                raise BindingError("Native visibility mutation receipt unavailable; never replay")
            record["nativeReceipt"] = copy.deepcopy(raw)
            same_world()
        while True:
            after = read(baseline=before)
            if after["disabled"] is not visible and (not visible or after["loaded3D"]):
                break
            backend.pause(.1)
        if visible:
            observed = fixture_actors.guard(session, spec, deadline, policy)
            if observed["incarnation"] != incarnation:
                raise BindingError("Enabled fixture ordinary loaded identity changed")
            # Recheck the exact native identity after the loaded actor guard.
            after = read(baseline=before)
            if after["disabled"] or not after["loaded3D"]:
                raise BindingError("Enabled fixture visibility changed after loaded guard")
        final = result(after, issued)
        record.update(status="completed", result=copy.deepcopy(final))
        state["actors"][tag]["lastObservation"] = copy.deepcopy(after)
        session.save()
        session.log("fixture-visibility-completed", fixtureTag=tag, commandId=command, result=final)
        return final
    except BaseException as error:
        record.update(status="uncertain", mutationIssued=issued, reason=str(error))
        try:
            session.save()
        except Exception:
            pass
        raise
