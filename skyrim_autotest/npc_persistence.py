"""One owned same-process save/load of six witnessed persistent NPCs.

The native SKSE co-save bundle supplies real form/VM remapping. A former FF ID,
base match, callback ACK or cached observer handle cannot authorize rebinding.
"""
from __future__ import annotations

import copy
import math
import re
import time
import uuid

from . import actor_domain, fixture_actors, owned_saves
from .interactive_bindings import BindingError, bounded_deadline, frozen_policy
from .platform import Backend


PROTOCOL = "npc-persistence/1"


def _enabled(session):
    if session.state.get("configuration", {}).get("interactive_session", {}).get("npcPersistence") is not True:
        raise BindingError("Owned NPC persistence requires the frozen npcPersistence opt-in")


def _deadline(deadline, maximum=30):
    try:
        remaining = deadline - time.monotonic() if type(deadline) in (int, float) else float("nan")
    except (OverflowError, ValueError):
        remaining = float("nan")
    if not math.isfinite(remaining) or not 0 < remaining <= maximum:
        raise BindingError("NPC persistence requires a finite absolute deadline within its declared bound")


def validate_request(request):
    if type(request) is not dict or request.get("action") not in ("save", "load"):
        raise BindingError("NPC persistence requires save or load")
    required = {"action", "saveTag"} | ({"fixtureTags"} if request["action"] == "save" else set())
    if set(request) != required:
        raise BindingError("NPC persistence accepts only its exact action, saveTag and save fixtureTags")
    tag = request["saveTag"]
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", tag):
        raise BindingError("Owned NPC saveTag must be a bounded flat identifier")
    if request["action"] == "save":
        tags = request["fixtureTags"]
        if (not isinstance(tags, list) or len(tags) != 6 or
                any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value) for value in tags) or
                len(set(tags)) != 6):
            raise BindingError("NPC save requires exactly six distinct creation fixture tags")
    return copy.deepcopy(request)


def _handle(value):
    # Papyrus handles are uint64. JSON numbers can lose their low bits in hosts.
    if (not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value) or
            int(value) >= 2**64):
        raise BindingError("Native saved/current VM identity requires an exact nonzero uint64 decimal string")
    return value


def _world(backend, record=None):
    game = backend.s.state.get("game") if record is None else record["game"]
    fixture_actors._owned(backend, game)
    return copy.deepcopy(game)


def _native(backend, request):
    request = dict(request, timeoutMs=max(1, min(5000, int(backend.remaining() * 1000))))
    receipt = backend.call("npc_persistence", request)
    backend.remaining()
    backend.s.log("interactive-npc-persistence-native", request=request, receipt=receipt)
    return receipt


