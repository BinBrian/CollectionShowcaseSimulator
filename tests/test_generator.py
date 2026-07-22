import unittest
from statistics import median

from generator import GenerationError, QUALITY_COLORS, RESOURCE_BUDGETS, ValidationError, generate_collection


def qualities(*weights):
    labels = ("白", "绿", "蓝", "紫", "金", "红")
    return [
        {"qualityId": index + 1, "label": labels[index], "color": QUALITY_COLORS[index], "weight": weight}
        for index, weight in enumerate(weights or (80, 200, 240, 240, 120, 70))
    ]


def item(item_id, quality_id=1, value=3000, resource_cost=50):
    return {"itemId": item_id, "name": "道具 %s" % item_id, "qualityId": quality_id, "value": value, "resourceCost": resource_cost}


def spec(spec_id, width, height, items):
    return {"specId": spec_id, "width": width, "height": height, "items": items}


class GeneratorTests(unittest.TestCase):
    def assert_layout_valid(self, result):
        seen = set()
        self.assertEqual(result["resourceConsumed"] + result["resourceRemaining"], result["resourceBudget"])
        self.assertEqual(result["resourceConsumed"], sum(entry["resourceCost"] for entry in result["items"]))
        self.assertEqual(result["totalValue"], sum(entry["value"] for entry in result["items"]))
        item_values = [entry["value"] for entry in result["items"]]
        self.assertEqual(result["averageValuePerOccupiedCell"], round(result["totalValue"] / result["occupiedCount"], 2))
        self.assertEqual(result["averageItemValue"], round(result["totalValue"] / result["itemCount"], 2))
        self.assertEqual(result["medianItemValue"], median(item_values))
        self.assertEqual(result["itemCount"], len(result["items"]))
        self.assertEqual(result["qualityRollCount"], result["itemCount"])
        spatial = []
        for order, entry in enumerate(result["items"], start=1):
            self.assertEqual(entry["uid"], "C%03d" % order)
            self.assertEqual(entry["placementOrder"], order)
            self.assertIn(entry["quality"], QUALITY_COLORS)
            self.assertLessEqual(entry["x"] + entry["width"], result["boardWidth"])
            self.assertLessEqual(entry["y"] + entry["height"], result["boardHeight"])
            spatial.append((entry["y"], entry["x"]))
            for y in range(entry["y"], entry["y"] + entry["height"]):
                for x in range(entry["x"], entry["x"] + entry["width"]):
                    self.assertNotIn((x, y), seen)
                    seen.add((x, y))
        self.assertEqual(spatial, sorted(spatial))
        snapshot = {(x, y) for y, row in enumerate(result["occupied"]) for x, used in enumerate(row) if used}
        self.assertEqual(snapshot, seen)
        self.assertEqual(result["occupiedCount"], len(seen))

    def test_same_seed_is_fully_deterministic(self):
        specs = [spec(1, 1, 1, [item(11), item(12, 2, 5000, 200)])]
        self.assertEqual(generate_collection(5, specs, qualities(), 12345), generate_collection(5, specs, qualities(), 12345))

    def test_budget_is_rolled_from_four_tiers_and_spent_until_unaffordable(self):
        result = generate_collection(4, [spec(1, 1, 1, [item(1, resource_cost=500)])], qualities(), 8)
        self.assertIn(result["resourceBudget"], RESOURCE_BUDGETS)
        self.assertLess(result["resourceRemaining"], 500)
        self.assert_layout_valid(result)

    def test_quality_weight_controls_first_layer_roll(self):
        configured = qualities(10000, 1, 1, 1, 1, 1)
        pool = [spec(index + 1, 1, 1, [item(index + 1, index + 1, 3000, 1200)]) for index in range(6)]
        white = 0
        total = 0
        for seed in range(150):
            result = generate_collection(3, pool, configured, seed)
            white += result["items"][0]["qualityId"] == 1
            total += 1
        self.assertGreater(white / total, 0.97)

    def test_concrete_item_is_rolled_after_quality(self):
        pool = [spec(1, 1, 1, [item(11, resource_cost=1200), item(12, resource_cost=1200)])]
        observed = {generate_collection(2, pool, qualities(), seed)["items"][0]["itemId"] for seed in range(30)}
        self.assertEqual(observed, {11, 12})

    def test_selected_items_can_repeat(self):
        result = generate_collection(3, [spec(1, 1, 1, [item(71, resource_cost=50)])], qualities(), 2)
        self.assertEqual({entry["itemId"] for entry in result["items"]}, {71})
        self.assertEqual(result["items"][0]["name"], "道具 71")

    def test_large_real_world_item_pool_is_supported(self):
        pool = [item(index, resource_cost=50) for index in range(1, 345)]
        result = generate_collection(10, [spec(1, 1, 1, pool)], qualities(), 9, 50)
        self.assertEqual(result["itemCount"], 1)
        self.assertIn(result["items"][0]["itemId"], range(1, 345))

    def test_configured_target_resource_budget_overrides_tier_roll(self):
        result = generate_collection(
            3, [spec(1, 1, 1, [item(1, resource_cost=50)])], qualities(), 99, 1350
        )
        self.assertEqual(result["resourceBudget"], 1350)
        self.assertEqual(result["resourceBudgetMode"], "configured")
        self.assertEqual(result["resourceRemaining"], 0)

    def test_saved_resource_budget_options_replace_builtin_tiers(self):
        configured = [{"budgetId": 7, "resourceBudget": 1350}]
        result = generate_collection(
            3, [spec(1, 1, 1, [item(1, resource_cost=50)])], qualities(), 99, None, configured
        )
        self.assertEqual(result["resourceBudget"], 1350)
        self.assertEqual(result["resourceBudgetOptions"], [1350])
        with self.assertRaises(ValidationError):
            generate_collection(3, [spec(1, 1, 1, [item(1)])], qualities(), 1, None, [])

    def test_skyline_rotates_wide_item_and_grows_height(self):
        result = generate_collection(2, [spec(1, 3, 1, [item(1, 4, 10000, 1200)])], qualities(), 5)
        self.assertTrue(all(entry["rotation"] == 90 for entry in result["items"]))
        self.assertTrue(all((entry["width"], entry["height"]) == (1, 3) for entry in result["items"]))
        self.assert_layout_valid(result)

    def test_non_square_orientation_is_seeded_random(self):
        pool = [spec(1, 1, 2, [item(1, resource_cost=1200)])]
        observed = set()
        for seed in range(30):
            result = generate_collection(4, pool, qualities(), seed, 1200)
            observed.add(result["items"][0]["rotation"])
            self.assert_layout_valid(result)
        self.assertEqual(observed, {0, 90})
        self.assertEqual(
            generate_collection(4, pool, qualities(), 17, 1200),
            generate_collection(4, pool, qualities(), 17, 1200),
        )

    def test_square_spec_never_rotates(self):
        result = generate_collection(
            4, [spec(1, 2, 2, [item(1, resource_cost=50)])], qualities(), 21, 200
        )
        self.assertTrue(all(entry["rotation"] == 0 for entry in result["items"]))
        self.assert_layout_valid(result)

    def test_all_items_too_expensive_returns_no_partial_layout(self):
        with self.assertRaises(GenerationError) as context:
            generate_collection(2, [spec(1, 1, 1, [item(1, resource_cost=7000)])], qualities(), 1)
        self.assertEqual(context.exception.code, "budget_too_low")

    def test_rejects_unknown_quality_duplicate_ids_and_zero_cost(self):
        with self.assertRaises(ValidationError) as context:
            generate_collection(2, [spec(1, 1, 1, [item(1, quality_id=99)])], qualities(), 1)
        self.assertEqual(context.exception.code, "unknown_quality_id")
        with self.assertRaises(ValidationError):
            generate_collection(2, [spec(1, 1, 1, [item(1), item(1)])], qualities(), 1)
        with self.assertRaises(ValidationError):
            generate_collection(2, [spec(1, 1, 1, [item(1, resource_cost=0)])], qualities(), 1)


if __name__ == "__main__":
    unittest.main()
