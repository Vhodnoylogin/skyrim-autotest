"""Explicit common SE QA arena preparation; no subject or collision claims."""
from __future__ import annotations

import copy
import math
import time
import uuid

from . import actor_domain, native
from .api_contract import validate_description
from .fixture_actors import PLAYER, _pose
from .interactive_bindings import BindingError, _native_call, bounded_deadline
from .owned_saves import Events, lifecycle
from .platform import Backend
from .readiness_state import gameplay_ready


RECIPE = "qasmoke-west-navmesh-v1"
TRANSITION_RECIPE = "qasmoke-marker-moveto-v1"
TARGET = {"plugin": "Dragonborn.esm", "localId": "02A1B9"}
TARGET_POSITION = [-2633.919189453125, 1521.9630126953125, 6976.0]
OFFSET = [-116.08081, 14.03699, 0.0]
POSITION = [-2750.0, 1536.0, 6976.0]
HEADING = 90.0
CELL = "0x00032AE7"


def validate_config(value):
    if value is not None and value != RECIPE:
        raise ValueError("se_fixture_anchor requires the explicit qasmoke-west-navmesh-v1 recipe")
    return value


def _qualify(backend):
    contracts = {
        "Game": ("globalFunctions", {"GetFormFromFile": (["int", "string"], "form")}),
        "ObjectReference": ("memberFunctions", {
            "MoveTo": (["objectreference", "float", "float", "float", "bool"], "none"),
            "SetAngle": (["float", "float", "float"], "none"),
            **{name: ([], "float") for name in ("GetPositionX", "GetPositionY", "GetPositionZ", "GetAngleZ")},
        }),
    }
    for script, (scope, methods) in contracts.items():
        description = backend.call("papyrus", {"action": "describe", "script": script})
        for function, (params, returns) in methods.items():
            checked = validate_description(script, description, scope, {function: params})[0]
            if checked["native"] is not True or str(checked["returnType"]).casefold() != returns:
                raise BindingError("QA anchor native metadata differs for " + script + "." + function)