def _receipt(receipt, record, phase, *, baseline=None):
    """Validate producer identities independently of subject state/cached FF IDs."""
    if (not isinstance(receipt, dict) or receipt.get("schemaVersion") != 1 or
            type(receipt.get("schemaVersion")) is not int or receipt.get("protocol") != PROTOCOL or
            receipt.get("phase") != phase or receipt.get("bindingId") != record["bindingId"] or
            receipt.get("runId") != record["runId"] or receipt.get("saveTag") != record["saveTag"] or
            type(receipt.get("pid")) is not int or receipt["pid"] != record["game"]["pid"] or
            not isinstance(receipt.get("providerSession"), str) or not 1 <= len(receipt["providerSession"]) <= 128 or
            any(type(receipt.get(key)) is not int or receipt[key] < 0 for key in ("saveOrdinal", "loadOrdinal"))):
        raise BindingError("Native NPC persistence receipt identity/phase is unavailable or foreign")
    if baseline is not None:
        if receipt["providerSession"] != baseline["providerSession"]:
            raise BindingError("NPC persistence provider session changed")
        save_delta, load_delta = (1, 0) if phase == "saved" else (0, 1)
        if (receipt["saveOrdinal"] != baseline["saveOrdinal"] + save_delta or
                receipt["loadOrdinal"] != baseline["loadOrdinal"] + load_delta):
            raise BindingError("NPC persistence requires exactly one native save/load serialization transition")
    rows = receipt.get("actors")
    expected = record["fixtures"]
    if (not isinstance(rows, list) or len(rows) != 6 or
            any(not isinstance(row, dict) for row in rows) or
            {row.get("tag") for row in rows} != set(expected)):
        raise BindingError("Native NPC persistence receipt does not cover the exact six creation witnesses")
    references, handles = set(), set()
    for row in rows:
        fixture = expected[row["tag"]]
        if (row.get("creationId") != fixture["creationId"] or row.get("base") != fixture["base"] or
                row.get("savedReference") != fixture["reference"] or row.get("persistent") is not True or
                type(row.get("runtimeHandle")) is not int or row["runtimeHandle"] <= 0):
            raise BindingError("Native NPC persistence differs from a persistent creation witness")
        saved_vm, current_vm = _handle(row.get("savedVmHandle")), _handle(row.get("currentVmHandle"))
        ref = actor_domain.form(row.get("currentReference"))
        if int(ref, 16) >> 24 != 0xFF or ref in references or current_vm in handles:
            raise BindingError("Native persistence remap contains a duplicate or non-created actor identity")
        references.add(ref); handles.add(current_vm)
        if phase != "loaded":
            if ref != fixture["reference"] or saved_vm != current_vm:
                raise BindingError("Native save identity changed before an owned load")
            if saved_vm != fixture.get("nativePersistentIdentity", {}).get("currentVmHandle"):
                raise BindingError("Native save VM identity differs from the actual persistent creation witness")
            if receipt["providerSession"] != fixture["nativePersistentIdentity"].get("providerSession"):
                raise BindingError("Native save provider session differs from the actual persistent creation witness")
            if row["runtimeHandle"] != fixture["savedObservation"]["incarnation"]["runtimeHandle"]:
                raise BindingError("Native save actor runtime identity differs from the actual creation observation")
            if baseline is not None:
                before = next(item for item in baseline["actors"] if item["tag"] == row["tag"])
                if saved_vm != before["savedVmHandle"]:
                    raise BindingError("Native serialized VM identity changed across the owned save")
        else:
            before = next(item for item in baseline["actors"] if item["tag"] == row["tag"])
            if (saved_vm != before["savedVmHandle"] or row.get("formResolved") is not True or
                    row.get("handleResolved") is not True or row.get("resolvedReference") != ref or
                    _handle(row.get("resolvedVmHandle")) != current_vm):
                raise BindingError("Saved form and VM identity lack matching actual native load remap witnesses")
    return copy.deepcopy(receipt)


def _wait_receipt(backend, record, phase, baseline):
    earlier = "bound" if phase == "saved" else "saved"
    while True:
        _world(backend, record)
        raw = _native(backend, {"action": "read", "bindingId": record["bindingId"]})
        if isinstance(raw, dict) and raw.get("phase") == earlier:
            # Only read polling; a repeated save/load request is never emitted.
            checked = _receipt(raw, record, earlier)
            if checked != baseline:
                raise BindingError("Earlier persistence receipt changed while awaiting completion")
            backend.pause(.1)
            continue
        return _receipt(raw, record, phase, baseline=baseline)


def _capture(backend, tags):
    result = {}
    state = backend.s.state
    fixtures = state.get("interactiveActorFixtures", {})
    if set(fixtures) != set(tags):
        raise BindingError("The NPC save bundle must contain all and only six attempted owned fixtures")
    for tag in tags:
        entry = fixtures.get(tag, {})
        spec = {"reference": entry.get("reference"), "base": entry.get("base")}
        fixture_actors.require_fixture(backend.s, spec)
        if entry.get("creationWitness", {}).get("forcePersist") is not True:
            raise BindingError("Owned NPC save requires forcePersist:true at witnessed creation")
        identity = entry.get("nativePersistentIdentity", {})
        if (identity.get("persistent") is not True or identity.get("currentReference") != spec["reference"] or
                identity.get("base") != spec["base"] or identity.get("protocol") != PROTOCOL or
                identity.get("pid") != state["game"]["pid"] or not isinstance(identity.get("providerSession"), str) or
                not identity["providerSession"]):
            raise BindingError("Owned NPC save requires the actual native persistent creation identity")
        observation = actor_domain.observe_actor(backend, spec)
        fixture_actors.require_fixture(backend.s, spec, observation)
        result[tag] = copy.deepcopy(entry)
        result[tag]["savedObservation"] = observation
    return result


