import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import create_server


QUALITIES = [
    {"qualityId": 1, "label": "白", "color": "gray", "weight": 80},
    {"qualityId": 2, "label": "紫", "color": "purple", "weight": 240},
]
SPECS = [
    {"specId": 1, "width": 1, "height": 1},
    {"specId": 2, "width": 1, "height": 2},
]
ITEMS = [
    {"itemId": 101, "name": "旧银币", "qualityId": 1, "value": 3000, "resourceCost": 50, "specId": 1},
    {"itemId": 102, "name": "紫晶花瓶", "qualityId": 2, "value": 30000, "resourceCost": 500, "specId": 2},
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
    {"budgetId": 3, "resourceBudget": 2550},
    {"budgetId": 4, "resourceBudget": 1200},
]
SETTINGS = {
    "boardWidth": 6,
    "targetResourceBudget": None,
    "seed": None,
    "revealSpeedSeconds": 0.25,
}


def jsonl(records):
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.spec_path = root / "item_specs.jsonl"
        cls.item_path = root / "items.jsonl"
        cls.quality_path = root / "qualities.jsonl"
        cls.band_path = root / "value_costs.jsonl"
        cls.budget_path = root / "resource_budgets.jsonl"
        cls.settings_path = root / "generation_settings.json"
        cls.server = create_server(
            ("127.0.0.1", 0),
            cls.spec_path,
            cls.item_path,
            cls.quality_path,
            cls.band_path,
            cls.settings_path,
            cls.budget_path,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.directory.cleanup()

    def setUp(self):
        self.spec_path.write_text(jsonl(SPECS), encoding="utf-8")
        self.item_path.write_text(jsonl(ITEMS), encoding="utf-8")
        self.quality_path.write_text(jsonl(QUALITIES), encoding="utf-8")
        self.band_path.write_text(jsonl(BANDS), encoding="utf-8")
        self.budget_path.write_text(jsonl(BUDGETS), encoding="utf-8")
        self.settings_path.write_text(json.dumps(SETTINGS), encoding="utf-8")

    def request_json(self, path, payload=None, method="GET"):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method=method,
        )
        try:
            response = urlopen(request, timeout=8)
            return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_page_exposes_two_tab_workbench(self):
        with urlopen(self.base_url + "/", timeout=3) as response:
            body = response.read().decode("utf-8")
        settings_tab = '<button class="top-tab is-active" type="button" data-tab="settings" aria-selected="true">基础参数</button>'
        config_tab = '<button class="top-tab" type="button" data-tab="config" aria-selected="false">配置</button>'
        self.assertIn(settings_tab, body)
        self.assertIn(config_tab, body)
        self.assertIn("藏品展仓模拟器", body)
        self.assertIn("COLLECTION SHOWCASE SIMULATOR", body)
        self.assertNotIn("BIDKING / COLLECTION WORKBENCH", body)
        self.assertLess(body.index(settings_tab), body.index(config_tab))
        self.assertIn('<section class="tab-panel" data-tab-panel="settings">', body)
        self.assertIn('<section class="tab-panel" data-tab-panel="config" hidden>', body)
        self.assertIn('data-tab="config"', body)
        self.assertIn('data-tab="settings"', body)
        self.assertIn('data-table="qualities"', body)
        self.assertIn('data-table="value-costs"', body)
        self.assertIn('data-table="resource-budgets"', body)
        self.assertNotIn('id="budget-options-note"', body)
        self.assertIn('id="save-settings"', body)
        self.assertIn('id="reveal-button"', body)
        self.assertIn('disabled>展示</button>', body)
        self.assertNotIn('id="replay-button"', body)
        self.assertIn('id="metric-average-cell-value"', body)
        self.assertIn('id="metric-average-item-value"', body)
        self.assertIn('id="metric-median-item-value"', body)
        self.assertIn('id="preview-quality-tags"', body)
        self.assertIn('id="preview-spec-tags"', body)
        self.assertIn("多选规则可叠加", body)
        self.assertIn("品质显示对应颜色填充与藏品黑色轮廓，规格只显示同款黑色轮廓", body)
        self.assertIn('id="config-table"', body)
        with urlopen(self.base_url + "/static/app.js", timeout=3) as response:
            script = response.read().decode("utf-8")
        self.assertIn("window.confirm", script)
        self.assertNotIn("updateBudgetOptionsNote", script)
        self.assertNotIn("中等概率随机抽取", script)
        self.assertIn("/api/config/${activeTable}", script)
        self.assertIn('requestJson("/api/settings"', script)
        self.assertIn("async function waitRevealPhase", script)
        self.assertIn("onDurationChange = null", script)
        self.assertIn("const phaseDuration = Number(revealSpeed.value)", script)
        self.assertNotIn("const duration = window.matchMedia", script)
        generate_section = script.split("async function generate", 1)[1].split("async function initialize", 1)[0]
        self.assertNotIn("playReveal", generate_section)
        self.assertIn('setState("ready", "等待展示")', generate_section)
        self.assertIn('setRevealButton("展示中…", true)', script)
        self.assertIn('setRevealButton("重播", false)', script)
        self.assertIn("selectedPreviewQualities", script)
        self.assertIn("selectedPreviewSpecs", script)
        self.assertIn('overlay.classList.add("is-preview-quality"', script)
        self.assertIn('overlay.classList.add("is-preview-spec")', script)
        self.assertIn('displayState !== "preview" && displayState !== "playing"', script)
        reveal_section = script.split("async function playReveal", 1)[1].split("async function generate", 1)[0]
        self.assertIn("applyPreviewTags();", reveal_section)
        self.assertIn("clearOverlayPreviewTags(overlay)", reveal_section)
        self.assertIn('overlay.classList.contains("is-preview-quality")', reveal_section)
        self.assertIn('overlay.classList.add("is-quality-transition")', reveal_section)
        self.assertIn('overlay.classList.remove("is-loading", "is-quality-transition")', reveal_section)
        self.assertLess(reveal_section.index("clearOverlayPreviewTags(overlay)"), reveal_section.index('overlay.classList.remove("is-loading", "is-quality-transition")'))
        self.assertIn("overlay.dataset.detailTitle", script)
        self.assertNotIn("buildGeneratorItemSpecs", script)
        with urlopen(self.base_url + "/static/styles.css", timeout=3) as response:
            styles = response.read().decode("utf-8")
        self.assertIn("--item-outline:rgba(7,10,16,.92)", styles)
        self.assertIn("border:2px solid transparent", styles)
        self.assertNotIn("border-color .18s", styles)
        self.assertIn(".item-overlay.is-revealed,.item-overlay.is-preview-spec,.item-overlay.is-preview-quality { border:2px solid var(--item-outline); box-shadow:none; }", styles)
        self.assertIn(".item-overlay.is-preview-quality { background:var(--preview-quality); }", styles)
        self.assertIn(".item-overlay.is-preview-quality.is-preview-spec { background:var(--preview-quality); border:2px solid var(--item-outline); box-shadow:none; }", styles)
        self.assertIn(".item-overlay.is-loading { border:2px solid var(--item-outline); box-shadow:none; }", styles)
        self.assertIn("@keyframes reveal-quality { from { background-color:var(--occupied-cell); } to { background-color:var(--reveal-quality); } }", styles)

    def test_each_table_has_an_independent_read_endpoint(self):
        expected = {"qualities": QUALITIES, "specs": SPECS, "items": ITEMS, "value-costs": BANDS, "resource-budgets": BUDGETS}
        for table, records in expected.items():
            with self.subTest(table=table):
                status, body = self.request_json("/api/config/" + table)
                self.assertEqual(status, 200)
                self.assertEqual(body["records"], records)
                self.assertEqual(body["count"], len(records))

    def test_single_table_save_does_not_rewrite_other_files(self):
        original_items = self.item_path.read_bytes()
        changed = [dict(QUALITIES[0], weight=99), QUALITIES[1]]
        status, body = self.request_json(
            "/api/config/qualities", {"records": changed}, method="PUT"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["records"], changed)
        self.assertEqual(self.item_path.read_bytes(), original_items)

    def test_deleting_referenced_quality_or_spec_is_blocked(self):
        status, body = self.request_json(
            "/api/config/qualities", {"records": [QUALITIES[0]]}, method="PUT"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "unknown_quality_id")
        status, body = self.request_json(
            "/api/config/specs", {"records": [SPECS[0]]}, method="PUT"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "unknown_spec_id")

    def test_settings_are_loaded_and_saved_separately(self):
        status, body = self.request_json("/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(body["settings"], SETTINGS)
        changed = dict(SETTINGS, boardWidth=12, targetResourceBudget=1350, seed=7, revealSpeedSeconds=0.4)
        status, body = self.request_json("/api/settings", changed, method="PUT")
        self.assertEqual(status, 200)
        self.assertEqual(body["settings"], changed)
        self.assertEqual(json.loads(self.settings_path.read_text(encoding="utf-8")), changed)

    def test_invalid_settings_return_400(self):
        status, body = self.request_json(
            "/api/settings", dict(SETTINGS, revealSpeedSeconds=0.9), method="PUT"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_reveal_speed")

    def test_generate_uses_saved_tables_and_parameters_only(self):
        payload = {"boardWidth": 6, "seed": 42, "targetResourceBudget": 1350}
        status, body = self.request_json("/api/generate", payload, method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body["resourceBudget"], 1350)
        self.assertEqual(body["resourceBudgetMode"], "configured")
        self.assertTrue({item["itemId"] for item in body["items"]}.issubset({101, 102}))
        self.assertTrue(all(item["name"] in {"旧银币", "紫晶花瓶"} for item in body["items"]))

    def test_blank_target_uses_saved_resource_budget_list(self):
        configured = [{"budgetId": 9, "resourceBudget": 1350}]
        status, body = self.request_json(
            "/api/config/resource-budgets", {"records": configured}, method="PUT"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["records"], configured)
        status, body = self.request_json(
            "/api/generate", {"boardWidth": 6, "seed": 42}, method="POST"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["resourceBudget"], 1350)
        self.assertEqual(body["resourceBudgetOptions"], [1350])
        self.assertEqual(body["resourceBudgetMode"], "rolled")

    def test_client_item_specs_are_rejected(self):
        status, body = self.request_json(
            "/api/generate", {"boardWidth": 6, "itemSpecs": []}, method="POST"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "unsupported_field")

    def test_same_seed_is_reproducible_except_time(self):
        payload = {"boardWidth": 6, "seed": 77, "targetResourceBudget": 1200}
        _, first = self.request_json("/api/generate", payload, method="POST")
        _, second = self.request_json("/api/generate", payload, method="POST")
        first.pop("generatedMs")
        second.pop("generatedMs")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
