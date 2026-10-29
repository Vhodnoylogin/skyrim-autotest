"""Prepare an untouched SE OBody/SKEE component probe from semantic test inputs.

Never submits an order, changes the subject, installs, launches or qualifies tools.
The probe measures all six references and both complete vector templates. Two
representative references additionally exercise naming/undressing/position holds.
Application errors and coefficients remain observations, not mod acceptance.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from skyrim_autotest import platform


def pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def request(step):
    return step.get("parameters", {}).get("request", {})


def build_probe(source, identifier, *, source_chat, source_thread_id):
    if source.get("schemaVersion") != 2 or source.get("subjectPlan", {}).get("interface") != "polygon-actions/1":
        raise ValueError("An explicit schema2 semantic source is required")
    steps = source["subjectPlan"]["steps"]
    for step in steps:
        try:
            platform.validate({"operation": step["operation"], **step.get("parameters", {})})
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Probe refuses an invalid or unsupported source operation") from error
    domains = [request(step).get("domain") for step in steps]
    if (domains[:3] != [None, "human-preset-catalog", "human-provider-config"] or
            any(domains.count(domain) != 1 for domain in (None, "human-preset-catalog", "human-provider-config"))):
        raise ValueError("Exactly one readiness/catalog/config sequence must precede every fixture")
    fixtures = {}
    for step in steps:
        req = request(step)
        if req.get("domain") == "actor-fixture":
            tag = req["actor"]["fixtureTag"]
            if tag in fixtures: raise ValueError("A fixture creation cannot repeat")
            fixtures[tag] = None
        if req.get("domain") == "actor-fixture-identity":
            tag = req["actor"]["fixtureTag"]
            sexes = [rule["equals"] for rule in step.get("assert", [])
                     if rule.get("field") == "actor.sex" and rule.get("equals") in ("male", "female")]
            if tag not in fixtures or len(sexes) != 1: raise ValueError("Exact fixture sex/creation declaration required")
            fixtures[tag] = sexes[0]
    if len(fixtures) != 6 or list(fixtures.values()).count("male") != 3 or list(fixtures.values()).count("female") != 3:
        raise ValueError("Six independently declared human fixtures, three of each sex, required")
    # Counts alone permit duplicate actor selectors to hide another fixture's
    # missing origin/vector/transition. Verify the original per-reference order
    # and complete sex-specific template before selecting any representatives.
    templates = {}
    for tag, sex in fixtures.items():
        local = [step for step in steps if request(step).get("actor", {}).get("fixtureTag") == tag
                 and request(step).get("domain") != "actor-fixture-inspection"]
        shape = [(request(step).get("domain"), request(step).get("stage")) for step in local]
        expected = [("actor-fixture", None), ("actor-fixture-identity", None), ("human-preset-state", None),
                    ("actor-morph-link-evaluation", "human-own-clear"), ("actor-race", None),
                    ("actor-morph-link-evaluation", "linked-beast"), ("actor-race", None),
                    ("actor-morph-link-evaluation", "human-own-clear")]
        if shape != expected: raise ValueError("Complete ordered per-fixture creation/origin/race/vector sequence required")
        origin = request(local[2])
        if origin.get("requireStockGenerationWitness") is not True or origin.get("requireAutomaticOrigin") is not True:
            raise ValueError("Every fixture requires its real automatic generation witness")
        baseline, beast, returned = [request(local[index]) for index in (3, 5, 7)]
        if (beast.get("compareSnapshot") != baseline["captureSnapshot"] or
                returned.get("compareSnapshot") != baseline["captureSnapshot"] or
                len({baseline["captureSnapshot"], beast["captureSnapshot"], returned["captureSnapshot"]}) != 3):
            raise ValueError("Exact per-fixture baseline and distinct phase snapshots required")
        human_races = [r["equals"] for r in local[1].get("assert", []) if r.get("field") == "actor.race" and "equals" in r]
        if len(human_races) != 1 or request(local[6]).get("race") != human_races[0] or request(local[4]).get("race") == human_races[0]:
            raise ValueError("Distinct beast transition followed by the declared human race return required")
        for index, value in ((3, baseline), (5, beast), (7, returned)):
            template = {key: value[key] for key in ("familyId", "rows", "publicTargets", "ownKey", "sourceValueMeaning")}
            if sex not in templates: templates[sex] = copy.deepcopy(template)
            if template != templates[sex]: raise ValueError("Complete sex-specific vector template changed or was truncated")
            source_count = len({row["sourceMorph"] for row in value["rows"]})
            counts = {r["field"]: r.get("equals") for r in local[index].get("assert", [])}
            if counts.get("sources.aggregateReadCount") != source_count or counts.get("own.targetReadCount") != len(value["publicTargets"]):
                raise ValueError("Original declared complete source/target coverage must match every retained vector")
    representatives = {next(tag for tag, actual in fixtures.items() if actual == sex) for sex in ("male", "female")}
    expected_domains = {"actor-fixture", "actor-fixture-identity", "actor-fixture-inspection", "human-preset-catalog",
                        "human-provider-config", "human-preset-state", "actor-morph-link-evaluation", "actor-race"}
    result, coverage = [], []
    for original in steps:
        req = request(original)
        domain = req.get("domain")
        if domain is not None and domain not in expected_domains:
            raise ValueError("Probe refuses provider assignment/configuration/morph writes or unknown domains")
        if domain is None and original["operation"] != "state.read":
            raise ValueError("Only the common world-readiness operation is accepted without a domain")
        tag = req.get("actor", {}).get("fixtureTag")
        if tag is not None and tag not in fixtures: raise ValueError("Unknown actor selector")
        if domain == "actor-fixture-inspection" and tag not in representatives: continue
        step = copy.deepcopy(original)
        if domain == "actor-morph-link-evaluation":
            if "preserveOtherActors" in req:
                raise ValueError("Peer snapshots require a separately declared component probe")
            sources = set(row["sourceMorph"] for row in req["rows"])
            targets = req["publicTargets"]
            # Read completeness is tool evidence. Numerical agreement with the
            # subject's output/status is deliberately left unasserted here.
            step["assert"] = [
                {"field": "actor.identityMismatchCount", "equals": 0},
                {"field": "actor.loaded3D", "equals": True},
                {"field": "actor.weightNormalizationAbsoluteError", "max": .0001},
                {"field": "sources.unavailableReadCount", "equals": 0},
                {"field": "sources.aggregateReadCount", "equals": len(sources)},
                {"field": "own.unavailableReadCount", "equals": 0},
                {"field": "own.targetReadCount", "equals": len(targets)},
                {"field": "raw.weightRaw", "exists": True},
                {"field": "raw.weightNormalized", "exists": True}]
            step["assert"] += [copy.deepcopy(rule) for rule in original.get("assert", [])
                               if rule.get("field") in ("actor.race", "actor.sex")]
            if "compareSnapshot" in req:
                step["assert"].append({"field": "comparisonBaseline", "exists": True})
                step["assert"].append({"field": "preservation.changedHumanKeyEntryCount", "exists": True})
            coverage.append({"step": step["name"], "tag": tag, "sex": fixtures[tag],
                             "sourceCount": len(sources), "rowCount": len(req["rows"]), "targetCount": len(targets)})
        elif domain == "human-provider-config":
            step["assert"] += [{"field": "human.config.baseSelectionCount", "equals": len(req["baseSelectionPolicy"])},
                {"field": "human.config.missingExpectedPresetCount", "equals": 0},
                {"field": "human.config.missingAllowedAdditionalPresetCount", "equals": 0},
                {"field": "human.config.inMemoryConfigObserved", "equals": False},
                {"field": "human.config.includeConfigurationObserved", "equals": False}]
        platform.validate({"operation": step["operation"], **step.get("parameters", {})})
        result.append(step)
    if not 1 <= len(result) <= 64 or len(coverage) != 18:
        raise ValueError("Probe must retain all eighteen complete human/beast/return observations within64cases")
    domains = [request(step).get("domain") for step in result]
    if domains.count("actor-fixture") != 6 or domains.count("actor-race") != 12 or domains.count("human-preset-state") != 6:
        raise ValueError("Complete automatic creation/origin and same-reference race sequence required")
    probe = {"schemaVersion": 2, "id": identifier, "mode": "automatic", "sourceChat": source_chat,
        "sourceThreadId": source_thread_id,
        "subject": "Tool-only untouched automatic human provider and independent morph-read qualification",
        "purpose": "Qualify exact SE adapter routes; numerical subject output remains unassessed. No mod acceptance or physics.",
        "profile": source["profile"], "inputs": copy.deepcopy(source["inputs"]),
        "collect": ["Full independent raw catalog, VFS main-file scope, stock events, source/key vectors and subject diagnostics",
                    "Six creation/identity/race witnesses, two inspection representatives, original inputs unchanged",
                    "Actual normal owned exit, restoration and archived removed temporary profile"],
        "subjectPlan": {**copy.deepcopy(source["subjectPlan"]), "steps": result},
        "testing": {"start": {"kind": "check", "name": result[0]["name"]},
                    "checks": [{"name": step["name"], "role": "subject"} for step in result]}}
    return probe, {"qualified": False, "gameStarted": False, "subjectModAccepted": False,
        "fixtureTags": list(fixtures), "inspectionRepresentatives": sorted(representatives), "vectorCoverage": coverage,
        "testingRoleMeaning": "The subject of this separate tool qualification is the adapter, never the original mod",
        "limitations": ["Main VFS file does not prove the effective merged OBody configuration",
                        "No tester assignment, generation, family configuration or morph setter",
                        "No rendered geometry, physics, save/load or audio acceptance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject-order", required=True, type=Path)
    parser.add_argument("--id", required=True)
    parser.add_argument("--source-chat", required=True)
    parser.add_argument("--source-thread-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    before = pin(args.subject_order)
    source = json.loads(args.subject_order.read_text(encoding="utf-8-sig"))
    probe, coverage = build_probe(source, args.id, source_chat=args.source_chat, source_thread_id=args.source_thread_id)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, data in (("probe-order.json", probe), ("probe-scope.json", {"sourceOrder": before, **coverage})):
        (args.output / name).write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if pin(args.subject_order) != before: raise ValueError("Source order changed during preparation")
    print(json.dumps({"output": str(args.output), "steps": len(probe["subjectPlan"]["steps"]), "qualified": False}))


if __name__ == "__main__": main()