def _result(record):
    saved = record.get("status") in ("saved", "loaded")
    result = {"save": {"completed": saved, "ownedPairCount": 1 if saved else 0,
                       "actorWitnessCount": 6 if saved else 0, "saveTag": record["saveTag"],
                       "scope": "current-temporary-profile", "bindingId": record["bindingId"]},
              "nativePersistenceReceipt": copy.deepcopy(record.get("loadedReceipt", record.get("savedReceipt")))}
    if saved:
        result["save"].update(copy.deepcopy(record["saveResult"]["save"]))
    if record.get("status") == "loaded":
        result["save"].update(loadedOwnedPairCount=1, actorRemapWitnessCount=6, worldReady=True)
        result["load"] = {"completed": True, "sameProcess": True, "actorWitnessCount": 6,
                          "worldGeneration": record["afterWorldGeneration"], "saveTag": record["saveTag"]}
        result["lifecycle"] = copy.deepcopy(record["loadResult"]["lifecycle"])
        result["actors"] = [{"tag": tag, **copy.deepcopy(value)} for tag, value in record["rebindings"].items()]
    return result


def perform(session, request, deadline, policy):
    """Execute one narrow save/load in the existing held, owned game process."""
    frozen_policy(session, policy)
    _enabled(session)
    request = validate_request(request)
    _deadline(deadline, 90 if request["action"] == "load" else 30)
    backend = Backend(session, deadline)
    state, tag = session.state, request["saveTag"]
    game = _world(backend)
    # Preserve the existing local-profile, MO2 mapping and permission guard.
    owned_saves.directory(backend)
    records = state.setdefault("npcPersistence", {})
    if request["action"] == "save":
        if records or tag in state.get("ownedSaves", {}):
            raise BindingError("One NPC save bundle only; an attempted save tag is never replayed")
        fixtures = _capture(backend, request["fixtureTags"])
        record = {"status": "save-intent", "saveTag": tag, "bindingId": uuid.uuid4().hex,
                  "runId": state["id"], "game": game, "worldGeneration": state["ownedWorldGeneration"],
                  "fixtures": fixtures, "createdAt": time.time(), "loadAttempted": False}
        records[tag] = record
        session.save()  # Durable intent covers a lost native bind or save ACK.
        try:
            actors = [{key: entry[key] for key in ("tag", "creationId", "reference", "base")} for entry in fixtures.values()]
            record["boundReceipt"] = _receipt(_native(backend, {"action": "bind", "bindingId": record["bindingId"],
                "runId": record["runId"], "saveTag": tag, "actors": actors}), record, "bound")
            session.save()
            _world(backend, record)
            record["saveResult"] = owned_saves.perform(backend, {"action": "save_game", "saveTag": tag,
                                                                    "scope": "owned-disposable-profile"})
            record["savedReceipt"] = _wait_receipt(backend, record, "saved", record["boundReceipt"])
            record["status"] = "saved"
            session.save()
            return _result(record)
        except BaseException as error:
            record.update(status="save-uncertain", reason=str(error))
            session.save()
            raise
    record = records.get(tag)
    if not isinstance(record, dict) or record.get("status") != "saved" or record.get("loadAttempted") is not False:
        raise BindingError("NPC load requires one completed unconsumed owned save; never replay")
    _world(backend, record)
    if state["ownedWorldGeneration"] != record["worldGeneration"]:
        raise BindingError("A foreign world transition invalidated the saved NPC bundle")
    owned_saves.saved(backend, tag)
    _capture(backend, list(record["fixtures"]))
    # Invalidate every old actor binding before requesting a world transition.
    window = None
    if state.get("interactiveSession", {}).get("ready") is True:
        command_id = state.get("activeSemanticCommandId")
        original_deadline = state.get("deadline")
        if (state.get("phase") != "interactive-session" or not isinstance(command_id, str) or
                not re.fullmatch(r"[0-9a-f]{32}", command_id) or type(original_deadline) not in (int, float) or
                not math.isfinite(original_deadline) or original_deadline <= time.time()):
            raise BindingError("Held NPC load requires its actual command and unchanged original interactive window")
        window = {"phase": state["phase"], "deadline": original_deadline}
    record.update(status="load-intent", loadAttempted=True,
                  loadCommandId=state.get("activeSemanticCommandId"), ownedLoadOrdinal=len(state.get("ownedLoadHistory", []))+1,
                  interactiveWindow=window)
    if window is not None:
        state.update(phase="interactive-owned-npc-load", deadline=min(window["deadline"], time.time()+backend.remaining()))
    for entry in state["interactiveActorFixtures"].values():
        entry["status"] = "load-pending"
    session.save()
    try:
        record["loadResult"] = owned_saves.perform(backend, {"action": "load_game", "saveTag": tag,
                                                                "scope": "owned-disposable-profile"})
        _world(backend, record)
        if (state["ownedWorldGeneration"] != record["worldGeneration"] + 1 or
                record["loadResult"].get("lifecycle", {}).get("worldReady") is not True or
                record["loadResult"]["lifecycle"].get("pidChanged") is not False):
            raise BindingError("NPC load lacks exactly one same-process owned ready world transition")
        raw = _wait_receipt(backend, record, "loaded", record["savedReceipt"])
        replacements, rebindings = {}, {}
        for row in raw["actors"]:
            old = record["fixtures"][row["tag"]]
            spec = {"reference": row["currentReference"], "base": old["base"]}
            observation = actor_domain.observe_actor(backend, spec)
            before, after = old["savedObservation"]["incarnation"], observation["incarnation"]
            if (after["sessionId"] != before["sessionId"] or after["loadGeneration"] <= before["loadGeneration"] or
                    after["runtimeHandle"] != row["runtimeHandle"] or observation["actor"]["loaded3D"] is not True or
                    observation["actor"]["sex"] != old["actor"]["sex"]):
                raise BindingError("Restored actor lacks a fresh matching observer world/VM/reference witness")
            replacement = copy.deepcopy(old)
            restoration = {"bindingId": record["bindingId"], "saveTag": tag, "native": copy.deepcopy(row),
                           "worldGeneration": state["ownedWorldGeneration"]}
            replacement.update(status="created", reference=spec["reference"], incarnation=after,
                               actor=observation["actor"], worldGeneration=state["ownedWorldGeneration"],
                               restorationWitness=copy.deepcopy(restoration))
            replacements[row["tag"]] = replacement
            rebindings[row["tag"]] = {"actor": copy.deepcopy(observation["actor"]), "incarnation": copy.deepcopy(after),
                                       "restorationWitness": copy.deepcopy(restoration)}
        _world(backend, record)
        record.update(status="loaded", loadedReceipt=raw, rebindings=rebindings,
                      afterWorldGeneration=state["ownedWorldGeneration"])
        # Publish all six together, after every independent native+observer check.
        state["interactiveActorFixtures"] = replacements
        if window is not None:
            if time.time() >= window["deadline"]:
                raise TimeoutError("Original held interactive deadline expired during NPC load")
            state.update(phase=window["phase"], deadline=window["deadline"])
        session.save()
        return _result(record)
    except BaseException as error:
        record.update(status="load-uncertain", reason=str(error))
        for entry in state["interactiveActorFixtures"].values():
            entry["status"] = "load-uncertain"
        session.save()
        raise


