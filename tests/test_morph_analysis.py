import copy
import math
import unittest

from skyrim_autotest.morph_analysis import compare, evaluate


def record(value, present=True, **fields):
    return {"available": True, "present": present, "value": value, **fields}


def snapshot():
    return {
        "sex": "female", "familyId": "Example.Geometry", "stage": "linked-beast", "snapshotLabel": "before",
        "weightRaw": 50, "weightNormalized": .5, "ownKey": "Example.Distribution",
        "sources": {
            "Positive": record(.8, keys=[record(9, key="Provider.One"), record(-4, key="Provider.Two")]),
            "Negative": record(-.6, keys=[record(-.6, key="Provider.One")]),
            "Zero": record(0, keys=[record(0, key="Provider.One")]),
        },
        "own": {"A": record(.4), "B": record(0, False), "C": record(0, False)},
        "targetKeys": {"A": [record(.4, key="Example.Distribution"), record(.9, key="Foreign.Target")], "B": [], "C": []},
    }


ROWS = [{"sourceMorph": "Positive", "targetMorph": "A", "gain": 2, "cap": .4},
        {"sourceMorph": "Negative", "targetMorph": "A", "gain": 1, "cap": .4},
        {"sourceMorph": "Zero", "targetMorph": "B", "gain": 1, "cap": 1}]
TARGETS = ["A", "B", "C"]