def transition_to_anchor(session, deadline, initial_read):
    """Request one native marker transition during the initial owned New Game.

    A returned callback does not establish cell loading or gameplay readiness.
    The common bootstrap performs those observations before completing its world.
    """
    config = copy.deepcopy(session.state.get("configuration", {}))
    if (config.get("se_fixture_transition") != TRANSITION_RECIPE
            or config.get("se_fixture_anchor") != RECIPE
            or config.get("game_edition") != "se" or config.get("se_new_game_ui") is not True):
        raise BindingError("QA marker transition requires the explicit SE native New Game and anchor recipes")
    bounded_deadline(deadline)
    if not callable(initial_read):
        raise BindingError("QA marker transition requires the current initial lifecycle reader")
    if session.state.get("fixtureTransition") or session.state.get("fixtureAnchor"):
        raise BindingError("QA marker transition or anchor was already attempted; never replay")
    backend = Backend(session, deadline)
    game = copy.deepcopy(session.state.get("game"))
    run_id = session.state.get("id")
    generation = session.state.get("ownedWorldGeneration", 0)
    initial = session.state.get("initialWorldTransition")
    if not isinstance(run_id, str) or not run_id or not isinstance(initial, dict):
        raise BindingError("QA marker transition requires an exact initial owned run")

    def owned():
        state = session.state
        if (state.get("id") != run_id or state.get("configuration") != config
                or not game or state.get("game") != game or not native.alive(game)
                or not state.get("testProfile") or type(generation) is not int or generation < 0
                or state.get("ownedWorldGeneration", 0) != generation
                or state.get("initialWorldTransition") is not initial
                or initial.get("mode") != "new-game" or initial.get("completed") is not False
                or initial.get("worldInvalidated") is True or initial.get("beforeGame") != game
                or state.get("ownedLoadTransition") or state.get("interactiveSession")
                or state.get("interactiveActorFixtures") or state.get("fixtureAnchor")
                or state.get("gameplayBootstrap", {}).get("completed") is True):
            raise BindingError("QA marker transition requires the unchanged initial owned New Game before gameplay/NPC actions")
        backend.remaining()

    def source_ready():
        owned()
        if initial_read() != ["newGame"]:
            raise BindingError("QA marker transition lacks the unique actual initial New Game lifecycle")
        owned()
        scene = backend.call("inspect", {"kind": "scene"})
        menus = backend.call("menu", {"action": "list", "includeFlags": True})
        if not gameplay_ready(scene, menus) or not isinstance(scene["cell"].get("formId"), str):
            raise BindingError("QA marker transition requires actual unblocked loaded source gameplay")
        if scene["cell"].get("formId") == CELL or scene["cell"].get("editorId") == "QASmoke":
            raise BindingError("QA marker transition cannot repeat an already loaded QASmoke transition")
        return scene, menus

    scene, menus = source_ready()
    _qualify(backend)
    target = actor_domain.form(backend.resolve(TARGET))
    if int(target, 16) & 0xFFFFFF != int(TARGET["localId"], 16) or int(target, 16) >> 24 >= 0xFE:
        raise BindingError("QA transition marker resolved to a foreign/dynamic reference")
    player_inc, player_row, _ = actor_domain.anchor(backend, PLAYER["reference"])
    target_inc, target_row, _ = actor_domain.anchor(backend, target)

    def identities(current_player, current_marker, current_scene):
        incarnation, row = current_player
        if (incarnation != player_inc or row.get("baseForm") != PLAYER["base"]
                or row.get("loaded3D") is not True or row.get("cellForm") != current_scene["cell"]["formId"]):
            raise BindingError("QA transition player incarnation/base/loaded source cell changed")
        incarnation, row = current_marker
        position = row.get("position")
        if (incarnation != target_inc or row.get("baseForm") != "0x0000003B" or row.get("cellForm") != CELL
                or not isinstance(position, list) or len(position) != 3
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in position)
                or math.dist(position, TARGET_POSITION) > .01
                or any(incarnation[key] != player_inc[key] for key in ("sessionId", "loadGeneration"))):
            raise BindingError("Actual Dragonborn QA transition marker identity/base/cell/position differs")

    identities((player_inc, player_row), (target_inc, target_row), scene)
    entry = {"recipe": TRANSITION_RECIPE, "status": "intent", "transitionId": uuid.uuid4().hex,
             "runId": run_id, "game": game, "worldGenerationBefore": generation,
             "sourceScene": scene, "sourceMenus": menus, "steps": {"MoveTo": "intent"},
             "target": {**TARGET, "reference": target, "incarnation": target_inc,
                        "position": target_row["position"], "loaded3D": target_row["loaded3D"]},
             "playerIncarnation": player_inc, "offsetGameUnits": [0.0, 0.0, 0.0],
             "nativeCallAttempted": False, "nativeCallbackReturned": False,
             "cellReadinessVerified": False, "subjectStarted": False,
             "basis": "native marker MoveTo alternative; original COC crash cause unproven"}
    session.state["fixtureTransition"] = entry
    try:
        session.save()
        current_scene, _ = source_ready()
        if current_scene["cell"] != scene["cell"]:
            raise BindingError("QA transition source cell changed before the native request")
        identities(actor_domain.anchor(backend, PLAYER["reference"])[:2],
                   actor_domain.anchor(backend, target)[:2], current_scene)
        owned()
        entry["nativeCallAttempted"] = True
        session.save()
        _native_call(backend, {"script": "ObjectReference", "function": "MoveTo", "returnType": "none"},
                     [{"form": target}, 0.0, 0.0, 0.0, False], PLAYER["reference"])
        owned()
        entry.update(status="returned", nativeCallbackReturned=True, steps={"MoveTo": "returned"})
        session.save()
        session.log("fixture-transition-native-returned", snapshot=copy.deepcopy(entry))
        return copy.deepcopy(entry)
    except BaseException as error:
        entry.update(status="uncertain", reason=str(error))
        try: session.save()
        except Exception: pass
        raise


