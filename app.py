"""Dependency-free local server for Collection Showcase Simulator."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import time
import traceback
from typing import Any, Dict, Tuple

from config_store import (
    ConfigStoreError,
    ITEM_CONFIG_PATH,
    QUALITY_CONFIG_PATH,
    RESOURCE_BUDGET_CONFIG_PATH,
    SETTINGS_CONFIG_PATH,
    SPEC_CONFIG_PATH,
    VALUE_COST_CONFIG_PATH,
    build_generator_specs,
    load_configuration,
    load_generation_settings,
    load_reference_configuration,
    load_resource_budget_configuration,
    save_all_configuration,
    save_configuration_table,
    save_generation_settings,
)
from generator import GenerationError, ValidationError, generate_collection


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
MAX_REQUEST_BYTES = 512 * 1024


class CollectionShowcaseHandler(BaseHTTPRequestHandler):
    server_version = "CollectionShowcaseSimulator/1.0"

    def log_message(self, format_string: str, *args: Any) -> None:
        print("%s - %s" % (self.address_string(), format_string % args))

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404, "Not found")
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", "%s; charset=utf-8" % content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_payload(self) -> Any:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(
                400,
                {"error": {"code": "invalid_content_length", "message": "请求长度无效"}},
            )
            return None
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(
                400,
                {
                    "error": {
                        "code": "invalid_request_size",
                        "message": "请求正文不能为空且不得超过 512KB",
                    }
                },
            )
            return None
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(
                400,
                {"error": {"code": "invalid_json", "message": "请求正文不是有效 JSON"}},
            )
            return None
        if not isinstance(payload, dict):
            self._send_json(
                400,
                {"error": {"code": "invalid_payload", "message": "请求正文必须是对象"}},
            )
            return None
        return payload

    def _config_paths(self) -> Tuple[Path, Path, Path, Path, Path]:
        return (
            Path(getattr(self.server, "spec_config_path", SPEC_CONFIG_PATH)),
            Path(getattr(self.server, "item_config_path", ITEM_CONFIG_PATH)),
            Path(getattr(self.server, "quality_config_path", QUALITY_CONFIG_PATH)),
            Path(getattr(self.server, "value_cost_config_path", VALUE_COST_CONFIG_PATH)),
            Path(getattr(self.server, "resource_budget_config_path", RESOURCE_BUDGET_CONFIG_PATH)),
        )

    def _settings_path(self) -> Path:
        return Path(getattr(self.server, "settings_config_path", SETTINGS_CONFIG_PATH))

    @staticmethod
    def _config_table(route: str):
        prefix = "/api/config/"
        if not route.startswith(prefix):
            return None
        table = route[len(prefix) :]
        return table if table in ("qualities", "specs", "items", "value-costs", "resource-budgets") else None

    def _load_all_configuration(self):
        spec_path, item_path, quality_path, value_cost_path, resource_budget_path = self._config_paths()
        qualities, value_costs = load_reference_configuration(quality_path, value_cost_path)
        resource_budgets = load_resource_budget_configuration(resource_budget_path)
        quality_ids = {quality["qualityId"] for quality in qualities}
        configuration = load_configuration(spec_path, item_path, quality_ids)
        return configuration, qualities, value_costs, resource_budgets

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        files = {
            "/": STATIC_DIR / "index.html",
            "/static/styles.css": STATIC_DIR / "styles.css",
            "/static/app.js": STATIC_DIR / "app.js",
        }
        if route == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if route == "/api/settings":
            try:
                settings = load_generation_settings(self._settings_path())
            except ConfigStoreError as error:
                self._send_json(500, {"error": {"code": "settings_read_error", "message": str(error)}})
                return
            self._send_json(200, {"settings": settings, "file": "data/generation_settings.json"})
            return
        table = self._config_table(route)
        if table is not None:
            try:
                configuration, qualities, value_costs, resource_budgets = self._load_all_configuration()
            except ConfigStoreError as error:
                self._send_json(500, {"error": {"code": "config_read_error", "message": str(error)}})
                return
            specs, items = configuration if configuration else ([], [])
            records = {
                "qualities": qualities,
                "specs": specs,
                "items": items,
                "value-costs": value_costs,
                "resource-budgets": resource_budgets,
            }[table]
            self._send_json(200, {"table": table, "records": records, "count": len(records)})
            return
        if route == "/api/config":
            try:
                configuration, qualities, value_costs, resource_budgets = self._load_all_configuration()
            except ConfigStoreError as error:
                self._send_json(
                    500,
                    {"error": {"code": "config_read_error", "message": str(error)}},
                )
                return
            self._send_json(
                200,
                {
                    "exists": configuration is not None,
                    "specs": configuration[0] if configuration else [],
                    "items": configuration[1] if configuration else [],
                    "qualities": qualities,
                    "valueCosts": value_costs,
                    "resourceBudgets": resource_budgets,
                    "files": {
                        "specs": "data/item_specs.jsonl",
                        "items": "data/items.jsonl",
                        "qualities": "data/qualities.jsonl",
                        "valueCosts": "data/value_costs.jsonl",
                        "resourceBudgets": "data/resource_budgets.jsonl",
                    },
                },
            )
            return
        path = files.get(route)
        if path is None:
            self.send_error(404, "Not found")
            return
        self._send_file(path)

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route != "/api/generate":
            self.send_error(404, "Not found")
            return

        payload = self._read_json_payload()
        if payload is None:
            return

        unsupported_fields = sorted(
            set(payload)
            - {
                "boardWidth",
                "seed",
                "targetResourceBudget",
            }
        )
        if unsupported_fields:
            self._send_json(
                400,
                {
                    "error": {
                        "code": "unsupported_field",
                        "message": "不支持的请求字段：%s" % ", ".join(unsupported_fields),
                    }
                },
            )
            return

        started = time.perf_counter()
        try:
            configuration, qualities, _, resource_budgets = self._load_all_configuration()
            if configuration is None:
                raise GenerationError("config_missing", "规格和道具配表尚未配置")
            item_specs = build_generator_specs(configuration[0], configuration[1])
            result = generate_collection(
                payload.get("boardWidth"),
                item_specs,
                qualities,
                payload.get("seed"),
                payload.get("targetResourceBudget"),
                resource_budgets,
            )
        except ConfigStoreError as error:
            self._send_json(
                500, {"error": {"code": "config_read_error", "message": str(error)}}
            )
            return
        except ValidationError as error:
            self._send_json(
                400, {"error": {"code": error.code, "message": error.message}}
            )
            return
        except GenerationError as error:
            self._send_json(
                422,
                {
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "suggestions": [
                            "检查规格宽度是否适合容纳盒",
                            "降低道具资源点，或补充可由最低预算承担的道具",
                        ],
                    }
                },
            )
            return
        except Exception:
            traceback.print_exc()
            self._send_json(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "生成器发生未预期错误，请检查服务日志",
                    }
                },
            )
            return

        result["generatedMs"] = round((time.perf_counter() - started) * 1000, 2)
        self._send_json(200, result)

    def do_PUT(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/api/settings":
            payload = self._read_json_payload()
            if payload is None:
                return
            try:
                settings = save_generation_settings(payload, self._settings_path())
            except ValidationError as error:
                self._send_json(400, {"error": {"code": error.code, "message": error.message}})
                return
            except ConfigStoreError as error:
                self._send_json(500, {"error": {"code": "settings_write_error", "message": str(error)}})
                return
            self._send_json(200, {"saved": True, "settings": settings, "file": "data/generation_settings.json"})
            return

        table = self._config_table(route)
        if table is not None:
            payload = self._read_json_payload()
            if payload is None:
                return
            unsupported_fields = sorted(set(payload) - {"records"})
            if unsupported_fields:
                self._send_json(400, {"error": {"code": "unsupported_field", "message": "不支持的请求字段：%s" % ", ".join(unsupported_fields)}})
                return
            try:
                records = save_configuration_table(
                    table,
                    payload.get("records"),
                    *self._config_paths(),
                )
            except ValidationError as error:
                self._send_json(400, {"error": {"code": error.code, "message": error.message}})
                return
            except ConfigStoreError as error:
                self._send_json(500, {"error": {"code": "config_write_error", "message": str(error)}})
                return
            self._send_json(200, {"saved": True, "table": table, "records": records, "count": len(records)})
            return

        if route != "/api/config":
            self.send_error(404, "Not found")
            return
        payload = self._read_json_payload()
        if payload is None:
            return
        unsupported_fields = sorted(
            set(payload) - {"specs", "items", "qualities", "valueCosts"}
        )
        if unsupported_fields:
            self._send_json(
                400,
                {
                    "error": {
                        "code": "unsupported_field",
                        "message": "不支持的请求字段：%s" % ", ".join(unsupported_fields),
                    }
                },
            )
            return
        try:
            spec_path, item_path, quality_path, value_cost_path, _ = self._config_paths()
            specs, items, qualities, value_costs = save_all_configuration(
                payload.get("specs"),
                payload.get("items"),
                payload.get("qualities"),
                payload.get("valueCosts"),
                spec_path,
                item_path,
                quality_path,
                value_cost_path,
            )
        except ValidationError as error:
            self._send_json(
                400, {"error": {"code": error.code, "message": error.message}}
            )
            return
        except ConfigStoreError as error:
            self._send_json(
                500,
                {"error": {"code": "config_write_error", "message": str(error)}},
            )
            return
        self._send_json(
            200,
            {
                "saved": True,
                "specs": specs,
                "items": items,
                "qualities": qualities,
                "valueCosts": value_costs,
                "specCount": len(specs),
                "itemCount": len(items),
                "qualityCount": len(qualities),
                "valueCostCount": len(value_costs),
                "files": {
                    "specs": "data/item_specs.jsonl",
                    "items": "data/items.jsonl",
                    "qualities": "data/qualities.jsonl",
                    "valueCosts": "data/value_costs.jsonl",
                },
            },
        )


def create_server(
    address: Tuple[str, int],
    spec_config_path: Path = SPEC_CONFIG_PATH,
    item_config_path: Path = ITEM_CONFIG_PATH,
    quality_config_path: Path = QUALITY_CONFIG_PATH,
    value_cost_config_path: Path = VALUE_COST_CONFIG_PATH,
    settings_config_path: Path = SETTINGS_CONFIG_PATH,
    resource_budget_config_path: Path = RESOURCE_BUDGET_CONFIG_PATH,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(address, CollectionShowcaseHandler)
    server.spec_config_path = Path(spec_config_path)  # type: ignore[attr-defined]
    server.item_config_path = Path(item_config_path)  # type: ignore[attr-defined]
    server.quality_config_path = Path(quality_config_path)  # type: ignore[attr-defined]
    server.value_cost_config_path = Path(value_cost_config_path)  # type: ignore[attr-defined]
    server.settings_config_path = Path(settings_config_path)  # type: ignore[attr-defined]
    server.resource_budget_config_path = Path(resource_budget_config_path)  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="藏品展仓模拟器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = create_server((args.host, args.port))
    print("藏品展仓模拟器 / Collection Showcase Simulator: http://%s:%d" % server.server_address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