class MorphAnalysisTests(unittest.TestCase):
    def test_signed_sum_then_single_clamp_and_real_aggregate(self):
        result = evaluate(snapshot(), ROWS, TARGETS)
        self.assertEqual(result["rawTargetSums"]["A"], 1.0)
        self.assertEqual(result["expected"], {"A": .4, "B": 0, "C": 0})
        self.assertEqual(result["mapping"]["maxAbsoluteError"], 0)
        self.assertEqual(result["contributions"][1]["signedContribution"], -.6)
        self.assertEqual(result["sources"]["multipleKeySourceCount"], 1)
        self.assertFalse(result["sourceAggregationWasReconstructedFromKeys"])

    def test_cancellation_keeps_signed_inputs_and_does_not_clamp_each_row(self):
        raw = snapshot(); raw["sources"]["Negative"]["value"] = -1.5
        raw["sources"]["Negative"]["keys"][0]["value"] = -1.5
        result = evaluate(raw, ROWS, TARGETS)
        self.assertAlmostEqual(result["expected"]["A"], .04)
        self.assertAlmostEqual(result["mapping"]["maxAbsoluteError"], .36)

    def test_existing_zero_and_absent_zero_remain_distinct(self):
        before = snapshot(); after = copy.deepcopy(before)
        after["sources"]["Zero"] = record(0, False, keys=[])
        result = compare(evaluate(before, ROWS, TARGETS), evaluate(after, ROWS, TARGETS))
        self.assertEqual(result["comparison"]["changedActualHumanSourceCount"], 1)
        self.assertEqual(result["comparison"]["changedSourceKeyEntryCount"], 1)
        self.assertEqual(result["comparison"]["changedExpectedTargetCount"], 0)
        self.assertTrue(result["rawDiffs"]["sourceAggregates"][0]["before"]["present"])
        self.assertFalse(result["rawDiffs"]["sourceAggregates"][0]["after"]["present"])

    def test_clear_stages_still_retain_arithmetic_but_expect_zero(self):
        for stage in ("human-own-clear", "suppressed-own-clear"):
            raw = snapshot(); raw["stage"] = stage
            result = evaluate(raw, ROWS, TARGETS)
            self.assertEqual(result["expected"], dict.fromkeys(TARGETS, 0))
            self.assertEqual(result["rawTargetSums"]["A"], 1)
            self.assertEqual(result["mapping"]["maxAbsoluteError"], .4)

    def test_unmapped_actual_target_is_not_hidden(self):
        raw = snapshot(); raw["own"]["C"] = record(-.25)
        raw["targetKeys"]["C"] = [record(-.25, key=raw["ownKey"])]
        result = evaluate(raw, ROWS, TARGETS)
        self.assertEqual(result["mapping"]["unmappedOwnMaxAbsolute"], .25)
        self.assertEqual(result["mapping"]["evaluatedTargetCount"], 3)

    def test_foreign_target_diff_excludes_own_key_and_records_presence(self):
        before = snapshot(); after = copy.deepcopy(before); after["snapshotLabel"] = "after"
        after["own"]["A"]["value"] = .2; after["targetKeys"]["A"][0]["value"] = .2
        after["targetKeys"]["A"][1]["value"] = 0; after["targetKeys"]["A"][1]["present"] = False
        result = compare(evaluate(before, ROWS, TARGETS), evaluate(after, ROWS, TARGETS))
        self.assertEqual(result["preservation"]["changedForeignTargetEntryCount"], 1)
        self.assertEqual(result["comparison"]["changedOwnTargetEntryCount"], 1)
        self.assertEqual(result["comparison"]["changedSourceKeyEntryCount"], 0)
        self.assertEqual(result["afterSnapshot"], "after")
        self.assertEqual(result["rawDiffs"]["foreignTargetKeys"][0]["key"], "Foreign.Target")

    def test_full_key_changes_detected_even_with_unchanged_aggregate(self):
        before = snapshot(); after = copy.deepcopy(before)
        after["sources"]["Positive"]["keys"][0]["value"] += 1
        after["sources"]["Positive"]["keys"][1]["value"] -= 1
        result = compare(evaluate(before, ROWS, TARGETS), evaluate(after, ROWS, TARGETS))
        self.assertEqual(result["comparison"]["changedActualHumanSourceCount"], 0)
        self.assertEqual(result["comparison"]["changedSourceKeyEntryCount"], 2)
        self.assertEqual(result["preservation"]["changedHumanKeyEntryCount"], 2)

    def test_no_missing_or_unavailable_read_becomes_zero(self):
        mutations = [lambda raw: raw["sources"].pop("Zero"),
                     lambda raw: raw["own"].pop("C"),
                     lambda raw: raw["targetKeys"].pop("C"),
                     lambda raw: raw["sources"]["Zero"].pop("keys"),
                     lambda raw: raw["sources"]["Zero"].update(available=False),
                     lambda raw: raw["targetKeys"]["A"][1].update(available=False),
                     lambda raw: raw["own"]["C"].pop("present"),
                     lambda raw: raw["sources"]["Negative"].update(value=math.nan),
                     lambda raw: raw["sources"]["Negative"].update(value=math.inf),
                     lambda raw: raw["sources"]["Negative"].update(value=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                raw = snapshot(); mutation(raw)
                with self.assertRaises(ValueError): evaluate(raw, ROWS, TARGETS)

    def test_absent_nonzero_duplicate_keys_and_incoherent_own_are_rejected(self):
        raw = snapshot(); raw["sources"]["Negative"]["present"] = False
        with self.assertRaises(ValueError): evaluate(raw, ROWS, TARGETS)
        raw = snapshot(); raw["sources"]["Zero"]["keys"] *= 2
        with self.assertRaises(ValueError): evaluate(raw, ROWS, TARGETS)
        raw = snapshot(); raw["own"]["A"]["value"] = .5
        with self.assertRaises(ValueError): evaluate(raw, ROWS, TARGETS)

    def test_weight_unknown_is_not_normalized_to_zero(self):
        for field in ("weightRaw", "weightNormalized"):
            raw = snapshot(); raw[field] = -1
            with self.assertRaises(ValueError): evaluate(raw, ROWS, TARGETS)
        raw = snapshot(); raw["weightNormalized"] = .49
        self.assertAlmostEqual(evaluate(raw, ROWS, TARGETS)["actor"]["weightNormalizationAbsoluteError"], .01)

    def test_mapping_configuration_and_expected_coverage_are_required(self):
        invalid_rows = [ROWS + [{"sourceMorph": "Zero", "targetMorph": "A", "gain": 1, "cap": .5}],
                        ROWS + [{"sourceMorph": "Zero", "targetMorph": "Nonpublic", "gain": 1, "cap": 1}],
                        [dict(ROWS[0], gain=math.inf)] + ROWS[1:]]
        for rows in invalid_rows:
            with self.assertRaises(ValueError): evaluate(snapshot(), rows, TARGETS)
        with self.assertRaises(ValueError): evaluate(snapshot(), ROWS, TARGETS + ["C"])
        with self.assertRaises(ValueError): compare(snapshot(), snapshot())

    def test_raw_evidence_is_independent_of_later_caller_edits(self):
        raw = snapshot(); result = evaluate(raw, ROWS, TARGETS)
        raw["sources"]["Positive"]["keys"][0]["value"] = 100
        self.assertEqual(result["raw"]["sources"]["Positive"]["keys"][0]["value"], 9)


if __name__ == "__main__":
    unittest.main()
