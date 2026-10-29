"""Bounded semantic morph sessions over one existing owned SE game.

Roles resolve only through frozen typed bindings. Raw SKEE aggregates/keys and
stock OBody events are independent of the subject's status/diagnostic getters.
No read initiates generation, assignment, configuration or action replay.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import uuid

from . import actor_domain, fixture_actors, interactive_bindings as bindings, morph_analysis, npc_persistence
from .interactive_bindings import BindingError
from .platform import Backend


DOMAINS = frozenset(("actor-fixture", "actor-fixture-identity", "human-preset-catalog", "human-provider-config",
                    "human-preset", "human-preset-state", "actor-race", "morph-link", "actor-morph-fixture",
                    "actor-morph-link-evaluation", "save-state", "actor-fixture-visibility"))
ROLES = frozenset(("status", "error", "assigned", "humanWeight", "beastWeight", "clear", "refresh", "configure", "race"))
READ_ROLES = frozenset(("status", "error", "assigned", "humanWeight", "beastWeight"))
PRESET_CATEGORIES = frozenset(("female", "male", "female_blacklisted", "male_blacklisted"))


def _text(value, label, *, empty=False):
    try:
        valid = isinstance(value, str) and (empty or bool(value)) and len(value.encode("utf-8")) <= 512 and "\0" not in value
    except UnicodeError:
        valid = False
    if not valid: raise BindingError(label + " requires bounded explicit UTF-8 text")
    return value


def _tag(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", value):
        raise BindingError("An exact bounded fixture/snapshot identifier is required")
    return value


def _actor(value):
    if type(value) is not dict or set(value) != {"fixtureTag"}: raise BindingError("Actor requires only fixtureTag")
    return _tag(value["fixtureTag"])


def validate_config(value, native_policy=None):
    if value is None: return None
    optional = {"providerOwnKeys", "providerKeyEvidence", "providerConfigSha256", "sourceMorphsBySex", "maximumFixtures"}
    if type(value) is not dict or not {"bindings", "testKeys"} <= set(value) or set(value) - {"bindings", "testKeys"} - optional:
        raise BindingError("morphSession requires bindings/testKeys and only documented evidence fields")
    mapping = value["bindings"]
    if "maximumFixtures" in value and (type(value["maximumFixtures"]) is not int or value["maximumFixtures"] not in (6, 12)):
        raise BindingError("maximumFixtures must explicitly select six or twelve owned references")
    if type(mapping) is not dict or set(mapping) != ROLES or any(not isinstance(v, str) or not v for v in mapping.values()):
        raise BindingError("morphSession must map all nine exact semantic binding roles")
    keys = value["testKeys"]
    if (type(keys) is not list or len(keys) != 3 or len(set(keys)) != 3 or
            any(not isinstance(k, str) or len(k) > 128 or ".Test." not in k or
                any(ord(c) < 33 or ord(c) > 126 for c in k) for k in keys)):
        raise BindingError("morphSession requires three distinct explicit bounded .Test. namespace keys")
    if ("providerOwnKeys" in value) != ("providerKeyEvidence" in value):
        raise BindingError("Provider ownership keys require paired frozen provenance evidence")
    if "providerOwnKeys" in value:
        owned = value["providerOwnKeys"]
        if (type(owned) is not list or not 1 <= len(owned) <= 8 or len(set(owned)) != len(owned) or
                any(not isinstance(k, str) or not k or len(k) > 128 or "\0" in k for k in owned) or set(owned) & set(keys)):
            raise BindingError("Invalid frozen provider-owned key identities")
        evidence = value["providerKeyEvidence"]
        if (type(evidence) is not dict or not re.fullmatch(r"[0-9a-f]{40}", str(evidence.get("sourceCommit", ""))) or
                not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("providerSha256", "")))):
            raise BindingError("Provider key provenance requires sourceCommit and providerSha256 pins; qualification verifies their correspondence")
    if "providerConfigSha256" in value and not re.fullmatch(r"[0-9a-f]{64}", str(value["providerConfigSha256"])):
        raise BindingError("Provider configuration requires an exact frozen SHA256")
    if "sourceMorphsBySex" in value:
        sources = value["sourceMorphsBySex"]
        if type(sources) is not dict or set(sources) != {"male", "female"}:
            raise BindingError("Explicit source catalogs require both male and female lists")
        for names in sources.values():
            if type(names) is not list or not 1 <= len(names) <= 256 or len(set(names)) != len(names):
                raise BindingError("Each source catalog must be complete, bounded and unique")
            for name in names: _text(name, "configured source morph")
    if native_policy is not None:
        policy = bindings.validate(native_policy)
        by_id = {entry["id"]: entry for entry in policy["bindings"]}
        for role, identifier in mapping.items():
            entry = by_id.get(identifier)
            if not entry or entry["effect"] != ("read" if role in READ_ROLES else "mutate"):
                raise BindingError("Morph role is missing or has the wrong frozen read/mutate effect: " + role)
            actor_count = len(entry["actorArgs"]) + int(entry["actorSelf"])
            if actor_count != 1: raise BindingError("Every morph binding requires exactly one actual owned actor role")
            other = [kind for i, kind in enumerate(entry["params"]) if i not in entry["actorArgs"]]
            expected = ["race"] if role == "race" else ["string"] if role == "configure" else []
            if other != expected or (role == "race" and entry["completion"] != "actor-race"):
                raise BindingError("Morph binding parameter roles differ from the semantic contract: " + role)
            returns = {"status": "int", "error": "string", "assigned": "string", "humanWeight": "float", "beastWeight": "float",
                       "clear": "bool", "refresh": "bool", "configure": "bool", "race": "none"}
            if entry["returnType"] != returns[role]: raise BindingError("Unexpected morph binding return type: " + role)
    return copy.deepcopy(value)


def validate(operation, req):
    if isinstance(req, dict) and req.get("domain") == "actor-fixture-visibility":
        from . import fixture_visibility
        return fixture_visibility.validate(operation, req)
    if isinstance(req, dict) and req.get("domain") == "actor-fixture-inspection":
        from . import actor_inspection
        return actor_inspection.validate(operation, req)
    if type(req) is not dict or req.get("domain") not in DOMAINS: return False
    domain = req["domain"]; action = req.get("action")
    read = domain in {"actor-fixture-identity", "human-preset-catalog", "human-provider-config", "human-preset-state", "actor-morph-link-evaluation"} or (domain == "save-state" and action is None)
    if operation != ("world.read" if read else "object.perform"): raise BindingError("Wrong operation for morph semantic domain")
    required, optional = {"domain"}, set()
    if domain == "actor-fixture":
        required |= {"action", "actor", "base", "placement", "persistence", "maximumCreations"}
        if (action != "create" or req.get("persistence") != "save-load-witness-required" or
                type(req.get("maximumCreations")) is not int or req["maximumCreations"] not in (6, 12)):
            raise BindingError("Only explicitly bounded persistent six/twelve-actor fixtures are supported")
        base = req.get("base")
        if type(base) is not dict or set(base) != {"plugin", "formId"}: raise BindingError("Exact plugin/local base record required")
        _text(base["plugin"], "base plugin"); actor_domain.form(base["formId"])
        if int(base["formId"], 16) > 0xffffff: raise BindingError("Base formId is a plugin-local identity")
        placement = req.get("placement")
        if (type(placement) is not dict or set(placement) not in ({"forwardGameUnits", "rightGameUnits"},
                {"forwardGameUnits", "rightGameUnits", "basis"})
                or "basis" in placement and placement["basis"] != fixture_actors.FIXED_BASIS):
            raise BindingError("Exact relative offsets and a supported placement basis required")
        actor_domain.bounded(placement["forwardGameUnits"], 0, 1000); actor_domain.bounded(placement["rightGameUnits"], -1000, 1000)
    elif domain == "actor-fixture-identity": required.add("actor")
    elif domain == "human-preset-catalog":
        required |= {"presets", "wolfPresetRequirement"}
        if req.get("wolfPresetRequirement") != "none": raise BindingError("Independent beast presets are outside this catalog contract")
        presets = req.get("presets")
        if type(presets) is not list or not 1 <= len(presets) <= 64: raise BindingError("Bounded explicit requested preset catalog required")
        names = set()
        for item in presets:
            if type(item) is not dict or set(item) != {"name", "sex", "set"} or item["sex"] not in ("male", "female"):
                raise BindingError("Requested presets require exact name, sex and source-set declaration")
            pair = (item["sex"], _text(item["name"], "preset name")); _text(item["set"], "preset source set")
            if pair in names: raise BindingError("Duplicate requested preset identity")
            names.add(pair)
    elif domain == "human-provider-config":
        required |= {"presetPoolPolicy", "baseSelectionPolicy", "otherActorsPolicy", "requiredDisablePresetDistribution"}
        optional.add("allowedAdditionalLoadedPresets")
        if req.get("presetPoolPolicy") != "exact-six-existing-human-preset-elements" or req.get("requiredDisablePresetDistribution") != "none":
            raise BindingError("Unsupported stock distribution configuration contract")
        _text(req.get("otherActorsPolicy"), "other actor policy")
        policies = req.get("baseSelectionPolicy")
        if type(policies) is not list or len(policies) not in (6, 12): raise BindingError("Six or twelve explicit complete base mappings are required")
        seen = set()
        for item in policies:
            if type(item) is not dict or set(item) != {"plugin", "baseFormId", "allowedHumanPresets"}: raise BindingError("Invalid base selection mapping")
            identity = (_text(item["plugin"], "plugin"), actor_domain.form(item["baseFormId"]))
            if int(identity[1], 16) > 0xffffff or identity in seen: raise BindingError("Invalid/duplicate plugin-local base mapping")
            seen.add(identity)
            pool = item["allowedHumanPresets"]
            if type(pool) is not list or not 1 <= len(pool) <= 64: raise BindingError("Each base requires a bounded nonempty actual preset pool")
            for name in pool: _text(name, "allowed preset")
            if len(set(pool)) != len(pool): raise BindingError("Duplicate base preset identity")
        if "allowedAdditionalLoadedPresets" in req:
            extras = req["allowedAdditionalLoadedPresets"]
            targets = set().union(*(set(item["allowedHumanPresets"]) for item in policies))
            if len(targets) != 6:
                raise BindingError("Pinned additional catalog requires exactly six target preset names in the complete base policy")
            if type(extras) is not list or len(extras) > 4096:
                raise BindingError("Pinned additional catalog requires at most4096 explicit category/name identities")
            identities = set()
            for item in extras:
                if (type(item) is not dict or set(item) != {"name", "category"} or
                        not isinstance(item["category"], str) or item["category"] not in PRESET_CATEGORIES):
                    raise BindingError("Additional preset requires exact native category and name")
                identity = (item["category"], _text(item["name"], "additional preset name"))
                if identity in identities or item["name"] in targets:
                    raise BindingError("Duplicate additional identity or target preset overlap")
                identities.add(identity)
    elif domain == "human-preset":
        required |= {"action", "actor"}
        if action == "assign":
            required |= {"presetName", "applyImmediately", "assignmentOnly"}
            _text(req.get("presetName"), "preset name", empty=True)
            if req.get("applyImmediately") is not True or req.get("assignmentOnly") is not False: raise BindingError("Real immediate preset application required")
        elif action not in ("unassign", "reset-own-provider-morphs"): raise BindingError("Unknown human preset mutation")
    elif domain == "human-preset-state":
        required.add("actor")
        optional |= {"requireStockGenerationWitness", "requireAutomaticOrigin", "expectedStockEventResponsibleInterface", "allowedHumanPresets", "manualGenerationOrAssignmentCallsBeforeThisObservation"}
        if set(req) & optional:
            automatic_fields = optional - {"expectedStockEventResponsibleInterface"}
            if (not automatic_fields <= set(req) or req["requireStockGenerationWitness"] is not True or
                    req["requireAutomaticOrigin"] is not True or req.get("expectedStockEventResponsibleInterface") is not None or
                    type(req["manualGenerationOrAssignmentCallsBeforeThisObservation"]) is not int or
                    req["manualGenerationOrAssignmentCallsBeforeThisObservation"] != 0):
                raise BindingError("Automatic origin requires the complete stock event/no-prior-manual-call contract")
            if type(req["allowedHumanPresets"]) is not list or not req["allowedHumanPresets"]: raise BindingError("Explicit allowed human preset pool required")
            for name in req["allowedHumanPresets"]: _text(name, "allowed human preset")
    elif domain == "actor-race":
        required |= {"action", "actor", "race", "preserveBaseRecord"}
        if action != "change-current-race" or req.get("preserveBaseRecord") is not True: raise BindingError("Only witnessed same-reference current-race change is supported")
        actor_domain.form(req.get("race"))
    elif domain == "morph-link":
        required |= {"action", "actor"}
        if action == "bind-resource-family": required.add("familyId"); _text(req.get("familyId"), "familyId")
        elif action not in ("clear-own", "refresh"): raise BindingError("Unknown morph-link mutation")
    elif domain == "actor-morph-fixture":
        required |= {"action", "actor"}
        if action == "set-keyed-coefficients-once":
            required |= {"values", "sourceOfValues"}; _text(req.get("sourceOfValues"), "fixture provenance")
            values = req.get("values")
            if type(values) is not list or not 1 <= len(values) <= 3: raise BindingError("One to three exact supplementary contributions required")
            seen = set()
            for value in values:
                if type(value) is not dict or set(value) != {"morph", "key", "value"}: raise BindingError("Fixture tuple requires morph/key/value")
                _text(value["morph"], "fixture morph"); _text(value["key"], "fixture key"); actor_domain.bounded(value["value"], -2, 2)
                if value["key"] in seen: raise BindingError("Duplicate supplementary fixture key")
                seen.add(value["key"])
        elif action == "remove-exact-keys-once":
            required.add("keys")
            if type(req.get("keys")) is not list or not 1 <= len(req["keys"]) <= 3 or len(set(req["keys"])) != len(req["keys"]): raise BindingError("Exact distinct supplementary keys required")
            for key in req["keys"]: _text(key, "fixture key")
        else: raise BindingError("Unknown supplementary morph fixture mutation")
    elif domain == "actor-morph-link-evaluation":
        required |= {"actor", "stage", "captureSnapshot", "familyId", "rows", "publicTargets", "ownKey", "sourceValueMeaning"}
        optional |= {"compareSnapshot", "preserveOtherActors", "minimumObservationSpanSeconds", "adoption", "manualFamilyConfigurationCallsBeforeThisObservation", "manualTesterMutationsBeforeThisObservation", "requireFullSourceKeyEnumeration", "zeroMeaning", "aggregateMeaning", "expectedSourcePolicy"}
        if req.get("stage") not in ("human-own-clear", "suppressed-own-clear", "linked-beast") or req.get("sourceValueMeaning") != "actual-SKEE-aggregate": raise BindingError("Unsupported stage or non-observed source aggregate semantics")
        _tag(req.get("captureSnapshot")); _text(req.get("familyId"), "familyId"); _text(req.get("ownKey"), "own key")
        rows, public = req.get("rows"), req.get("publicTargets")
        if type(rows) is not list or not 1 <= len(rows) <= 2048 or type(public) is not list or not 1 <= len(public) <= 256 or len(set(public)) != len(public): raise BindingError("Complete bounded mapping/public target list required")
        for name in public: _text(name, "public target")
        for row in rows:
            if type(row) is not dict or set(row) != {"sourceMorph", "targetMorph", "gain", "cap"}: raise BindingError("Mapping row fields are not exact")
            _text(row["sourceMorph"], "source morph"); _text(row["targetMorph"], "target morph")
            actor_domain.bounded(row["gain"], -1e6, 1e6); actor_domain.bounded(row["cap"], 0, 1e6)
            if row["targetMorph"] not in public: raise BindingError("Mapping target is not in the complete public target list")
        if "compareSnapshot" in req: _tag(req["compareSnapshot"])
        if "minimumObservationSpanSeconds" in req: actor_domain.bounded(req["minimumObservationSpanSeconds"], 0, 5)
        if "manualFamilyConfigurationCallsBeforeThisObservation" in req and req["manualFamilyConfigurationCallsBeforeThisObservation"] != 0: raise BindingError("Only pre-manual automatic family adoption is supported")
        if "manualTesterMutationsBeforeThisObservation" in req and (type(req["manualTesterMutationsBeforeThisObservation"]) is not int or req["manualTesterMutationsBeforeThisObservation"] != 0):
            raise BindingError("Pre-manual origin observation requires exact zero tester mutations")
        if "requireFullSourceKeyEnumeration" in req and req["requireFullSourceKeyEnumeration"] is not True: raise BindingError("Full independent key enumeration cannot be waived")
        peers = req.get("preserveOtherActors", [])
        if type(peers) is not list or len(peers) > 5: raise BindingError("At most five explicit peer preservation reads")
        for peer in peers:
            if type(peer) is not dict or set(peer) != {"fixtureTag", "snapshot"}: raise BindingError("Peer requires exact fixtureTag/snapshot")
            _tag(peer["fixtureTag"]); _tag(peer["snapshot"])
    elif domain == "save-state":
        required.add("saveLabel"); _tag(req.get("saveLabel"))
        if action == "save-disposable-once":
            required |= {"action", "actors", "scope", "maximumSaves"}
            if req.get("scope") != "current-temporary-profile" or req.get("maximumSaves") != 1 or type(req.get("actors")) is not list or len(req["actors"]) != 6 or len(set(req["actors"])) != 6: raise BindingError("Exactly one owned disposable six-actor save is supported")
            for tag in req["actors"]: _tag(tag)
        elif action == "load-owned-disposable-once":
            required |= {"action", "maximumLoads", "processRestart"}
            if req.get("maximumLoads") != 1 or req.get("processRestart") is not False: raise BindingError("Exactly one same-process owned load is supported")
        elif action is not None: raise BindingError("Unknown save-state action")
    if "actor" in required: _actor(req.get("actor"))
    if not required <= set(req) or set(req) - required - optional: raise BindingError("Unknown or missing fields in morph semantic request")
    return True


def _state(session):
    return session.state.setdefault("morphSession", {"owner": uuid.uuid4().hex, "fixtures": {}, "snapshots": {}, "mutations": [], "metadata": {}})


def _begin(session, request, **details):
    command = session.state.get("activeSemanticCommandId")
    if not isinstance(command, str) or not 1 <= len(command) <= 128 or "\0" in command:
        raise BindingError("A morph mutation requires the current durable owned semantic command identity")
    state = _state(session)
    if any(item.get("commandId") == command for item in state["mutations"]):
        raise BindingError("Semantic command already attempted; inspect retained evidence, never replay")
    intent = {"commandId": command, "request": copy.deepcopy(request), "status": "intent", **details}
    state["mutations"].append(intent)
    session.save()
    return intent


def _config(session, policy):
    frozen = bindings.frozen_policy(session, policy)
    config = session.state.get("configuration", {})
    if config.get("game_edition") != "se": raise BindingError("Morph sessions require the explicitly frozen SE target")
    settings = validate_config(config.get("interactive_session", {}).get("morphSession"), frozen)
    if settings is None: raise BindingError("Morph sessions are disabled in the frozen owned session")
    return settings, frozen


def _world(backend):
    fixture_actors._owned(backend, backend.s.state.get("game"))


def _call(backend, tool, request):
    _world(backend)
    remaining = backend.remaining()
    if remaining < .1: raise TimeoutError("Insufficient remaining time to begin a bounded native read/call")
    request = dict(request, timeoutMs=max(100, min(3000 if tool in ("inspect", "fixture_config") else 5000, int(remaining * 1000))))
    result = backend.call(tool, request)
    backend.remaining(); _world(backend)
    backend.s.log("morph-session-provider-read" if request.get("action") not in ("assign_preset", "unassign_preset", "reset_provider_morphs", "set_test_morphs", "remove_test_keys") else "morph-session-provider-mutation", tool=tool, request=request, raw=result)
    return result


def _fixture(session, tag):
    entry = session.state.get("interactiveActorFixtures", {}).get(tag)
    if not isinstance(entry, dict): raise BindingError("No actual same-run creation witness for fixture " + tag)
    spec = {"reference": entry.get("reference"), "base": entry.get("base")}
    fixture_actors.require_fixture(session, spec)
    semantic = _state(session)["fixtures"].get(tag)
    if not isinstance(semantic, dict) or semantic.get("creationId") != entry.get("creationId"):
        raise BindingError("Morph fixture does not match this adapter's pre-creation event intent")
    return entry, spec, semantic


def _envelope(raw, session):
    if (not isinstance(raw, dict) or raw.get("ok") is not True or not isinstance(raw.get("sessionId"), str) or not raw["sessionId"] or
            type(raw.get("loadGeneration")) is not int or raw["loadGeneration"] <= 0 or type(raw.get("producerMonotonicNs")) is not int):
        raise BindingError("Actual independent Observer process/world/time envelope unavailable")
    return raw


def _obody(backend, ref=None):
    request = {"kind": "world_observer", "obody": {"afterSequence": 0, "maximumEvents": 256}}
    if ref: request["obody"]["refs"] = [ref]
    raw = _envelope(_call(backend, "inspect", request), backend.s)
    value = raw.get("obody", {}); provider = value.get("provider", {}); retention = value.get("retention", {})
    if (value.get("status") != "available" or value.get("quality") != "complete" or provider.get("interfaceAvailable") is not True or
            provider.get("ready") is not True or provider.get("actorListenerRegistered") is not True or type(provider.get("epoch")) is not int or
            any(retention.get(name) != 0 for name in ("droppedTotal", "callbackFailuresTotal", "missingBeforeRetained", "truncatedTextFieldsTotal")) or
            retention.get("cursorAhead") is not False or retention.get("moreAvailable") is not False or type(value.get("events")) is not list):
        raise BindingError("Complete current-epoch official OBody listener/assignment evidence unavailable")
    return raw


def _copied_text(value):
    if type(value) is not dict or value.get("truncated") is not False or not isinstance(value.get("value"), str):
        raise BindingError("Complete copied provider text unavailable")
    return _text(value["value"], "provider text", empty=True)


def _assignment(raw, ref):
    value = raw["obody"]; rows = value.get("assignments")
    if type(rows) is not list or len(rows) != 1: raise BindingError("One independent current OBody assignment is required")
    row = rows[0]
    if row.get("actorForm") != ref or row.get("status") != "available" or row.get("providerEpoch") != value["provider"]["epoch"]:
        raise BindingError("OBody assignment belongs to another actor/readiness epoch")
    name = _copied_text(row.get("presetName"))
    if row.get("assigned") != bool(name): raise BindingError("OBody assignment presence/name mismatch")
    return name


def _catalog(backend):
    from .human_provider_config import read_catalog
    return read_catalog(lambda request: _call(backend, "morph_provider", request), backend.s.state["game"]["pid"])


def required_target_presets(request, requested_presets):
    """Cross-check declarations only; current availability requires a fresh catalog."""
    if "allowedAdditionalLoadedPresets" not in request: return None
    if type(requested_presets) is not list or len(requested_presets) != 6:
        raise BindingError("Pinned additional catalog requires a prior catalog declaration of exactly six targets")
    validate("world.read", {"domain": "human-preset-catalog", "presets": requested_presets, "wolfPresetRequirement": "none"})
    names = [item["name"] for item in requested_presets]
    expected = set().union(*(set(item["allowedHumanPresets"]) for item in request["baseSelectionPolicy"]))
    if len(set(names)) != 6 or set(names) != expected:
        raise BindingError("Six target catalog declarations must exactly cover the complete base policy")
    return {(item["sex"], item["name"]) for item in requested_presets}


def _guard(backend, tag):
    entry, spec, semantic = _fixture(backend.s, tag)
    observation = fixture_actors.guard(backend.s, spec, backend.end, backend.s.state["configuration"]["interactive_session"]["nativeBindings"])
    value = _call(backend, "morph_provider", {"action": "actor_status", "actorFormId": spec["reference"]})
    identity = value.get("identity", {})
    if (value.get("pid") != backend.s.state["game"]["pid"] or identity.get("pid") != value["pid"] or
            identity.get("actorFormId") != spec["reference"] or identity.get("baseFormId") != spec["base"] or
            identity.get("raceFormId") != observation["actor"]["race"] or identity.get("runtimeHandle") != observation["incarnation"]["runtimeHandle"] or
            value.get("identityCurrentAfterRead") is not True or type(identity.get("worldGeneration")) is not int or not identity.get("modelIdentity")):
        raise BindingError("Native control guard differs from actual disposable actor identity")
    return entry, spec, semantic, identity


def _binding_request(policy, config, role, spec, extras=()):
    entry = next(entry for entry in policy["bindings"] if entry["id"] == config["bindings"][role])
    arguments, remaining = [], iter(extras)
    for index in range(len(entry["params"])):
        arguments.append(spec if index in entry["actorArgs"] else next(remaining))
    request = {"bindingId": entry["id"], "args": arguments}
    if entry["actorSelf"]: request["self"] = spec
    return entry, request


def _diagnostics(backend, config, policy, spec):
    result = {}
    cache = _state(backend.s)["metadata"]
    for role in READ_ROLES:
        entry, request = _binding_request(policy, config, role, spec)
        key = entry["id"]
        if key not in cache:
            cache[key] = {"game": copy.deepcopy(backend.s.state["game"]), "metadata": bindings._metadata(backend, entry)}
        elif cache[key]["game"] != backend.s.state["game"]: raise BindingError("Diagnostic metadata belongs to a different process")
        arguments = [{"form": spec["reference"]} if i in entry["actorArgs"] else value for i, value in enumerate(request["args"])]
        result[role] = bindings._native_call(backend, entry, arguments, spec["reference"] if entry["actorSelf"] else None)
    if result["status"] < 0: raise BindingError("Subject status diagnostic unavailable")
    for role in ("humanWeight", "beastWeight"):
        actor_domain.bounded(result[role], -1, 1)
        if -1 < result[role] < 0: raise BindingError("Invalid subject weight diagnostic")
    return result


def _read_morphs(backend, spec, names):
    names = list(dict.fromkeys(names)); collected, envelopes = {}, []
    baseline = None
    for start in range(0, len(names), 32):
        requested = names[start:start + 32]
        raw = _envelope(_call(backend, "inspect", {"kind": "world_observer", "refs": [spec["reference"]], "actors": True,
            "skee": {"refs": [spec["reference"]], "morphs": requested}}), backend.s)
        refs, samples = raw.get("refs"), raw.get("skee")
        if type(refs) is not list or len(refs) != 1 or type(samples) is not list or len(samples) != 1:
            raise BindingError("Exact actual actor/SKEE sample unavailable")
        row, sample = refs[0], samples[0]; identity = row.get("identity", {}); actor = row.get("actor", {}); weight = actor.get("weight", {})
        if (row.get("status") != "available" or row.get("deleted") is not False or row.get("disabled") is not False or row.get("loaded3D") is not True or
                identity.get("form") != spec["reference"] or actor.get("status") != "available" or actor.get("baseForm") != spec["base"] or
                identity.get("loadGeneration") != raw["loadGeneration"] or type(identity.get("runtimeHandle")) is not int or identity["runtimeHandle"] <= 0 or
                weight.get("status") != "available" or type(actor.get("sex")) is not int or actor["sex"] not in (0, 1)):
            raise BindingError("Independent actor/base/weight/loaded identity unavailable")
        fixture_actors.require_fixture(backend.s, spec, {"actor": {"reference": spec["reference"], "base": spec["base"],
            "sex": ("male", "female")[actor["sex"]], "loaded3D": True},
            "incarnation": {"sessionId": raw["sessionId"], "loadGeneration": raw["loadGeneration"], "runtimeHandle": identity["runtimeHandle"]}})
        provider = sample.get("provider", {})
        root = row.get("rootIdentity", {})
        if (type(root) is not dict or type(root.get("sampledRootToken")) is not int or root["sampledRootToken"] <= 0 or
                root.get("firstPerson") is not False or type(provider.get("interfaceEpoch")) is not int or provider["interfaceEpoch"] <= 0):
            raise BindingError("Independent root/provider identity token unavailable")
        coherence = {"sessionId": raw["sessionId"], "loadGeneration": raw["loadGeneration"], "identity": identity,
                     "rootIdentity": row.get("rootIdentity"), "actor": actor, "providerEpoch": provider.get("interfaceEpoch")}
        if baseline is None: baseline = coherence
        if coherence != baseline or sample.get("status") != "available" or provider.get("status") != "available" or provider.get("interfaceVersion") != 5 or sample.get("identity") != identity or sample.get("rootIdentity") != row.get("rootIdentity"):
            raise BindingError("Actor/model/world/provider changed across independent morph batches")
        entries = sample.get("morphs")
        if type(entries) is not list or len(entries) != len(requested) or {entry.get("name") for entry in entries} != set(requested):
            raise BindingError("Complete requested source/target morph coverage unavailable")
        for item in entries:
            presence, aggregate, keys = item.get("namePresence", {}), item.get("aggregate", {}), item.get("keys", {})
            values = keys.get("entries")
            if (item.get("status") != "available" or presence.get("status") != "available" or type(presence.get("present")) is not bool or
                    aggregate.get("status") != "available" or keys.get("status") != "available" or type(values) is not list or
                    keys.get("truncated") is not False or keys.get("invalidKey") is not False or keys.get("nonFinite") is not False or keys.get("captureFailure") is not False or
                    keys.get("providerTraversalCompleted") is not True or keys.get("retainedCount") != len(values) or keys.get("callbackCount") != len(values)):
                raise BindingError("Independent morph aggregate/presence/key enumeration incomplete")
            numeric = actor_domain.bounded(aggregate.get("value"), -1e100, 1e100)
            records, seen = [], set()
            for value in values:
                key = _text(value.get("key"), "enumerated key")
                if value.get("status") != "available" or key in seen: raise BindingError("Unavailable/duplicate independent morph key")
                seen.add(key)
                records.append({"key": key, "available": True, "present": True, "value": actor_domain.bounded(value.get("value"), -1e100, 1e100)})
            collected[item["name"]] = {"available": True, "present": presence["present"], "value": numeric, "keys": records}
        envelopes.append(raw)
    return collected, baseline, envelopes


def _human(backend, tag, request=None, source_evidence=None):
    entry, spec, semantic = _fixture(backend.s, tag)
    raw = _obody(backend, spec["reference"]); name = _assignment(raw, spec["reference"])
    if source_evidence is None:
        config = backend.s.state["configuration"]["interactive_session"]["morphSession"]
        names = config.get("sourceMorphsBySex", {}).get(entry.get("actor", {}).get("sex"))
        if not names: raise BindingError("Human state requires a frozen complete source catalog for independent SKEE reads")
        measured, identity, source_raw = _read_morphs(backend, spec, names)
    else:
        names, measured = source_evidence
        source_raw = []
    if any(name not in measured or measured[name].get("available") is not True for name in names):
        raise BindingError("Human applied source read coverage is unavailable")
    after = _obody(backend, spec["reference"])
    if (after["sessionId"] != raw["sessionId"] or after["loadGeneration"] != raw["loadGeneration"] or
            after["obody"]["provider"]["epoch"] != raw["obody"]["provider"]["epoch"] or _assignment(after, spec["reference"]) != name):
        raise BindingError("Official assignment/readiness epoch changed during independent human source reads")
    raw = after
    value = {"assignedPreset": name, "officialApiReady": True, "appliedSourceReadUnavailableCount": 0,
             "appliedSourceReadCount": len(names), "assignmentBasis": "official_current_epoch_assignment_not_morph_completion",
             "sourceReadBasis": "complete_independent_SKEE_storage_reads_not_applied_or_rendered_completion"}
    history = _tester_mutations(backend.s, tag)
    value["testerMutationCounts"] = history
    intent = semantic["eventIntent"]
    same_epoch = (raw["sessionId"] == intent["observerSession"] and
                  raw["loadGeneration"] == intent["observerGeneration"] and
                  raw["obody"]["provider"]["epoch"] == intent["providerEpoch"])
    value["generationEvidence"] = {
        "sameCreationEpoch": same_epoch, "afterSequence": intent["afterSequence"],
        "events": copy.deepcopy([event for event in raw["obody"]["events"]
            if event.get("sequence", 0) > intent["afterSequence"] and
               event.get("actorForm") == spec["reference"] and event.get("event") == "OnActorGenerated"]),
        "automaticHostOriginVerified": False,
        "meaning": "raw_native_generation_events_not_proof_of_natural_host_invocation"}
    if request and request.get("requireAutomaticOrigin"):
        if (semantic.get("manualHumanCalls") != 0 or any(history.values()) or
                semantic.get("worldGeneration") != backend.s.state["ownedWorldGeneration"]):
            raise BindingError("Manual provider action or world load invalidated pre-manual stock origin")
        intent = semantic["eventIntent"]
        if raw["sessionId"] != intent["observerSession"] or raw["loadGeneration"] != intent["observerGeneration"] or raw["obody"]["provider"]["epoch"] != intent["providerEpoch"]:
            raise BindingError("Stock generation witness belongs to a changed observer/readiness epoch")
        matches = []
        for event in raw["obody"]["events"]:
            if event.get("sequence", 0) <= intent["afterSequence"]: continue
            if event.get("channel") == "observer_lifecycle" and event.get("event") == "world_boundary":
                raise BindingError("Observer world boundary occurred between creation intent and automatic origin read")
            if event.get("actorForm") != spec["reference"] or event.get("event") != "OnActorGenerated": continue
            if (event.get("channel") != "obody_native_actor_change" or event.get("stockInternalGeneration") is not True or
                    event.get("responsibility") != "obody_internal_stock" or event.get("providerReadyAtReceipt") is not True or
                    event.get("providerEpoch") != intent["providerEpoch"] or event.get("producerMonotonicNs", -1) < intent["producerMonotonicNs"] or
                    event.get("responsibleOwner", {}).get("value") is not None):
                continue
            preset = _copied_text(event.get("presetName"))
            if preset in request["allowedHumanPresets"] and preset == name: matches.append(event)
        value.update(assignmentCatalogMatchCount=int(name in request["allowedHumanPresets"]),
                     stockGenerationWitnessCount=len(matches), automaticGenerationWitnessCount=len(matches),
                     stockEventResponsibleInterface=None if matches else "unavailable")
        semantic["automaticWitnesses"] = copy.deepcopy(matches)
        backend.s.save()
    return {"human": value, "providerObservation": raw, "sourceObservations": source_raw}


def _tester_mutations(session, tag):
    """Count durable intents, including uncertain calls and old counter formats."""
    counts = {"humanProvider": 0, "family": 0, "race": 0, "testMorph": 0}
    domains = {"human-preset": "humanProvider", "morph-link": "family",
               "actor-race": "race", "actor-morph-fixture": "testMorph"}
    for intent in _state(session)["mutations"]:
        request = intent.get("request", {})
        if intent.get("fixtureTag") == tag and request.get("domain") in domains:
            counts[domains[request["domain"]]] += 1
    return counts


def _capture_once(backend, config, policy, request):
    tag = _actor(request["actor"]); entry, spec, semantic = _fixture(backend.s, tag)
    if "manualTesterMutationsBeforeThisObservation" in request and any(_tester_mutations(backend.s, tag).values()):
        raise BindingError("Tester mutation intent preceded the declared untouched origin observation")
    source_names = list(dict.fromkeys(row["sourceMorph"] for row in request["rows"]))
    extra_names = [item["morph"] for item in semantic.get("fixtureValues", [])]
    provider_before = _obody(backend, spec["reference"])
    measured, identity, envelopes = _read_morphs(backend, spec, source_names + request["publicTargets"] + extra_names)
    diagnostic = _diagnostics(backend, config, policy, spec)
    human = _human(backend, tag, source_evidence=(source_names, measured))
    provider_after = human["providerObservation"]
    if (provider_before["sessionId"] != provider_after["sessionId"] or provider_before["loadGeneration"] != provider_after["loadGeneration"] or
            provider_before["obody"]["provider"]["epoch"] != provider_after["obody"]["provider"]["epoch"] or
            _assignment(provider_before, spec["reference"]) != human["human"]["assignedPreset"]):
        raise BindingError("Official assignment/readiness changed across the complete independent snapshot")
    # Re-read actor/world/root after the separate subject diagnostics/assignment.
    last, final_identity, final_raw = _read_morphs(backend, spec, [source_names[0]])
    if identity != final_identity: raise BindingError("Actor/model/world changed across subject diagnostics")
    actor = identity["actor"]; weight = actor["weight"]
    raw = {"sex": ("male", "female")[actor["sex"]], "familyId": request["familyId"], "stage": request["stage"],
        "weightRaw": weight["rawNPCWeight"], "weightNormalized": weight["normalizedNPCWeight"], "ownKey": request["ownKey"],
        "sources": {name: measured[name] for name in source_names}, "own": {}, "targetKeys": {},
        "fixtureTag": tag, "snapshotLabel": request["captureSnapshot"], "identity": identity,
        "ownedWorldGeneration": backend.s.state["ownedWorldGeneration"], "reference": spec["reference"],
        "timestamp": time.time(), "subjectDiagnostics": diagnostic, "humanAssignment": human["human"]["assignedPreset"],
        "providerObservations": envelopes + final_raw, "obodyObservation": human["providerObservation"]}
    for name in request["publicTargets"]:
        keys = measured[name]["keys"]; raw["targetKeys"][name] = keys
        matches = [value for value in keys if value["key"] == request["ownKey"]]
        raw["own"][name] = {"available": True, "present": bool(matches), "value": matches[0]["value"] if matches else 0.0}
    result = morph_analysis.evaluate(raw, request["rows"], request["publicTargets"])
    result["actor"].update(reference=spec["reference"], base=spec["base"], baseFormId=spec["base"], race=actor_domain.form(actor["race"]),
        sex=raw["sex"], loaded3D=True, identityMismatchCount=0)
    result["claw"] = {"status": diagnostic["status"], "lastError": diagnostic["error"], "assignedIndependentPreset": diagnostic["assigned"],
                      "humanWeight": diagnostic["humanWeight"], "beastWeight": diagnostic["beastWeight"]}
    result["human"] = human["human"]
    result["weight"] = {}
    role = "humanWeight" if request["stage"] == "human-own-clear" else "beastWeight"
    field = "humanObservationAbsoluteError" if role == "humanWeight" else "beastObservationAbsoluteError"
    known = diagnostic[role] >= 0
    result["quality"] = "complete" if known else "partial"
    result["weight"].update(observationStatus="available" if known else "unavailable", observationRole=role,
                            subjectDiagnostic=diagnostic[role])
    result["weight"][field] = abs(diagnostic[role] - raw["weightNormalized"]) if known else None
    if not known:
        # -1 is the public subject's legitimate not-yet-observed sentinel. It
        # must fail a numeric assertion without aborting the owned read channel
        # or replacing an unknown observation with an invented zero/error.
        result["weight"]["reason"] = "The subject has not observed a valid weight in this form; diagnostic -1 remains unknown"
    if semantic.get("humanBaseWeightRaw") is None and request["stage"] == "human-own-clear":
        semantic["humanBaseWeightRaw"] = raw["weightRaw"]
    if semantic.get("humanBaseWeightRaw") is not None:
        result["weight"]["sameReferenceAbsoluteError"] = abs(raw["weightRaw"] - semantic["humanBaseWeightRaw"])
    if "manualFamilyConfigurationCallsBeforeThisObservation" in request and semantic.get("manualFamilyCalls", 0) != 0:
        raise BindingError("Manual family configuration preceded the declared automatic adoption observation")
    if "restorationWitness" in entry:
        restored = npc_persistence.require_restoration(backend.s, entry)
        native = restored["native"]
        checks = [native.get("currentReference") == spec["reference"], native.get("base") == spec["base"],
                  native.get("runtimeHandle") == identity["identity"]["runtimeHandle"], native.get("creationId") == entry["creationId"],
                  native.get("formResolved") is True, native.get("handleResolved") is True]
        result["persistence"] = {"identityRemapMismatchCount": sum(not value for value in checks), "rawWitness": copy.deepcopy(restored)}
    fixture_records = {}
    for index, key in enumerate(config["testKeys"]):
        configured = [item for item in semantic.get("fixtureValues", []) if item["key"] == key]
        found = [(name, item) for name, value in measured.items() for item in value["keys"] if item["key"] == key]
        fixture_records[key] = {"entries": [{"morph": name, **item} for name, item in found], "presenceObserved": True}
        if configured:
            target = configured[0]["morph"]; matches = [item for name, item in found if name == target]
            fixture_records[key].update(morph=target, present=bool(matches), value=matches[0]["value"] if matches else 0.0)
    result["fixture"] = {"remainingOwnedTestKeyCount": sum(len(value["entries"]) for value in fixture_records.values()),
        "foreignSourceKeyCount": sum(item["key"] in config["testKeys"] for value in raw["sources"].values() for item in value["keys"]),
        "rawTestKeyObservations": fixture_records}
    for key, field in zip(config["testKeys"], ("foreignHumanValue", "zeroHumanKeyValue", "foreignWolfValue")):
        if "value" in fixture_records[key]: result["fixture"][field] = fixture_records[key]["value"]
    if "value" in fixture_records[config["testKeys"][1]]: result["fixture"]["zeroHumanKeyPresenceRecorded"] = True
    if config.get("providerOwnKeys"):
        values = [abs(item["value"]) for value in raw["sources"].values() for item in value["keys"] if item["key"] in config["providerOwnKeys"]]
        result["human"].update(providerOwnMaxAbsoluteCoefficient=max(values, default=0.0), providerOwnKeyEvidence=copy.deepcopy(config["providerKeyEvidence"]),
                               providerOwnCoefficientScope="complete_configured_source_names_only")
    else:
        result["human"]["providerOwnCoefficientStatus"] = "unavailable_without_frozen_key_identity_evidence"
    return result


def _retained_snapshot(request, result, command_id):
    """A prior observation for comparison, with full proof retained in the log.

    Keep complete numeric/presence/key maps and their original identities/times.
    Provider envelopes, peer captures and interval sample copies are evidence in
    the full result; duplicating them in mutable state grows with every capture.
    """
    fields = ("sex", "familyId", "stage", "quality", "expected", "actualOwnKey", "absoluteErrors", "rawTargetSums",
              "actor", "claw", "human", "weight", "fixture", "mapping", "sources", "own")
    compact = {name: copy.deepcopy(result[name]) for name in fields if name in result}
    compact["raw"] = copy.deepcopy({name: value for name, value in result["raw"].items()
                                    if name not in ("providerObservations", "obodyObservation")})
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"fixtureTag": _actor(request["actor"]), "snapshotLabel": request["captureSnapshot"],
            "commandId": command_id, "basis": "retained_prior_observation_not_a_fresh_read",
            "fullResultSha256": hashlib.sha256(encoded).hexdigest(),
            "fullResultDigestEncoding": "JSON_UTF8_sort_keys_compact_allow_nan_false",
            "request": copy.deepcopy(request), "result": compact}


def _baseline_provenance(snapshot):
    return {name: copy.deepcopy(snapshot.get(name)) for name in
            ("fixtureTag", "snapshotLabel", "commandId", "basis", "fullResultSha256", "fullResultDigestEncoding")}


def _snapshot_result(backend, config, policy, request):
    state = _state(backend.s); tag = _actor(request["actor"])
    result = _capture_once(backend, config, policy, request)
    started = time.monotonic(); interval = [copy.deepcopy(result)]
    span = request.get("minimumObservationSpanSeconds", 0)
    # A long copy/scheduling pause is not a second observation. For a declared
    # span always take a later real sample, even if elapsed time already passed.
    while span:
        remaining = span - (time.monotonic() - started)
        if remaining > 0: backend.pause(min(.2, remaining))
        current = _capture_once(backend, config, policy, request)
        interval.append(copy.deepcopy(current))
        current["own"]["maxAbsoluteCoefficient"] = max(item["own"]["maxAbsoluteCoefficient"] for item in interval)
        current["mapping"]["maxAbsoluteError"] = max(item["mapping"]["maxAbsoluteError"] for item in interval)
        if any(item["weight"]["observationStatus"] != "available" for item in interval):
            field = "humanObservationAbsoluteError" if request["stage"] == "human-own-clear" else "beastObservationAbsoluteError"
            current["quality"] = "partial"
            current["weight"].update(observationStatus="unavailable", reason="One or more actual samples in the required observation span have an unknown subject weight")
            current["weight"][field] = None
        result = current
        if time.monotonic() - started >= span: break
    if span:
        statuses = [sample["claw"]["status"] for sample in interval]
        transitions = sum(before != after for before, after in zip(statuses, statuses[1:]))
        result["interval"] = {"observedSpanSeconds": time.monotonic() - started, "samples": interval, "actionReplayCount": 0,
                              "observedStatuses": statuses, "statusTransitionCount": transitions,
                              "lastObservedStatus": statuses[-1]}
        result["claw"].update(statusObservationStatus="unavailable" if transitions else "available", lastObservedStatus=statuses[-1])
        if transitions:
            # A legitimate queued subject transition is observation evidence,
            # not an instrument/identity exception. Its final sample cannot
            # establish a stable status for the requested observation span.
            result["quality"] = "partial"
            result["claw"]["status"] = None
            result["claw"]["statusObservationReason"] = "Actual subject statuses changed during the required observation span"
    if "compareSnapshot" in request:
        previous = state["snapshots"].get(request["compareSnapshot"])
        if not previous or previous["fixtureTag"] != tag: raise BindingError("Exact named same-fixture comparison snapshot unavailable")
        comparison = morph_analysis.compare(previous["result"], result)
        result.update(comparison)
        result["comparisonBaseline"] = _baseline_provenance(previous)
        result["weight"]["persistedObservationAbsoluteError"] = abs(result["raw"]["weightNormalized"] - previous["result"]["raw"]["weightNormalized"])
    if "preserveOtherActors" in request:
        peer_results, changed = [], 0
        for peer in request["preserveOtherActors"]:
            previous = state["snapshots"].get(peer["snapshot"])
            if not previous or previous["fixtureTag"] != peer["fixtureTag"] or peer["fixtureTag"] == tag: raise BindingError("Exact peer snapshot/fixture comparison unavailable")
            peer_request = copy.deepcopy(previous["request"])
            current = _capture_once(backend, config, policy, peer_request)
            differences = morph_analysis.compare(previous["result"], current)
            count = sum(len(differences["rawDiffs"][key]) for key in ("sourceAggregates", "sourceKeys", "targetKeys"))
            for field in ("race", "sex", "base", "weightRaw", "weightNormalized"):
                if previous["result"]["actor"].get(field) != current["actor"].get(field): count += 1
            for field in ("status", "lastError", "assignedIndependentPreset", "humanWeight", "beastWeight"):
                if previous["result"]["claw"][field] != current["claw"][field]: count += 1
            if previous["result"]["human"]["assignedPreset"] != current["human"]["assignedPreset"]: count += 1
            changed += count; peer_results.append({"fixtureTag": peer["fixtureTag"], "snapshot": peer["snapshot"], "changedEntryCount": count,
                "baselineEvidence": _baseline_provenance(previous), "comparison": differences, "actual": current})
        result.setdefault("preservation", {})["changedOtherActorEntryCount"] = changed
        result["peerComparisons"] = peer_results
    label = request["captureSnapshot"]
    previous = state["snapshots"].get(label)
    if previous and (previous["fixtureTag"] != tag or previous["request"] != request): raise BindingError("A snapshot label cannot be repurposed for another request/actor")
    command_id = backend.s.state.get("activeSemanticCommandId")
    state["snapshots"][label] = _retained_snapshot(request, result, command_id)
    backend.s.log("morph-session-snapshot", label=label, fixtureTag=tag, commandId=command_id, rawResult=result)
    backend.s.save()
    return result


def execute(session, args, deadline, policy):
    operation, request = args.get("operation"), args.get("request")
    if not validate(operation, request): raise BindingError("Unrelated request passed to morph session executor")
    config, policy = _config(session, policy)
    if request["domain"] == "actor-fixture-visibility":
        from . import fixture_visibility
        return fixture_visibility.perform(session, request, deadline, policy)
    if request["domain"] == "actor-fixture-inspection":
        from . import actor_inspection
        return actor_inspection.execute(session, args, deadline, policy)
    backend = Backend(session, deadline); _world(backend)
    state = _state(session); domain = request["domain"]; action = request.get("action")
    if domain == "human-preset-catalog":
        catalog = _catalog(backend); state["requestedPresets"] = copy.deepcopy(request["presets"])
        missing = [item for item in request["presets"] if item["name"] not in catalog["categories"][item["sex"]]]
        session.save()
        return {"catalog": {"missingRequestedPresetCount": len(missing), "maleRequestedCount": sum(item["sex"] == "male" for item in request["presets"]),
            "femaleRequestedCount": sum(item["sex"] == "female" for item in request["presets"]), "missing": missing, "actual": catalog,
            "sourceSetDeclarationObservedInNativeAPI": False}}
    if domain == "human-provider-config":
        from .human_provider_config import inspect_config
        required_target_presets(request, state.get("requestedPresets"))
        if len(request["baseSelectionPolicy"]) > config.get("maximumFixtures", 6):
            raise BindingError("Complete base policy exceeds the frozen platform fixture opt-in")
        if "providerConfigSha256" not in config: raise BindingError("Actual VFS configuration read requires a frozen expected config SHA256")
        raw = _call(backend, "fixture_config", {"action": "obody"})
        catalog = _catalog(backend)
        observed = inspect_config(raw, request, expected_pid=session.state["game"]["pid"],
            expected_sha256=config["providerConfigSha256"], maximum_fixtures=config.get("maximumFixtures", 6),
            requested_presets=state.get("requestedPresets"), catalog=catalog, expected_game_path=session.state["game"]["path"])
        readiness = _obody(backend)
        return {"human": {"officialApiReady": readiness["obody"]["provider"]["ready"], "config": observed},
                "catalogObservation": catalog, "providerObservation": readiness}
    if domain == "actor-fixture":
        tag = _actor(request["actor"])
        maximum = config.get("maximumFixtures", 6)
        if request["maximumCreations"] > maximum:
            raise BindingError("Requested fixture count exceeds the frozen platform opt-in")
        if tag in state["fixtures"] or len(state["fixtures"]) >= min(maximum, request["maximumCreations"]):
            raise BindingError("Owned fixture attempt bound reached; never replay a tag")
        base = actor_domain.form(backend.resolve({"plugin": request["base"]["plugin"], "localId": f'{int(request["base"]["formId"],16):06X}'}))
        if base not in policy["fixtureActorBases"]: raise BindingError("Resolved base is outside the frozen disposable allowlist")
        observed = _obody(backend)
        semantic = {"status": "creation-intent", "createdMonotonicNs": time.monotonic_ns(), "manualHumanCalls": 0, "manualFamilyCalls": 0, "worldGeneration": session.state["ownedWorldGeneration"],
                    "eventIntent": {"observerSession": observed["sessionId"], "observerGeneration": observed["loadGeneration"],
                        "providerEpoch": observed["obody"]["provider"]["epoch"], "afterSequence": observed["obody"]["retention"]["latestSequence"],
                        "producerMonotonicNs": observed["producerMonotonicNs"]}}
        intent = _begin(session, request, fixtureTag=tag)
        state["fixtures"][tag] = semantic; session.save()
        result = fixture_actors.create(session, {"tag": tag, "base": base, **request["placement"], "persistentForOwnedSave": True}, deadline, policy)
        entry = session.state["interactiveActorFixtures"][tag]
        semantic.update(status="created", creationId=entry["creationId"])
        intent.update(status="created", creationId=entry["creationId"]); session.save()
        return result
    if domain == "save-state":
        if action is None: return npc_persistence.observe(session, {"saveTag": request["saveLabel"]}, deadline, policy)
        translated = {"action": "save" if action == "save-disposable-once" else "load", "saveTag": request["saveLabel"]}
        if translated["action"] == "save": translated["fixtureTags"] = request["actors"]
        intent = _begin(session, request)
        result = npc_persistence.perform(session, translated, deadline, policy)
        intent.update(status="returned", result=copy.deepcopy(result)); session.save()
        return result
    tag = _actor(request["actor"]); entry, spec, semantic = _fixture(session, tag)
    if domain == "actor-fixture-identity":
        observation = fixture_actors.guard(session, spec, deadline, policy)
        expected_identity = copy.deepcopy(entry.get("nativePersistentIdentity"))
        if "restorationWitness" in entry:
            restored = npc_persistence.require_restoration(session, entry)["native"]
            expected_identity.update(currentReference=restored["currentReference"], currentVmHandle=restored["currentVmHandle"],
                                     runtimeHandle=restored["runtimeHandle"])
        identity = fixture_actors._persistent_identity(backend, spec, observation, expected_identity)
        return {"actor": {**observation["actor"], "baseFormId": spec["base"], "sameRunCreationWitnessCount": 1,
                          "persistentSaveWitnessAvailable": identity.get("persistent") is True}, "nativePersistentIdentity": identity, "creationWitness": copy.deepcopy(entry["creationWitness"])}
    if domain == "human-preset-state": return _human(backend, tag, request)
    if domain == "actor-morph-link-evaluation": return _snapshot_result(backend, config, policy, request)
    if domain in ("actor-race", "morph-link"):
        role = "race" if domain == "actor-race" else {"clear-own": "clear", "refresh": "refresh", "bind-resource-family": "configure"}[action]
        extras = [request["race"]] if role == "race" else [request["familyId"]] if role == "configure" else []
        unused, bound = _binding_request(policy, config, role, spec, extras)
        intent = _begin(session, request, fixtureTag=tag, bindingRequest=bound)
        if role != "race": semantic["manualFamilyCalls"] += 1
        session.save()
        receipt = bindings.guarded_call(session, bound, deadline, policy)
        intent.update(status="returned", receipt=copy.deepcopy(receipt)); session.save()
        if role == "race": return receipt.get("result", receipt)
        if type(receipt.get("returned")) is not bool: raise BindingError("Actual subject queue-admission Bool unavailable")
        return {"request": {"admitted": receipt["returned"], "completed": False}, "bindingReceipt": receipt}
    entry, spec, semantic, guard = _guard(backend, tag)
    if domain == "human-preset":
        native_action = "reset_provider_morphs" if action == "reset-own-provider-morphs" else "unassign_preset" if action == "unassign" or not request.get("presetName", "") else "assign_preset"
        native_request = {"action": native_action}
        if native_action == "assign_preset": native_request["presetName"] = request["presetName"]
    else:
        requested_keys = [value["key"] for value in request["values"]] if action == "set-keyed-coefficients-once" else request["keys"]
        if not set(requested_keys) <= set(config["testKeys"]): raise BindingError("Fixture mutation key is outside the frozen exact three-key allowlist")
        native_request = {"action": "set_test_morphs" if action == "set-keyed-coefficients-once" else "remove_test_keys"}
        if action == "set-keyed-coefficients-once":
            native_request["values"] = request["values"]
        else: native_request["keys"] = request["keys"]
    native_request.update(actorFormId=spec["reference"], guard=guard, owner=state["owner"], command=uuid.uuid4().hex)
    intent = _begin(session, request, fixtureTag=tag, nativeRequest=native_request)
    if domain == "human-preset": semantic["manualHumanCalls"] += 1
    elif action == "set-keyed-coefficients-once": semantic["fixtureValues"] = copy.deepcopy(request["values"])
    session.save()
    receipt = _call(backend, "morph_provider", native_request)
    if receipt.get("status") != "call_returned" or receipt.get("providerAccepted") is not True or receipt.get("identityCurrentAfterCall") is not True or receipt.get("identity") != guard:
        intent.update(status="unconfirmed", receipt=copy.deepcopy(receipt)); session.save()
        raise BindingError("Actual provider call was rejected or its outcome/actor identity is uncertain; never replay")
    intent.update(status="call-returned", receipt=copy.deepcopy(receipt)); session.save()
    result = {"request": {"admitted": True, "completed": False}, "providerReceipt": receipt}
    if domain == "human-preset" and native_request["action"] in ("assign_preset", "unassign_preset"):
        result["request"]["assignmentAccepted"] = receipt["providerAccepted"]
    return result