def prepare_anchor(session, deadline):
    """Prepare this one opt-in arena before common gameplay bootstrap completes.

    The deadline is absolute monotonic, at most30seconds away. Every mutation
    has one durable intent and is attempted once; even a lost ACK forbids retry.
    """
    config = copy.deepcopy(session.state.get("configuration", {}))
    if validate_config(config.get("se_fixture_anchor")) != RECIPE or config.get("game_edition") != "se":
        raise BindingError("QA anchor requires the frozen explicit SE recipe")
    bounded_deadline(deadline)
    if "fixtureAnchor" in session.state or session.state.get("interactiveActorFixtures"):
        raise BindingError("QA anchor was already attempted or NPC creation began; never replay")
    backend = Backend(session, deadline)
    game = copy.deepcopy(session.state.get("game"))
    generation = session.state.get("ownedWorldGeneration")
    run_id = session.state.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise BindingError("QA anchor requires an exact current run")

    def ready():
        state = session.state
        transition = state.get("initialWorldTransition", {})
        if (state.get("id") != run_id or state.get("configuration") != config
                or not game or state.get("game") != game or not native.alive(game) or not state.get("testProfile")
                or type(generation) is not int or generation <= 0 or state.get("ownedWorldGeneration") != generation
                or transition.get("completed") is not True or transition.get("worldInvalidated") is True
                or transition.get("beforeGame") != game or transition.get("afterGame") != game
                or transition.get("worldGeneration") != generation or state.get("ownedLoadTransition")):
            raise BindingError("QA anchor requires the exact completed initial owned world")
        backend.remaining()
        events = Events(backend, transition["cursor"])
        try:
            if any(lifecycle(event) in ("preLoadGame", "postLoadGame", "newGame") for event in events.read()):
                raise BindingError("World transition invalidated QA anchor preparation")
        except Exception:
            transition["worldInvalidated"] = True
            session.save()
            raise
        transition["cursor"] = events.cursor
        scene = backend.call("inspect", {"kind": "scene"})
        menus = backend.call("menu", {"action": "list", "includeFlags": True})
        if not gameplay_ready(scene, menus, "QASmoke") or scene["cell"].get("formId") != CELL:
            raise BindingError("QA anchor requires actual QASmoke identity and gameplay/menu readiness")
        backend.remaining()
        return scene, menus

    ready()
    _qualify(backend)
    target = actor_domain.form(backend.resolve(TARGET))
    if int(target, 16) & 0xFFFFFF != int(TARGET["localId"], 16) or int(target, 16) >> 24 >= 0xFE:
        raise BindingError("QA marker resolved to a foreign/dynamic reference")
    player_inc, player_row, _ = actor_domain.anchor(backend, PLAYER["reference"])
    if player_row.get("baseForm") != PLAYER["base"] or player_row["loaded3D"] is not True or player_row.get("cellForm") != CELL:
        raise BindingError("Actual QA player reference/base/cell is unavailable")
    target_inc, target_row, _ = actor_domain.anchor(backend, target)

    def marker_matches(incarnation, row):
        position = row.get("position")
        if (incarnation != target_inc or row.get("baseForm") != "0x0000003B" or row.get("cellForm") != CELL
                or not isinstance(position, list) or len(position) != 3
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in position)
                or math.dist(position, TARGET_POSITION) > .01
                or any(incarnation[key] != player_inc[key] for key in ("sessionId", "loadGeneration"))):
            raise BindingError("Actual Dragonborn QA marker identity/base/cell/position differs from the recipe")
    marker_matches(target_inc, target_row)
    entry = {"recipe": RECIPE, "status": "intent", "preparationId": uuid.uuid4().hex,
             "runId": run_id, "game": game, "worldGeneration": generation, "steps": {}, "samples": [],
             "target": {**TARGET, "reference": target, "incarnation": target_inc, "position": target_row["position"]},
             "playerIncarnation": player_inc, "offsetGameUnits": list(OFFSET), "expectedPosition": list(POSITION),
             "headingDegrees": HEADING, "toleranceGameUnits": 4, "toleranceDegrees": 1,
             "provenance": {"selection": "offline Dragonborn.esm NAVM local02AF3E and placed references",
                            "physicsClearanceVerified": False, "subjectStarted": False}}
    session.state["fixtureAnchor"] = entry

    def guard():
        scene, menus = ready()
        current, row, _ = actor_domain.anchor(backend, PLAYER["reference"])
        if current != player_inc or row["loaded3D"] is not True or row.get("baseForm") != PLAYER["base"] or row.get("cellForm") != CELL:
            raise BindingError("Player incarnation/base/cell changed during QA anchor preparation")
        marker_matches(*actor_domain.anchor(backend, target)[:2])
        return scene, menus

    def invoke(function, values):
        guard()
        entry["steps"][function] = "intent"
        session.save()
        _native_call(backend, {"script": "ObjectReference", "function": function, "returnType": "none"},
                     values, PLAYER["reference"])
        entry["steps"][function] = "returned"
        session.save()

    try:
        session.save()
        invoke("MoveTo", [{"form": target}, *OFFSET, False])
        invoke("SetAngle", [0.0, 0.0, HEADING])
        previous = None
        settle_end = min(deadline, time.monotonic()+5)
        while True:
            guard()
            position, heading = _pose(backend, PLAYER["reference"])
            sample = {"atMonotonic": time.monotonic(), "position": position, "headingDegrees": heading,
                      "positionErrorGameUnits": math.dist(position, POSITION),
                      "headingErrorDegrees": abs((heading-HEADING+180) % 360-180)}
            entry["samples"].append(sample)
            session.save()
            session.log("fixture-anchor-readback", **sample)
            if sample["atMonotonic"] > settle_end:
                raise BindingError("QA anchor readback exceeded its settling deadline: " + repr(sample))
            within = sample["positionErrorGameUnits"] <= 4 and sample["headingErrorDegrees"] <= 1
            if previous and within and previous["positionErrorGameUnits"] <= 4 and previous["headingErrorDegrees"] <= 1:
                if (sample["atMonotonic"]-previous["atMonotonic"] >= .2
                        and math.dist(position, previous["position"]) <= 1
                        and abs((heading-previous["headingDegrees"]+180) % 360-180) <= 1):
                    break
            if time.monotonic() >= settle_end:
                raise BindingError("QA anchor did not settle at the requested pose: " + repr(sample))
            previous = sample
            backend.pause(.2)
        scene, menus = guard()
        entry.update(status="prepared", position=position, actualHeadingDegrees=heading,
                     stableSampleSpanSeconds=sample["atMonotonic"]-previous["atMonotonic"],
                     scene=scene, menus=menus)
        session.save()
        session.log("fixture-anchor-prepared", snapshot=copy.deepcopy(entry))
        return copy.deepcopy(entry)
    except BaseException as error:
        entry.update(status="uncertain", reason=str(error))
        try: session.save()
        except Exception: pass
        raise
