"""Explicit, frozen native Papyrus bindings for disposable-NPC interaction.

No binding is enabled by default. Metadata establishes the callable signature,
not a function's safety, queue completion, visible appearance or host authority.
"""
from __future__ import annotations

import copy
import math
import re
import time

from .native_session import settings as native_settings
from . import actor_domain, native
from .api_contract import validate_description
from .platform import Backend


class BindingError(ValueError):
    pass


_TYPES = {"none", "bool", "int", "float", "string", "actor", "objectreference", "form", "race"}
_ARRAYS = {"bool[]", "int[]", "float[]", "string[]"}
_WORLD_FUNCTIONS = {"loadgame", "startnewgame", "quittomainmenu", "quitgame", "savegame", "delete",
                    "deletewhenable", "moveto", "movetonode", "setposition", "placeatme", "enable", "disable"}


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", value):
        raise BindingError(label + " must be one explicit identifier")
    return value


def _type(value, parameter=False):
    if not isinstance(value, str) or value.casefold() not in _TYPES | _ARRAYS:
        raise BindingError("Unsupported explicit Papyrus type")
    result = value.casefold()
    if parameter and result == "none":
        raise BindingError("None is not a binding parameter type")
    return result


def validate(policy=None):
    """Normalize optional policy without I/O. None means disabled, not defaults."""
    if policy is None:
        return None
    if (type(policy) is not dict or set(policy) != {"schemaVersion", "fixtureActorBases", "allowedRaceForms", "bindings"}
            or type(policy["schemaVersion"]) is not int or policy["schemaVersion"] != 1):
        raise BindingError("Native bindings require schemaVersion, fixtureActorBases, allowedRaceForms and bindings")
    result = {"schemaVersion": 1}
    for field in ("fixtureActorBases", "allowedRaceForms"):
        values = policy[field]
        if not isinstance(values, list) or len(values) > 128:
            raise BindingError(field + " must be an explicit bounded form list")
        normalized = [actor_domain.form(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise BindingError("Duplicate form identity in " + field)
        if field == "fixtureActorBases" and "0x00000007" in normalized:
            raise BindingError("The player base cannot be a disposable-NPC base")
        result[field] = normalized
    entries = policy["bindings"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise BindingError("bindings must contain 1..64 explicit declarations")
    required = {"id", "script", "function", "scope", "params", "returnType", "effect", "actorSelf", "actorArgs", "raceArgs", "completion"}
    result["bindings"], identifiers, methods = [], set(), set()
    for original in entries:
        if type(original) is not dict or set(original) != required:
            raise BindingError("Binding fields must exactly match the declaration contract")
        entry = copy.deepcopy(original)
        if not isinstance(entry["id"], str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,95}", entry["id"]):
            raise BindingError("Binding id must be one bounded explicit identifier")
        for key in ("script", "function"):
            _name(entry[key], key)
        method = (entry["script"].casefold(), entry["function"].casefold())
        if entry["id"] in identifiers or method in methods:
            raise BindingError("Duplicate binding id or callable declaration")
        identifiers.add(entry["id"]); methods.add(method)
        if entry["scope"] not in ("member", "global") or entry["effect"] not in ("read", "mutate") or type(entry["actorSelf"]) is not bool:
            raise BindingError("Binding requires explicit member/global scope and read/mutate effect")
        if not isinstance(entry["params"], list) or len(entry["params"]) > 12:
            raise BindingError("Binding requires at most twelve exact parameter types")
        entry["params"] = [_type(value, True) for value in entry["params"]]
        entry["returnType"] = _type(entry["returnType"])
        for field in ("actorArgs", "raceArgs"):
            indexes = entry[field]
            if (not isinstance(indexes, list) or any(type(i) is not int or not 0 <= i < len(entry["params"]) for i in indexes)
                    or len(set(indexes)) != len(indexes)):
                raise BindingError(field + " must contain unique declared parameter indexes")
            entry[field] = sorted(indexes)
        if set(entry["actorArgs"]) & set(entry["raceArgs"]):
            raise BindingError("Actor and race parameter roles cannot overlap")
        if entry["actorSelf"] != (entry["scope"] == "member"):
            raise BindingError("Member bindings require an actor self; global bindings forbid self")
        if any(entry["params"][i] not in ("actor", "objectreference") for i in entry["actorArgs"]):
            raise BindingError("Actor argument roles require Actor or ObjectReference parameters")
        if any(entry["params"][i] not in ("race", "form") for i in entry["raceArgs"]):
            raise BindingError("Race argument roles require Race or Form parameters")
        for i, value in enumerate(entry["params"]):
            if value in ("actor", "objectreference") and i not in entry["actorArgs"]:
                raise BindingError("Every actor/reference parameter requires an actor guard")
            if value in ("race", "form") and i not in entry["raceArgs"]:
                raise BindingError("Every race/form parameter requires an explicit race allowlist role")
        if entry["effect"] == "mutate" and not (entry["actorSelf"] or entry["actorArgs"]):
            raise BindingError("Every mutation requires a guarded disposable-NPC target")
        if (entry["actorSelf"] or entry["actorArgs"]) and not result["fixtureActorBases"]:
            raise BindingError("Actor bindings require a nonempty disposable base allowlist")
        if entry["raceArgs"] and not result["allowedRaceForms"]:
            raise BindingError("Race parameters require a nonempty race allowlist")
        if entry["function"].casefold() in _WORLD_FUNCTIONS:
            raise BindingError("World/save/creation/deletion operations are outside native binding scope")
        if entry["completion"] not in ("native-return", "actor-race"):
            raise BindingError("Unsupported binding completion contract")
        set_race = method == ("actor", "setrace")
        if set_race or entry["completion"] == "actor-race":
            if not (set_race and entry["completion"] == "actor-race" and entry["scope"] == "member" and
                    entry["params"] == ["race"] and entry["returnType"] == "none" and entry["effect"] == "mutate" and
                    entry["actorSelf"] and entry["actorArgs"] == [] and entry["raceArgs"] == [0]):
                raise BindingError("Actor.SetRace requires its exact guarded actor-race readback contract")
        result["bindings"].append(entry)
    return result


def _scalar(value, value_type, *, returned=False):
    if value_type == "none":
        if value is not None: raise BindingError("Native return must be None")
    elif value_type == "bool":
        if type(value) is not bool: raise BindingError("Expected a real Bool")
    elif value_type == "int":
        if type(value) is not int or not -(2**31) <= value < 2**31: raise BindingError("Expected a bounded Papyrus Int")
    elif value_type == "float":
        if type(value) not in (int, float) or abs(value) > 3.402823466e38 or not math.isfinite(value):
            raise BindingError("Expected a finite Papyrus Float")
        value = float(value)
    elif value_type == "string":
        try:
            valid = isinstance(value, str) and len(value.encode("utf-8")) <= 4096 and "\x00" not in value
        except UnicodeError:
            valid = False
        if not valid:
            raise BindingError("Expected a bounded UTF-8 String")
    elif returned and value_type in ("actor", "objectreference", "form", "race"):
        if type(value) is not dict or "formId" not in value: raise BindingError("Native form return is unavailable")
        actor_domain.form(value["formId"])
    else:
        raise BindingError("Unsupported unguarded argument type")
    return value


def _value(value, value_type, *, returned=False):
    if value_type.endswith("[]"):
        if not isinstance(value, list) or len(value) > 4096: raise BindingError("Expected a bounded native array")
        return [_scalar(item, value_type[:-2], returned=returned) for item in value]
    return _scalar(value, value_type, returned=returned)


def _metadata(backend, entry):
    description = backend.call("papyrus", {"action": "describe", "script": entry["script"]})
    scope = "memberFunctions" if entry["scope"] == "member" else "globalFunctions"
    rows = description.get(scope) if isinstance(description, dict) else None
    matches = [row for row in rows or [] if isinstance(row, dict) and str(row.get("name", "")).casefold() == entry["function"].casefold()]
    if len(matches) != 1:
        raise BindingError("Unique declared native function metadata is unavailable")
    try:
        checked = validate_description(entry["script"], description, scope, {entry["function"]: entry["params"]})[0]
    except (AssertionError, TypeError, AttributeError) as exc:
        raise BindingError("Live native metadata does not match the frozen binding") from exc
    if checked["native"] is not True or str(checked["returnType"]).casefold() != entry["returnType"]:
        raise BindingError("Live native function/return signature does not match the frozen binding")
    return checked


def _native_call(backend, entry, arguments, target):
    request = {"action": "call", "script": entry["script"], "function": entry["function"], "args": arguments,
               "timeoutMs": max(1, min(6000, int(backend.remaining() * 1000)))}
    if target is not None:
        request["self"] = {"form": target}
    response = backend.call("papyrus", request)
    backend.remaining()
    if (not isinstance(response, dict) or response.get("called") is not True or "returned" not in response
            or str(response.get("returnedType", "")).casefold() != entry["returnType"]):
        raise BindingError("Native callback/typed return is unavailable; never replay this call")
    return _value(response["returned"], entry["returnType"], returned=True)


def _compact(observation):
    return {"actor": observation["actor"], "incarnation": observation["incarnation"]}


def frozen_policy(session, policy):
    policy = validate(policy)
    configured = validate(native_settings(session.state.get("configuration", {})).get("nativeBindings"))
    if policy is None or configured is None or policy != configured:
        raise BindingError("Native bindings are disabled or differ from the frozen run configuration")
    return policy


def bounded_deadline(deadline):
    try:
        remaining = deadline - time.monotonic() if type(deadline) in (int, float) else float("nan")
        bounded = math.isfinite(remaining) and 0 < remaining <= 30
    except (OverflowError, ValueError):
        bounded = False
    if not bounded:
        raise BindingError("Binding requires a finite absolute deadline with at most thirty seconds remaining")


def guarded_call(session, request, deadline, policy):
    """Invoke one declared binding in a currently owned world. Never retry here."""
    from .fixture_actors import require_fixture
    policy = frozen_policy(session, policy)
    if (type(request) is not dict or set(request) - {"bindingId", "args", "self"}
            or not {"bindingId", "args"} <= set(request) or not isinstance(request["args"], list)):
        raise BindingError("Binding request accepts only bindingId, complete args and optional actor self")
    entries = [entry for entry in policy["bindings"] if entry["id"] == request["bindingId"]]
    if len(entries) != 1: raise BindingError("Binding id is not declared in the frozen policy")
    entry = entries[0]
    if len(request["args"]) != len(entry["params"]) or ("self" in request) != entry["actorSelf"]:
        raise BindingError("Binding arguments/self do not match the exact declared signature")
    bounded_deadline(deadline)
    arguments, actors, target = [], {}, None
    def actor(value):
        spec = actor_domain.actor_spec(value)
        if spec["reference"] == "0x00000014" or spec["base"] not in policy["fixtureActorBases"]:
            raise BindingError("Target must be a non-player actor with an explicitly allowed disposable base")
        require_fixture(session, spec)
        if spec["reference"] in actors and actors[spec["reference"]] != spec:
            raise BindingError("The same actor reference cannot declare different bases")
        actors[spec["reference"]] = spec
        return spec["reference"]
    if entry["actorSelf"]:
        target = actor(request["self"])
    for index, (value, value_type) in enumerate(zip(request["args"], entry["params"])):
        if index in entry["actorArgs"]:
            arguments.append({"form": actor(value)})
        elif index in entry["raceArgs"]:
            race = actor_domain.form(value)
            if race not in policy["allowedRaceForms"]: raise BindingError("Race is outside the explicit allowedRaceForms")
            arguments.append({"form": race})
        else:
            arguments.append(_value(value, value_type))
    game = copy.deepcopy(session.state.get("game"))
    backend = Backend(session, deadline)
    def world():
        if (not game or session.state.get("game") != game or not native.alive(game) or
                not session.state.get("testProfile") or session.state.get("gameplayBootstrap", {}).get("completed") is not True):
            raise BindingError("Binding requires the exact live owned game and disposable gameplay profile")
        backend.remaining()
        backend.guard_world()
        backend.remaining()
    world()
    metadata = _metadata(backend, entry)
    before = {ref: actor_domain.observe_actor(backend, spec) for ref, spec in actors.items()}
    for ref, observation in before.items():
        require_fixture(session, actors[ref], observation)
    if any(value["actor"]["loaded3D"] is not True for value in before.values()):
        raise BindingError("Every bound actor must have actual loaded 3D")
    def same_actors():
        world()
        current = {ref: actor_domain.observe_actor(backend, spec) for ref, spec in actors.items()}
        for ref, observation in current.items():
            require_fixture(session, actors[ref], observation)
            if observation["incarnation"] != before[ref]["incarnation"] or observation["actor"]["loaded3D"] is not True:
                raise BindingError("Actor incarnation/loaded state changed; do not replay the binding")
        backend.remaining()
        if session.state.get("game") != game or not native.alive(game):
            raise BindingError("Owned game identity changed across binding guards")
        return current
    session.log("interactive-binding-qualified", bindingId=entry["id"], metadata=metadata,
                actors=[_compact(value) for value in before.values()], atomicSnapshot=False)
    if entry["completion"] == "actor-race":
        class RaceBackend(Backend):
            invoked = False
            def pap(self, script, function, values=None, target=None, **kwargs):
                if (script, function) == ("Actor", "SetRace"):
                    if self.invoked: raise BindingError("A race mutation cannot be invoked twice")
                    same_actors()
                    self.invoked = True
                    return _native_call(self, entry, arguments, target)
                return super().pap(script, function, values, target, **kwargs)
        race_backend = RaceBackend(session, deadline)
        result = actor_domain.perform(race_backend, {"action": "set-race", "actor": actors[target], "race": request["args"][0]})
        same_actors()
        return {"bindingId": entry["id"], "effect": "mutate", "domainCompletion": "observed-race-readback", "result": result}
    same_actors()
    # Exactly one actual declared call, with every argument supplied explicitly.
    returned = _native_call(backend, entry, arguments, target)
    after = same_actors()
    return {"bindingId": entry["id"], "effect": entry["effect"], "returned": returned, "returnedType": entry["returnType"],
            "actors": [_compact(value) for value in after.values()],
            "domainCompletion": "unverified" if entry["effect"] == "mutate" else "not-applicable",
            "basis": "Actual type-checked native callback return; no inferred queue completion, applied morphs or rendered appearance"}