def require_restoration(session, entry):
    """Used by ordinary fixture guards after an atomic complete bundle rebind."""
    witness = entry.get("restorationWitness", {})
    record = session.state.get("npcPersistence", {}).get(witness.get("saveTag"), {})
    rebound = record.get("rebindings", {}).get(entry.get("tag"), {})
    native = witness.get("native", {})
    if (record.get("status") != "loaded" or witness.get("bindingId") != record.get("bindingId") or
            record.get("runId") != session.state.get("id") or record.get("game") != session.state.get("game") or
            record.get("afterWorldGeneration") != session.state.get("ownedWorldGeneration") or
            rebound.get("restorationWitness") != witness or rebound.get("incarnation") != entry.get("incarnation") or
            rebound.get("actor") != entry.get("actor") or native.get("currentReference") != entry.get("reference") or
            native.get("savedReference") != entry.get("creationWitness", {}).get("reference") or
            native.get("creationId") != entry.get("creationId") or native.get("formResolved") is not True or
            native.get("handleResolved") is not True):
        raise BindingError("Fixture restoration lacks a completed exact owned native remap bundle")
    return witness


def observe(session, request, deadline, policy):
    frozen_policy(session, policy)
    _enabled(session)
    if type(request) is not dict or set(request) != {"saveTag"}:
        raise BindingError("NPC persistence observation requires an exact saveTag")
    validate_request({"action": "load", **request})
    bounded_deadline(deadline)
    backend = Backend(session, deadline)
    record = session.state.get("npcPersistence", {}).get(request["saveTag"], {})
    if record.get("status") not in ("saved", "loaded"):
        raise BindingError("No completed owned NPC persistence evidence for this tag")
    _world(backend, record)
    owned_saves.saved(backend, request["saveTag"])
    if record["status"] == "loaded":
        owned_saves.observe(backend, {"observation": "lifecycle.state", "afterSaveTag": request["saveTag"]})
        for tag, entry in session.state["interactiveActorFixtures"].items():
            observation = actor_domain.observe_actor(backend, {"reference": entry["reference"], "base": entry["base"]})
            fixture_actors.require_fixture(session, {"reference": entry["reference"], "base": entry["base"]}, observation)
    return _result(record)
