import copy
import hashlib
import json
import unittest

from skyrim_autotest import human_provider_config as subject
from skyrim_autotest.interactive_bindings import BindingError


GAME = "D:/Fixture/SkyrimSE.exe"
PATH = "D:/Fixture/Data/SKSE/Plugins/OBody_presetDistributionConfig.json"


def fixture():
    targets = [{"name": f"{prefix}{number}", "sex": sex, "set": "Reviewed source"}
               for sex, prefix in (("female", "F"), ("male", "M")) for number in (1, 2, 3)]
    policies = [{"plugin": plugin, "baseFormId": f"0x{number:08X}", "allowedHumanPresets": [target["name"]]}
                for plugin in ("Master.esm", "Fixture.esp") for number, target in enumerate(targets, 0x800)]
    extras = ([{"category": "female", "name": f"Stock female {number}"} for number in range(12)] +
              [{"category": "male", "name": f"Stock male {number}"} for number in range(15)] +
              [{"category": category, "name": "Stock blacklisted " + category}
               for category in ("female_blacklisted", "male_blacklisted")])
    request = {"domain": "human-provider-config", "presetPoolPolicy": "exact-six-existing-human-preset-elements",
               "baseSelectionPolicy": policies, "otherActorsPolicy": "Reviewed complete base policy",
               "requiredDisablePresetDistribution": "none", "allowedAdditionalLoadedPresets": extras}
    parsed = {"disablePresetDistribution": "none", "npcFormID": {plugin: {
        item["baseFormId"][2:]: item["allowedHumanPresets"] for item in policies if item["plugin"] == plugin}
        for plugin in ("Master.esm", "Fixture.esp")}}
    categories = {category: [] for category in subject.COUNT_FIELDS}
    for item in targets:
        categories[item["sex"]].append(item["name"])
    for item in extras:
        categories[item["category"]].append(item["name"])
    return request, targets, parsed, categories


class NativeCatalog:
    def __init__(self, categories):
        self.categories = copy.deepcopy(categories)
        self.calls = []
        self.change = None

    def __call__(self, request):
        self.calls.append(copy.deepcopy(request))
        names = self.categories[request["category"]]
        values = names[request["offset"]:request["offset"] + request["limit"]]
        page = {"schemaVersion": 1, "protocol": "morph-provider/1", "pid": 123,
                "providerEpoch": 3, "worldGeneration": 2, "worldLoading": False,
                "phase": "skse_main_thread_task", "frame": len(self.calls),
                "category": request["category"], "offset": request["offset"], "limit": request["limit"],
                "names": values, "returnedCount": len(values),
                "counts": {field: len(self.categories[category]) for category, field in subject.COUNT_FIELDS.items()}}
        if self.change:
            self.change(page, len(self.calls))
        return page


class HumanProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self.request, self.targets, self.parsed, self.categories = fixture()

    def raw(self, text=None):
        if text is None:
            text = json.dumps(self.parsed, ensure_ascii=False)
        return {"pid": 123, "path": PATH, "rawText": text, "bytes": len(text.encode("utf-8")),
                "inMemoryConfigObserved": False,
                "basis": "actual fixed game-VFS file bytes; startup pins/lifecycle and actual generation establish use separately"}

    def inspect(self, raw=None, request=None, catalog=None, **changes):
        raw = self.raw() if raw is None else raw
        if catalog is None:
            catalog = subject.read_catalog(NativeCatalog(self.categories), 123)
        settings = {"expected_pid": 123, "expected_sha256": hashlib.sha256(raw["rawText"].encode("utf-8")).hexdigest(),
                    "maximum_fixtures": 12, "requested_presets": self.targets, "catalog": catalog,
                    "expected_game_path": GAME, **changes}
        return subject.inspect_config(raw, self.request if request is None else request, **settings)

    def test_twelve_exact_base_identities_and_twenty_nine_stock_extras(self):
        self.assertEqual(len(self.request["baseSelectionPolicy"]), 12)
        self.assertEqual(len(self.request["allowedAdditionalLoadedPresets"]), 29)
        result = self.inspect()
        self.assertEqual(result["baseSelectionCount"], 12)
        self.assertTrue(result["baseSelectionMatch"])
        for name in ("unexpectedLoadedPresetCount", "missingExpectedPresetCount", "missingAllowedAdditionalPresetCount"):
            self.assertEqual(result[name], 0)
        self.assertEqual(result["configObservationScope"], "fixed_main_game_vfs_file_only")
        self.assertIs(result["includeConfigurationObserved"], False)
        self.assertIs(result["inMemoryConfigObserved"], False)
        self.assertEqual(result["actualVfsRead"], self.raw())

    def test_same_local_form_in_different_plugins_remains_independent(self):
        self.parsed["npcFormID"]["Fixture.esp"]["00000800"] = ["F2"]
        with self.assertRaisesRegex(BindingError, "complete base policy"):
            self.inspect()

    def test_no_subset_or_unfrozen_twelve_mapping_acceptance(self):
        request = copy.deepcopy(self.request)
        request["baseSelectionPolicy"] = request["baseSelectionPolicy"][:6]
        with self.assertRaisesRegex(BindingError, "complete base policy"):
            self.inspect(request=request)
        with self.assertRaisesRegex(BindingError, "fixture opt-in"):
            self.inspect(maximum_fixtures=6)

    def test_unknown_loaded_presets_are_counted_in_each_native_category(self):
        for category in subject.COUNT_FIELDS:
            with self.subTest(category=category):
                self.categories[category].append("Undeclared")
                result = self.inspect()
                self.assertEqual(result["unexpectedLoadedPresetCount"], 1)
                self.assertEqual(result["unexpectedLoadedPresets"], [{"category": category, "name": "Undeclared"}])
                self.categories[category].pop()

    def test_each_declared_extra_requires_its_exact_category(self):
        extra = self.request["allowedAdditionalLoadedPresets"][0]
        self.categories[extra["category"]].remove(extra["name"])
        self.categories["male_blacklisted"].append(extra["name"])
        result = self.inspect()
        self.assertEqual(result["missingAllowedAdditionalPresetCount"], 1)
        self.assertEqual(result["unexpectedLoadedPresetCount"], 1)
        self.assertEqual(result["missingAllowedAdditionalPresets"], [extra])

    def test_wrong_sex_and_blacklisted_targets_remain_missing(self):
        self.categories["female"].remove("F1")
        for category in ("male", "female_blacklisted"):
            with self.subTest(category=category):
                self.categories[category].append("F1")
                result = self.inspect()
                self.assertEqual(result["missingExpectedPresetCount"], 1)
                self.assertEqual(result["unexpectedLoadedPresetCount"], 1)
                self.categories[category].pop()

    def test_same_extra_name_in_distinct_categories_requires_both_declarations(self):
        name = self.request["allowedAdditionalLoadedPresets"][0]["name"]
        self.categories["male"].append(name)
        self.assertEqual(self.inspect()["unexpectedLoadedPresetCount"], 1)
        self.request["allowedAdditionalLoadedPresets"].append({"name": name, "category": "male"})
        self.assertEqual(self.inspect()["unexpectedLoadedPresetCount"], 0)

    def test_duplicate_extra_and_duplicate_cross_sex_target_declarations_rejected(self):
        self.request["allowedAdditionalLoadedPresets"].append(copy.deepcopy(self.request["allowedAdditionalLoadedPresets"][0]))
        with self.assertRaisesRegex(BindingError, "Duplicate additional"):
            self.inspect()
        self.request["allowedAdditionalLoadedPresets"].pop()
        self.targets[3] = dict(self.targets[0], sex="male")
        with self.assertRaisesRegex(BindingError, "unique across"):
            self.inspect()

    def test_real_empty_catalog_is_observed_as_missing_not_invented_availability(self):
        self.categories = {category: [] for category in subject.COUNT_FIELDS}
        result = self.inspect()
        self.assertEqual(result["missingExpectedPresetCount"], 6)
        self.assertEqual(result["missingAllowedAdditionalPresetCount"], 29)
        self.assertEqual(result["unexpectedLoadedPresetCount"], 0)

    def test_recognized_distribution_mismatch_is_retained_for_subject_assertion(self):
        self.parsed["disablePresetDistribution"] = "all"
        result = self.inspect()
        self.assertEqual(result["disablePresetDistribution"], "all")
        self.assertIs(result["requiredDisablePresetDistributionMatch"], False)
        del self.parsed["disablePresetDistribution"]
        with self.assertRaisesRegex(BindingError, "missing/unknown"):
            self.inspect()

    def test_actual_preset_pool_rejects_string_duplicate_null_and_empty(self):
        for value in ("F1", ["F1", "F1"], None, [], {}, [True], ["F1\0"]):
            with self.subTest(value=value):
                self.parsed["npcFormID"]["Master.esm"]["00000800"] = value
                with self.assertRaises(BindingError):
                    self.inspect()

    def test_json_duplicate_keys_and_nonfinite_values_rejected(self):
        text = self.raw()["rawText"]
        for bad in (text.replace('"disablePresetDistribution": "none"', '"disablePresetDistribution": "all", "disablePresetDistribution": "none"'),
                    text.replace('"00000800": ["F1"]', '"00000800": ["F2"], "00000800": ["F1"]', 1),
                    text[:-1] + ', "extra": NaN}'):
            with self.subTest(bad=bad[:100]):
                with self.assertRaises(BindingError):
                    self.inspect(raw=self.raw(bad))

    def test_normalized_form_aliases_and_plugin_case_aliases_rejected(self):
        self.parsed["npcFormID"]["Master.esm"]["800"] = ["F1"]
        with self.assertRaisesRegex(BindingError, "duplicate normalized"):
            self.inspect()
        del self.parsed["npcFormID"]["Master.esm"]["800"]
        self.parsed["npcFormID"]["MASTER.esm"] = {"00000800": ["F1"]}
        with self.assertRaisesRegex(BindingError, "duplicate normalized"):
            self.inspect()

    def test_missing_malformed_or_nonlocal_actual_base_identities_rejected(self):
        for value in (None, [], {"Master.esm": []}, {"Master.esm": {}},
                      {"Master.esm": {"01000800": ["F1"]}}, {"Master.esm": {"00000000": ["F1"]}},
                      {"Master.esm": {"0x000800": ["F1"]}}):
            with self.subTest(value=value):
                self.parsed["npcFormID"] = value
                with self.assertRaises(BindingError):
                    self.inspect()

    def test_vfs_pin_uses_actual_utf8_bytes_and_preserves_bom(self):
        raw = self.raw("\ufeff" + self.raw()["rawText"])
        result = self.inspect(raw=raw)
        self.assertEqual(result["sha256"], hashlib.sha256(raw["rawText"].encode("utf-8")).hexdigest())
        raw["rawText"] += " "
        with self.assertRaisesRegex(BindingError, "frozen staged pin"):
            self.inspect(raw=raw)

    def test_vfs_provenance_requires_pid_path_basis_byte_count_and_file_only_claim(self):
        changes = ({"pid": 124}, {"pid": True}, {"bytes": True}, {"bytes": 0}, {"basis": ""},
                   {"inMemoryConfigObserved": True}, {"status": "unavailable"}, {"ok": False},
                   {"error": "read failed"}, {"path": "SKSE/Plugins/OBody_presetDistributionConfig.json"},
                   {"path": "D:/Other/Data/SKSE/Plugins/OBody_presetDistributionConfig.json"},
                   {"path": "D:/Fixture/Data/Other/OBody_presetDistributionConfig.json"},
                   {"path": "D:/Fixture/Data/../Data/SKSE/Plugins/OBody_presetDistributionConfig.json"})
        for change in changes:
            with self.subTest(change=change):
                raw = self.raw()
                raw.update(change)
                with self.assertRaises(BindingError):
                    self.inspect(raw=raw)
        with self.assertRaisesRegex(BindingError, "frozen staged pin"):
            self.inspect(expected_sha256="f" * 64)

    def test_legacy_strict_name_policy_retained(self):
        del self.request["allowedAdditionalLoadedPresets"]
        result = self.inspect(requested_presets=None)
        self.assertEqual(result["unexpectedLoadedPresetCount"], 29)
        self.assertEqual(result["missingExpectedPresetCount"], 0)


class NativeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.categories = fixture()[3]
        self.native = NativeCatalog(self.categories)

    def test_four_independent_categories_paginate_and_retain_raw_evidence(self):
        self.native.categories["female"] = [f"Preset {i}" for i in range(600)]
        result = subject.read_catalog(self.native, 123)
        self.assertEqual(result["categories"], self.native.categories)
        self.assertEqual(len(result["pages"]), 6)
        self.assertEqual([call["offset"] for call in self.native.calls if call["category"] == "female"], [0, 256, 512])
        self.assertEqual({call["category"] for call in self.native.calls}, set(subject.COUNT_FIELDS))
        self.assertTrue(all(call["action"] == "catalog" for call in self.native.calls))

    def test_empty_category_has_its_own_explicit_zero_count_read(self):
        self.native.categories = {category: [] for category in subject.COUNT_FIELDS}
        result = subject.read_catalog(self.native, 123)
        self.assertEqual(len(self.native.calls), 4)
        self.assertEqual(result["categories"], self.native.categories)
        self.assertEqual(result["counts"], {field: 0 for field in subject.COUNT_FIELDS.values()})

    def test_duplicate_names_within_category_rejected_but_across_categories_retained(self):
        self.native.categories["female"].append(self.native.categories["female"][0])
        with self.assertRaisesRegex(BindingError, "unique-name"):
            subject.read_catalog(self.native, 123)
        self.native.categories["female"].pop()
        self.native.categories["male"].append("F1")
        result = subject.read_catalog(self.native, 123)
        self.assertIn("F1", result["categories"]["female"])
        self.assertIn("F1", result["categories"]["male"])

    def test_unavailable_errors_and_wrong_page_identities_never_become_zero(self):
        changes = ({"status": "unavailable"}, {"ok": False}, {"error": "provider not ready"},
                   {"pid": 124}, {"providerEpoch": True}, {"providerEpoch": 0}, {"worldGeneration": 0},
                   {"worldLoading": True}, {"category": "male"}, {"offset": 1}, {"limit": 1},
                   {"frame": -1}, {"protocol": "other"}, {"schemaVersion": True}, {"phase": "unknown"})
        for change in changes:
            with self.subTest(change=change):
                native = NativeCatalog(self.categories)
                native.change = lambda page, index: page.update(change)
                with self.assertRaises(BindingError):
                    subject.read_catalog(native, 123)
                self.assertEqual(len(native.calls), 1)

    def test_missing_unknown_noninteger_and_oversized_counts_rejected(self):
        counts = ({}, {"female": 0}, {**{field: 0 for field in subject.COUNT_FIELDS.values()}, "other": 0},
                  {**{field: 0 for field in subject.COUNT_FIELDS.values()}, "female": True},
                  {**{field: 0 for field in subject.COUNT_FIELDS.values()}, "female": 4097})
        for value in counts:
            with self.subTest(value=value):
                self.native.change = lambda page, index: page.update(counts=value)
                with self.assertRaisesRegex(BindingError, "counts"):
                    subject.read_catalog(self.native, 123)

    def test_changed_epoch_world_counts_or_backwards_frame_is_terminal(self):
        changes = ({"providerEpoch": 4}, {"worldGeneration": 3}, {"frame": 0},
                   {"counts": {"female": 15, "femaleBlacklisted": 1, "male": 19, "maleBlacklisted": 1}})
        for change in changes:
            with self.subTest(change=change):
                native = NativeCatalog(self.categories)
                native.change = lambda page, index: page.update(change) if index == 2 else None
                with self.assertRaisesRegex(BindingError, "changed"):
                    subject.read_catalog(native, 123)
                self.assertEqual(len(native.calls), 2)

    def test_short_truncated_invalid_or_missing_page_is_terminal(self):
        for change in (lambda page: page.update(names=[], returnedCount=0),
                       lambda page: page.update(returnedCount=True),
                       lambda page: page.pop("names"),
                       lambda page: page.update(names=["x\0"] * 15, returnedCount=15)):
            with self.subTest(change=change):
                native = NativeCatalog(self.categories)
                native.change = lambda page, index: change(page)
                with self.assertRaises(BindingError):
                    subject.read_catalog(native, 123)
                self.assertEqual(len(native.calls), 1)


if __name__ == "__main__":
    unittest.main()
