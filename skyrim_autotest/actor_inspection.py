"""Owned reference-only names, unequip/hold preparation and measured inspection.

This domain neither adopts NPCs nor supplies a voice/NLP route. Position samples
and command counts describe their measured interval and this domain's own ledger.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
import time
import uuid

from . import actor_domain, fixture_actors, interactive_bindings
from .interactive_bindings import BindingError, bounded_deadline, frozen_policy
from .platform import Backend


DOMAIN = "actor-fixture-inspection"
ACTIONS = {"set-reference-display-name": "name", "unequip-all-reference-gear": "unequip",
           "hold-position-keep-collision": "hold"}
COMMON = {"domain", "actor", "displayName", "nameScope", "phase", "requireActualOwnedReferenceWitness"}
MUTABLE = {"action", "preserveInventory", "editBaseNPC", "editBaseOutfit", "collisionPolicy", "noRetryOnUnknownOutcome"}
READ = {"wornArmorSlots", "minimumPositionSamples", "minimumObservationSpanMs", "positionToleranceGameUnits"}


def validate(operation, req):
    """Validate only the exact reviewed domain; no I/O or caller script selectors."""
    if operation not in ("world.read", "object.perform") or type(req) is not dict:
        raise BindingError("Actor inspection supports world.read or object.perform")
    if set(req) != COMMON | (MUTABLE if operation == "object.perform" else READ):
        raise BindingError("Actor inspection request fields must exactly match its domain contract")
    if (req["domain"] != DOMAIN or type(req["actor"]) is not dict or set(req["actor"]) != {"fixtureTag"} or
            not isinstance(req["actor"]["fixtureTag"], str) or
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", req["actor"]["fixtureTag"])):
        raise BindingError("Actor inspection requires one exact owned fixture tag")
    name = req["displayName"]
    if (not isinstance(name, str) or not 1 <= len(name) <= 64 or name.strip() != name or
            any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise BindingError("Reference display name must be one bounded visible name")
    try:
        valid = len(name.encode("utf-8")) <= 128
    except UnicodeError:
        valid = False
    if not valid:
        raise BindingError("Reference display name must be valid bounded UTF-8")
    if (req["nameScope"] != "reference-only" or req["phase"] not in ("initial", "returned-human") or
            req["requireActualOwnedReferenceWitness"] is not True):
        raise BindingError("Inspection requires reference-only naming, declared phase and actual owned witness")
    if operation == "object.perform":
        if (not isinstance(req["action"], str) or req["action"] not in ACTIONS or req["preserveInventory"] is not True or
                req["editBaseNPC"] is not False or req["editBaseOutfit"] is not False or
                req["collisionPolicy"] != "retain-enabled" or req["noRetryOnUnknownOutcome"] is not True):
            raise BindingError("Inspection preparation forbids base/outfit/inventory deletion and collision-disable commands")
    else:
        if (req["wornArmorSlots"] != [30, 61] or any(type(v) is not int for v in req["wornArmorSlots"]) or
                type(req["minimumPositionSamples"]) is not int or not 2 <= req["minimumPositionSamples"] <= 32 or
                type(req["minimumObservationSpanMs"]) is not int or not 200 <= req["minimumObservationSpanMs"] <= 10000):
            raise BindingError("Inspection requires complete armor slots30..61 and at least two samples over200ms")
        actor_domain.bounded(req["positionToleranceGameUnits"], 0, 100)
    return copy.deepcopy(req)


def _expected(entry):
    restored = entry.get("restorationWitness", {}).get("native")
    original = entry.get("nativePersistentIdentity", {})
    if restored:
        return restored.get("currentVmHandle"), original.get("providerSession")
    return original.get("currentVmHandle"), original.get("providerSession")


def _sample(backend, entry, policy):
    """Bracket one native identity/equipment batch without repeated full getters."""
    session = backend.s
    spec = {"reference": entry["reference"], "base": entry["base"]}
    game = copy.deepcopy(session.state.get("game"))
    run_id, generation = session.state.get("id"), session.state.get("ownedWorldGeneration")
    creation_id, incarnation = entry.get("creationId"), copy.deepcopy(entry.get("incarnation"))
    expected_vm, expected_session = _expected(entry)

    def owned():
        current_policy = frozen_policy(session, policy)
        if spec["base"] not in current_policy["fixtureActorBases"]:
            raise BindingError("Inspection base is outside the frozen fixture allowlist")
        fixture_actors.require_fixture(session, spec)
        fixture_actors._owned(backend, game)
        current = fixture_actors.require_fixture(session, spec)
        if (session.state.get("id") != run_id or session.state.get("ownedWorldGeneration") != generation or
                current.get("creationId") != creation_id or current.get("incarnation") != incarnation or
                current.get("reference") != spec["reference"] or current.get("base") != spec["base"] or
                _expected(current) != (expected_vm, expected_session)):
            raise BindingError("Owned inspection world or creation identity changed across the sample")
        backend.remaining()

    def observed():
        current, row, _ = actor_domain.anchor(backend, spec["reference"])
        if (current != incarnation or row.get("baseForm") != spec["base"] or row.get("loaded3D") is not True):
            raise BindingError("Actor incarnation/base/loaded state changed across native inspection")
        return current, actor_domain.form(row.get("cellForm"))

    owned()
    before, cell = observed()
    raw = backend.call("npc_persistence", {"action": "inspection", **spec,
        "timeoutMs": max(1, min(5000, int(backend.remaining() * 1000)))})
    backend.remaining()
    vm = raw.get("currentVmHandle") if isinstance(raw, dict) else None
    if (not isinstance(raw, dict) or raw.get("protocol") != "npc-persistence/1" or
            type(raw.get("pid")) is not int or raw["pid"] != backend.s.state["game"]["pid"] or
            raw.get("providerSession") != expected_session or not isinstance(expected_session, str) or not expected_session or
            raw.get("persistent") is not True or raw.get("currentReference") != spec["reference"] or raw.get("base") != spec["base"] or
            type(raw.get("runtimeHandle")) is not int or raw["runtimeHandle"] != before["runtimeHandle"] or
            not isinstance(vm, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", vm) or int(vm) >= 2**64 or vm != expected_vm):
        raise BindingError("Native inspection lacks the actual current owned reference/VM identity")
    name, position, slots = raw.get("displayName"), raw.get("position"), raw.get("wornArmorSlots")
    if not isinstance(name, str) or len(name) > 1024 or not isinstance(position, list) or len(position) != 3:
        raise BindingError("Actual display name/position inspection is unavailable")
    for value in position: actor_domain.bounded(value, -1e7, 1e7)
    if (not isinstance(slots, list) or len(slots) != 32 or any(type(row) is not dict or set(row) != {"slot", "form"} for row in slots) or
            any(type(row["slot"]) is not int for row in slots) or {row["slot"] for row in slots} != set(range(30, 62)) or
            "equippedLeft" not in raw or "equippedRight" not in raw or type(raw.get("dontMove")) is not bool or
            any(type(raw.get(hand+"IsWeapon")) is not bool or (raw[hand+"IsWeapon"] and raw[hand] is None)
                for hand in ("equippedLeft", "equippedRight"))):
        raise BindingError("Complete native armor/weapon/hold inspection is unavailable")
    for item in [row["form"] for row in slots] + [raw["equippedLeft"], raw["equippedRight"]]:
        if item is not None: actor_domain.form(item)
    # The batch already supplies the actual reference/base/VM/runtime identity.
    # Only these three current actor values are absent from that native batch.
    sex = backend.pap("ActorBase", "GetSex", target=spec["base"])
    if type(sex) is not int or sex not in (0, 1):
        raise BindingError("Actual inspection actor sex is unavailable")
    weight = actor_domain.bounded(backend.pap("ActorBase", "GetWeight", target=spec["base"]), 0, 100)
    race = actor_domain.returned_form(backend.pap("Actor", "GetRace", target=spec["reference"]))
    after, final_cell = observed()
    if after != before or final_cell != cell:
        raise BindingError("Actor incarnation or cell changed across native inspection")
    actor = dict(spec, loaded3D=True, sex=("male", "female")[sex], weight=weight, race=race, displayName=name)
    observation = {"actor": actor, "incarnation": after}
    fixture_actors.require_fixture(session, spec, observation)
    owned()
    result = {"native": copy.deepcopy(raw), "actor": actor,
              "incarnation": copy.deepcopy(after), "observedAtMonotonic": time.monotonic()}
    backend.s.log("actor-fixture-inspection-sample", tag=entry["tag"], sample=result, atomicSnapshot=False)
    return result


def _equipment(sample):
    raw = sample["native"]
    return (len({row["form"] for row in raw["wornArmorSlots"] if row["form"] is not None}),
            sum(raw[hand+"IsWeapon"] for hand in ("equippedLeft", "equippedRight")))


def _role(policy, kind):
    function, params = ("UnequipAll", []) if kind == "unequip" else ("SetDontMove", ["bool"])
    rows = [row for row in policy["bindings"] if row["script"].casefold() == "actor" and row["function"].casefold() == function.casefold()]
    if len(rows) != 1:
        raise BindingError("Inspection preparation requires one frozen Actor." + function + " binding")
    row = rows[0]
    if (row["scope"] != "member" or row["params"] != params or row["returnType"] != "none" or row["effect"] != "mutate" or
            row["actorSelf"] is not True or row["actorArgs"] != [] or row["raceArgs"] != [] or row["completion"] != "native-return"):
        raise BindingError("Inspection preparation requires the exact native actor preparation signature")
    return row


def _summary(session, entry, req, samples):
    latest = samples[-1]
    registry = session.state.get("actorInspection", {}).get("registry", {}).get(entry["tag"], {})
    match = (registry.get("runId") == session.state.get("id") and registry.get("creationId") == entry["creationId"] and
             registry.get("displayName") == req["displayName"] == latest["actor"]["displayName"])
    armor, weapons = _equipment(latest)
    positions = [sample["native"]["position"] for sample in samples]
    drift = max((math.dist(first, second) for first in positions for second in positions), default=0)
    commands = session.state.get("actorInspection", {}).get("commands", {})
    collision_count = sum(value.get("collisionDisableRequested") is True for value in commands.values())
    return {"actor": latest["actor"], "incarnation": latest["incarnation"],
        "fixture": {"tag": entry["tag"], "creationId": entry["creationId"], "registryIdentityMatch": match,
            "wornArmorItemCount": armor, "equippedWeaponCount": weapons, "positionSampleCount": len(samples),
            "positionObservationSpanMs": (samples[-1]["observedAtMonotonic"]-samples[0]["observedAtMonotonic"])*1000,
            "positionDriftGameUnits": drift, "positionToleranceGameUnits": req.get("positionToleranceGameUnits"),
            "collisionDisableCommandCount": collision_count, "dontMove": latest["native"]["dontMove"],
            "spokenAliases": [registry["displayName"]] if match else [],
            "collisionCountBasis": "This domain's durable issued-command ledger; not global collision state or contact proof",
            "positionBasis": "Actual independent endpoint samples in this bounded interval; unobserved movement is not inferred"},
        "samples": copy.deepcopy(samples)}


def execute(session, args, deadline, policy):
    """Run inside the existing held owner; command identity comes from dispatch."""
    if type(args) is not dict or set(args) != {"operation", "request"}:
        raise BindingError("Inspection execution requires exact operation and request")
    policy = frozen_policy(session, policy)
    req = validate(args["operation"], args["request"])
    bounded_deadline(deadline)
    tag = req["actor"]["fixtureTag"]
    entry = session.state.get("interactiveActorFixtures", {}).get(tag)
    if not isinstance(entry, dict):
        raise BindingError("Inspection fixture tag has no actual owned creation witness")
    backend = Backend(session, deadline)
    state = session.state.setdefault("actorInspection", {"registry": {}, "commands": {}})
    if args["operation"] == "world.read":
        samples = [_sample(backend, entry, policy)]
        needed, span = req["minimumPositionSamples"], req["minimumObservationSpanMs"] / 1000
        while len(samples) < needed or samples[-1]["observedAtMonotonic"]-samples[0]["observedAtMonotonic"] < span:
            remaining_span = max(0, span-(time.monotonic()-samples[0]["observedAtMonotonic"]))
            backend.pause(max(.001, remaining_span / max(1, needed-len(samples))))
            samples.append(_sample(backend, entry, policy))
        return _summary(session, entry, req, samples)
    kind = ACTIONS[req["action"]]
    role = _role(policy, kind) if kind != "name" else None
    command_id = session.state.get("activeSemanticCommandId")
    if not isinstance(command_id, str) or not 1 <= len(command_id) <= 160:
        raise BindingError("Inspection mutation requires the actual active held command identity")
    key = hashlib.sha256((session.state["id"] + "\0" + command_id).encode("utf-8")).hexdigest()
    if key in state["commands"] or len(state["commands"]) >= 128:
        raise BindingError("Inspection command already attempted or command bound reached; never replay")
    if any(value.get("creationId") == entry["creationId"] and value.get("status") != "completed" for value in state["commands"].values()):
        raise BindingError("An uncertain inspection mutation blocks further preparation of this actor")
    registry = state["registry"].get(tag)
    if any(other_tag != tag and value.get("displayName", "").casefold() == req["displayName"].casefold()
           for other_tag, value in state["registry"].items()):
        raise BindingError("A spoken/display alias cannot resolve to multiple fixture identities")
    if any(value.get("kind") == "name" and value.get("creationId") != entry["creationId"] and
           value.get("request", {}).get("displayName", "").casefold() == req["displayName"].casefold()
           for value in state["commands"].values()):
        raise BindingError("An attempted reference name reserves its alias for that exact creation identity")
    before = _sample(backend, entry, policy)
    if kind != "name" and (not registry or registry.get("creationId") != entry["creationId"] or
            registry.get("displayName") != req["displayName"] or before["actor"]["displayName"] != req["displayName"]):
        raise BindingError("Preparation name does not resolve to the exact actually named fixture")
    command = {"status": "intent", "commandId": command_id, "requestId": uuid.uuid4().hex,
        "creationId": entry["creationId"], "reference": entry["reference"], "base": entry["base"], "kind": kind,
        "request": copy.deepcopy(req), "collisionDisableRequested": False, "before": before}
    state["commands"][key] = command
    session.save()
    try:
        if kind == "name":
            receipt = backend.call("npc_persistence", {"action": "prepare", "kind": "name", "requestId": command["requestId"],
                "reference": entry["reference"], "base": entry["base"], "displayName": req["displayName"],
                "timeoutMs": max(1, min(5000, int(backend.remaining()*1000)))})
            backend.remaining()
            if (not isinstance(receipt, dict) or receipt.get("prepared") is not True or
                    receipt.get("requestId") != command["requestId"]):
                raise BindingError("Reference-name preparation lacks its unique native completion; never replay")
        else:
            receipt = interactive_bindings.guarded_call(session, {"bindingId": role["id"],
                "self": {"reference": entry["reference"], "base": entry["base"]}, "args": [] if kind == "unequip" else [True]},
                deadline, policy)
        command["nativeReceipt"] = copy.deepcopy(receipt)
        session.save()
        while True:
            after = _sample(backend, entry, policy)
            armor, weapons = _equipment(after)
            matched = (after["actor"]["displayName"] == req["displayName"] if kind == "name" else
                       (armor == weapons == 0 if kind == "unequip" else after["native"]["dontMove"] is True))
            if matched: break
            backend.pause(.1)
        if kind == "name":
            state["registry"][tag] = {"runId": session.state["id"], "creationId": entry["creationId"],
                "referenceAtNaming": entry["reference"], "displayName": req["displayName"], "nameScope": "reference-only"}
        command.update(status="completed", after=after, completionBasis="Actual native reference state after exactly one guarded preparation call")
        session.save()
        result = _summary(session, entry, req, [after])
        result["preparation"] = {"completed": True, "kind": kind, "requestId": command["requestId"],
                                 "inventoryAction": "UnequipAll without item removal" if kind == "unequip" else "no inventory operation requested"}
        return result
    except BaseException as error:
        command.update(status="uncertain", reason=str(error))
        try: session.save()
        except Exception: pass
        raise
