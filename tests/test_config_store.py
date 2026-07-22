import json
from pathlib import Path
import tempfile
import unittest

from config_store import (
    ConfigStoreError,
    DEFAULT_GENERATION_SETTINGS,
    build_generator_specs,
    canonicalize_resource_budgets,
    canonicalize_value_costs,
    load_configuration,
    load_generation_settings,
    load_reference_configuration,
    load_resource_budget_configuration,
    resource_cost_for_value,
    save_all_configuration,
    save_configuration,
    save_generation_settings,
)
from generator import ValidationError


QUALITIES = [
    {"qualityId": 1, "label": "白", "color": "gray", "weight": 80},
    {"qualityId": 2, "label": "绿", "color": "green", "weight": 200},
]
BANDS = [
    {"minValue": 2000, "maxValueExclusive": 4000, "resourceCost": 50},
    {"minValue": 4000, "maxValueExclusive": 10000, "resourceCost": 200},
    {"minValue": 10000, "maxValueExclusive": 999999, "resourceCost": 500},
    {"minValue": 999999, "maxValueExclusive": None, "resourceCost": 900},
]
BUDGETS = [
    {"budgetId": 1, "resourceBudget": 6000},
    {"budgetId": 2, "resourceBudget": 3800},
]


def sample_configuration():
    specs = [{"specId": 20, "width": 1, "height": 2}, {"specId": 10, "width": 1, "height": 1}]
    items = [
        {"itemId": 101, "name": "紫晶花瓶", "qualityId": 2, "value": 58000, "resourceCost": 500, "specId": 20},
        {"itemId": 102, "name": "旧银币", "qualityId": 1, "value": 3000, "resourceCost": 50, "specId": 10},
    ]
    return specs, items


class ConfigStoreTests(unittest.TestCase):
    def test_missing_settings_use_defaults_and_can_be_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generation_settings.json"
            self.assertEqual(load_generation_settings(path), DEFAULT_GENERATION_SETTINGS)
            changed = dict(DEFAULT_GENERATION_SETTINGS, boardWidth=12, seed=99)
            self.assertEqual(save_generation_settings(changed, path), changed)
            self.assertEqual(load_generation_settings(path), changed)

    def test_round_trip_uses_separate_utf8_jsonl_files(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path, item_path = Path(directory) / "item_specs.jsonl", Path(directory) / "items.jsonl"
            specs, items = sample_configuration()
            saved = save_configuration(specs, items, spec_path, item_path, {1, 2})
            self.assertEqual(load_configuration(spec_path, item_path, {1, 2}), saved)
            self.assertEqual(len(spec_path.read_text(encoding="utf-8").splitlines()), 2)
            self.assertEqual(json.loads(item_path.read_text(encoding="utf-8").splitlines()[0])["resourceCost"], 500)
            self.assertEqual(json.loads(item_path.read_text(encoding="utf-8").splitlines()[0])["name"], "紫晶花瓶")

    def test_reference_files_load_and_value_boundaries_are_half_open(self):
        with tempfile.TemporaryDirectory() as directory:
            quality_path, band_path = Path(directory) / "qualities.jsonl", Path(directory) / "value_costs.jsonl"
            quality_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in QUALITIES), encoding="utf-8")
            band_path.write_text("\n".join(json.dumps(row) for row in BANDS), encoding="utf-8")
            loaded_qualities, loaded_bands = load_reference_configuration(quality_path, band_path)
            self.assertEqual(loaded_qualities, QUALITIES)
            self.assertEqual(resource_cost_for_value(3999, loaded_bands), 50)
            self.assertEqual(resource_cost_for_value(4000, loaded_bands), 200)
            self.assertEqual(resource_cost_for_value(999999, loaded_bands), 900)

    def test_resource_budget_list_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resource_budgets.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in BUDGETS) + "\n", encoding="utf-8")
            self.assertEqual(load_resource_budget_configuration(path), BUDGETS)
        with self.assertRaises(ValidationError):
            canonicalize_resource_budgets([BUDGETS[0], dict(BUDGETS[1], budgetId=1)])
        with self.assertRaises(ValidationError):
            canonicalize_resource_budgets([BUDGETS[0], dict(BUDGETS[1], resourceBudget=6000)])

    def test_all_four_jsonl_files_can_be_saved_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (
                root / "item_specs.jsonl",
                root / "items.jsonl",
                root / "qualities.jsonl",
                root / "value_costs.jsonl",
            )
            specs, items = sample_configuration()
            saved = save_all_configuration(specs, items, QUALITIES, BANDS, *paths)
            self.assertEqual(saved, (specs, items, QUALITIES, BANDS))
            self.assertTrue(all(path.is_file() for path in paths))
            self.assertEqual(load_reference_configuration(paths[2], paths[3]), (QUALITIES, BANDS))

    def test_generator_specs_group_items_without_spec_id(self):
        specs, items = sample_configuration()
        grouped = build_generator_specs(specs, items)
        self.assertEqual([entry["specId"] for entry in grouped], [20, 10])
        self.assertNotIn("specId", grouped[0]["items"][0])
        self.assertEqual(grouped[0]["items"][0]["qualityId"], 2)

    def test_ids_are_unique_and_quality_reference_must_exist(self):
        specs, items = sample_configuration()
        with self.assertRaises(ValidationError):
            save_configuration([specs[0], dict(specs[1], specId=20)], items)
        with self.assertRaises(ValidationError):
            save_configuration(specs, [items[0], dict(items[1], itemId=101)])
        with self.assertRaises(ValidationError) as context:
            save_configuration(specs, [dict(items[0], qualityId=9), items[1]], quality_ids={1, 2})
        self.assertEqual(context.exception.code, "unknown_quality_id")

    def test_value_bands_must_be_contiguous_and_open_ended(self):
        with self.assertRaises(ValidationError):
            canonicalize_value_costs([BANDS[0], dict(BANDS[1], minValue=5000), *BANDS[2:]])
        with self.assertRaises(ValidationError):
            canonicalize_value_costs(BANDS[:-1])

    def test_missing_or_invalid_jsonl_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path, item_path = Path(directory) / "specs.jsonl", Path(directory) / "items.jsonl"
            self.assertIsNone(load_configuration(spec_path, item_path))
            spec_path.write_text('{"specId":1,"width":1,"height":1}\n', encoding="utf-8")
            with self.assertRaises(ConfigStoreError):
                load_configuration(spec_path, item_path)


if __name__ == "__main__":
    unittest.main()
