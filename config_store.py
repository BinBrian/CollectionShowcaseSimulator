"""Atomic JSON Lines persistence for Collection Showcase Simulator."""

import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from generator import (
    JS_SAFE_INTEGER,
    MAX_BOARD_WIDTH,
    MAX_POOL_ITEMS,
    MAX_QUALITY_TYPES,
    MAX_RESOURCE_BUDGET_OPTIONS,
    MAX_SPEC_TYPES,
    MAX_WEIGHT,
    QUALITY_COLORS,
    ValidationError,
)


ROOT = Path(__file__).resolve().parent
SPEC_CONFIG_PATH = ROOT / "data" / "item_specs.jsonl"
ITEM_CONFIG_PATH = ROOT / "data" / "items.jsonl"
QUALITY_CONFIG_PATH = ROOT / "data" / "qualities.jsonl"
VALUE_COST_CONFIG_PATH = ROOT / "data" / "value_costs.jsonl"
RESOURCE_BUDGET_CONFIG_PATH = ROOT / "data" / "resource_budgets.jsonl"
SETTINGS_CONFIG_PATH = ROOT / "data" / "generation_settings.json"
DEFAULT_GENERATION_SETTINGS = {
    "boardWidth": 10,
    "targetResourceBudget": None,
    "seed": None,
    "revealSpeedSeconds": 0.25,
}
CONFIG_TABLES = ("qualities", "specs", "items", "value-costs", "resource-budgets")
_STORE_LOCK = threading.Lock()


class ConfigStoreError(RuntimeError):
    """A persisted JSONL file cannot be read, written, or interpreted."""


def _reject_extra_fields(value: Dict[str, Any], allowed: Sequence[str], label: str) -> None:
    unsupported = sorted(set(value) - set(allowed))
    if unsupported:
        raise ValidationError(
            "unsupported_field", "%s包含不支持的字段：%s" % (label, ", ".join(unsupported))
        )


def _require_string(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("invalid_string", "%s必须是非空字符串" % label)
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValidationError("string_too_long", "%s最多允许 %d 个字符" % (label, maximum))
    return normalized


def _require_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("invalid_integer", "%s必须是整数" % label)
    if value < minimum or value > maximum:
        raise ValidationError(
            "integer_out_of_range", "%s必须在 %d 到 %d 之间" % (label, minimum, maximum)
        )
    return value


def canonicalize_quality_configs(raw_qualities: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_qualities, list) or not raw_qualities:
        raise ValidationError("invalid_quality_configs", "至少需要一条品质配置")
    if len(raw_qualities) > MAX_QUALITY_TYPES:
        raise ValidationError("too_many_quality_types", "品质最多允许 %d 种" % MAX_QUALITY_TYPES)
    qualities: List[Dict[str, Any]] = []
    seen_ids: Set[int] = set()
    seen_colors: Set[str] = set()
    for index, raw in enumerate(raw_qualities, start=1):
        label = "第 %d 条品质" % index
        if not isinstance(raw, dict):
            raise ValidationError("invalid_quality_config", "%s必须是对象" % label)
        _reject_extra_fields(raw, ("qualityId", "label", "color", "weight"), label)
        quality_id = _require_int(raw.get("qualityId"), "%s ID" % label, 1, JS_SAFE_INTEGER)
        if quality_id in seen_ids:
            raise ValidationError("duplicate_quality_id", "品质 ID 不能重复：%s" % quality_id)
        seen_ids.add(quality_id)
        color = _require_string(raw.get("color"), "%s颜色" % label, 16)
        if color not in QUALITY_COLORS:
            raise ValidationError(
                "invalid_quality_color", "%s颜色必须是 %s 之一" % (label, " / ".join(QUALITY_COLORS))
            )
        if color in seen_colors:
            raise ValidationError("duplicate_quality_color", "品质颜色不能重复：%s" % color)
        seen_colors.add(color)
        qualities.append(
            {
                "qualityId": quality_id,
                "label": _require_string(raw.get("label"), "%s标签" % label, 16),
                "color": color,
                "weight": _require_int(raw.get("weight"), "%s权重" % label, 1, MAX_WEIGHT),
            }
        )
    return qualities


def canonicalize_value_costs(raw_bands: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_bands, list) or not raw_bands:
        raise ValidationError("invalid_value_costs", "至少需要一条价值资源消耗配置")
    bands: List[Dict[str, Any]] = []
    expected_min = None
    for index, raw in enumerate(raw_bands, start=1):
        label = "第 %d 条价值区间" % index
        if not isinstance(raw, dict):
            raise ValidationError("invalid_value_cost", "%s必须是对象" % label)
        _reject_extra_fields(raw, ("minValue", "maxValueExclusive", "resourceCost"), label)
        minimum = _require_int(raw.get("minValue"), "%s下限" % label, 0, JS_SAFE_INTEGER)
        upper_raw = raw.get("maxValueExclusive")
        upper = None if upper_raw is None else _require_int(
            upper_raw, "%s上限" % label, 1, JS_SAFE_INTEGER
        )
        if upper is not None and upper <= minimum:
            raise ValidationError("invalid_value_range", "%s上限必须大于下限" % label)
        if expected_min is not None and minimum != expected_min:
            raise ValidationError("non_contiguous_value_ranges", "价值区间必须连续且不能重叠")
        if bands and bands[-1]["maxValueExclusive"] is None:
            raise ValidationError("open_value_range_not_last", "无上限的价值区间必须位于最后")
        bands.append(
            {
                "minValue": minimum,
                "maxValueExclusive": upper,
                "resourceCost": _require_int(
                    raw.get("resourceCost"), "%s资源点" % label, 1, JS_SAFE_INTEGER
                ),
            }
        )
        expected_min = upper
    if bands[-1]["maxValueExclusive"] is not None:
        raise ValidationError("missing_open_value_range", "最后一个价值区间必须没有上限")
    return bands


def canonicalize_resource_budgets(raw_budgets: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_budgets, list) or not raw_budgets:
        raise ValidationError("invalid_resource_budgets", "至少需要一条资源预算档位")
    if len(raw_budgets) > MAX_RESOURCE_BUDGET_OPTIONS:
        raise ValidationError(
            "too_many_resource_budgets",
            "资源预算档位最多允许 %d 条" % MAX_RESOURCE_BUDGET_OPTIONS,
        )
    records = []
    seen_ids = set()
    seen_budgets = set()
    for index, raw in enumerate(raw_budgets, start=1):
        label = "第 %d 条资源预算档位" % index
        if not isinstance(raw, dict):
            raise ValidationError("invalid_resource_budget", "%s必须是对象" % label)
        _reject_extra_fields(raw, ("budgetId", "resourceBudget"), label)
        budget_id = _require_int(raw.get("budgetId"), "%s ID" % label, 1, JS_SAFE_INTEGER)
        resource_budget = _require_int(raw.get("resourceBudget"), "%s资源点" % label, 1, JS_SAFE_INTEGER)
        if budget_id in seen_ids:
            raise ValidationError("duplicate_budget_id", "资源预算档位 ID 不能重复：%s" % budget_id)
        if resource_budget in seen_budgets:
            raise ValidationError("duplicate_resource_budget", "资源预算不能重复：%s" % resource_budget)
        seen_ids.add(budget_id)
        seen_budgets.add(resource_budget)
        records.append({"budgetId": budget_id, "resourceBudget": resource_budget})
    return records


def canonicalize_generation_settings(raw_settings: Any) -> Dict[str, Any]:
    if not isinstance(raw_settings, dict):
        raise ValidationError("invalid_settings", "基础参数必须是对象")
    _reject_extra_fields(
        raw_settings,
        ("boardWidth", "targetResourceBudget", "seed", "revealSpeedSeconds"),
        "基础参数",
    )
    target = raw_settings.get("targetResourceBudget")
    seed = raw_settings.get("seed")
    speed = raw_settings.get("revealSpeedSeconds")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise ValidationError("invalid_reveal_speed", "单件披露时长必须是数字")
    if speed < 0 or speed > 0.5:
        raise ValidationError("invalid_reveal_speed", "单件披露时长必须在 0 到 0.5 秒之间")
    return {
        "boardWidth": _require_int(raw_settings.get("boardWidth"), "容纳盒宽度", 1, MAX_BOARD_WIDTH),
        "targetResourceBudget": None if target is None else _require_int(
            target, "目标资源点", 1, JS_SAFE_INTEGER
        ),
        "seed": None if seed is None else _require_int(seed, "随机种子", 0, JS_SAFE_INTEGER),
        "revealSpeedSeconds": round(float(speed), 2),
    }


def canonicalize_configuration(
    raw_specs: Any, raw_items: Any, quality_ids: Optional[Set[int]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not isinstance(raw_specs, list) or not raw_specs:
        raise ValidationError("invalid_item_specs", "至少需要一条道具规格")
    if len(raw_specs) > MAX_SPEC_TYPES:
        raise ValidationError("too_many_spec_types", "道具规格最多允许 %d 种" % MAX_SPEC_TYPES)
    specs: List[Dict[str, Any]] = []
    seen_spec_ids: Set[int] = set()
    for index, raw_spec in enumerate(raw_specs, start=1):
        label = "第 %d 条规格" % index
        if not isinstance(raw_spec, dict):
            raise ValidationError("invalid_item_spec", "%s必须是对象" % label)
        _reject_extra_fields(raw_spec, ("specId", "width", "height"), label)
        spec_id = _require_int(raw_spec.get("specId"), "%s ID" % label, 1, JS_SAFE_INTEGER)
        if spec_id in seen_spec_ids:
            raise ValidationError("duplicate_spec_id", "规格 ID 不能重复：%s" % spec_id)
        seen_spec_ids.add(spec_id)
        specs.append(
            {
                "specId": spec_id,
                "width": _require_int(raw_spec.get("width"), "%s宽度" % label, 1, MAX_BOARD_WIDTH),
                "height": _require_int(raw_spec.get("height"), "%s高度" % label, 1, MAX_BOARD_WIDTH),
            }
        )

    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationError("invalid_item_pool", "至少需要一个具体道具")
    if len(raw_items) > MAX_SPEC_TYPES * MAX_POOL_ITEMS:
        raise ValidationError(
            "too_many_catalog_items", "具体道具最多允许 %d 个" % (MAX_SPEC_TYPES * MAX_POOL_ITEMS)
        )
    items: List[Dict[str, Any]] = []
    seen_item_ids: Set[int] = set()
    count_by_spec = {spec_id: 0 for spec_id in seen_spec_ids}
    for index, raw_item in enumerate(raw_items, start=1):
        label = "第 %d 个道具" % index
        if not isinstance(raw_item, dict):
            raise ValidationError("invalid_catalog_item", "%s必须是对象" % label)
        _reject_extra_fields(
            raw_item, ("itemId", "name", "qualityId", "value", "resourceCost", "specId"), label
        )
        item_id = _require_int(raw_item.get("itemId"), "%s ID" % label, 1, JS_SAFE_INTEGER)
        if item_id in seen_item_ids:
            raise ValidationError("duplicate_item_id", "道具 ID 不能重复：%s" % item_id)
        seen_item_ids.add(item_id)
        spec_id = _require_int(raw_item.get("specId"), "%s规格 ID" % label, 1, JS_SAFE_INTEGER)
        if spec_id not in seen_spec_ids:
            raise ValidationError("unknown_spec_id", "%s引用了不存在的规格：%s" % (label, spec_id))
        count_by_spec[spec_id] += 1
        if count_by_spec[spec_id] > MAX_POOL_ITEMS:
            raise ValidationError(
                "too_many_pool_items", "规格 %s 最多允许 %d 个具体道具" % (spec_id, MAX_POOL_ITEMS)
            )
        quality_id = _require_int(raw_item.get("qualityId"), "%s品质 ID" % label, 1, JS_SAFE_INTEGER)
        if quality_ids is not None and quality_id not in quality_ids:
            raise ValidationError("unknown_quality_id", "%s引用了不存在的品质：%s" % (label, quality_id))
        items.append(
            {
                "itemId": item_id,
                "name": _require_string(raw_item.get("name"), "%s名称" % label, 64),
                "qualityId": quality_id,
                "value": _require_int(raw_item.get("value"), "%s价值" % label, 0, JS_SAFE_INTEGER),
                "resourceCost": _require_int(
                    raw_item.get("resourceCost"), "%s资源点" % label, 1, JS_SAFE_INTEGER
                ),
                "specId": spec_id,
            }
        )
    return specs, items


def build_generator_specs(
    specs: Sequence[Dict[str, Any]], items: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    grouped = {spec["specId"]: dict(spec, items=[]) for spec in specs}
    for item in items:
        grouped[item["specId"]]["items"].append(
            {key: item[key] for key in ("itemId", "name", "qualityId", "value", "resourceCost")}
        )
    return [grouped[spec["specId"]] for spec in specs if grouped[spec["specId"]]["items"]]


def resource_cost_for_value(value: int, bands: Sequence[Dict[str, Any]]) -> int:
    for band in bands:
        upper = band["maxValueExclusive"]
        if value >= band["minValue"] and (upper is None or value < upper):
            return band["resourceCost"]
    raise ValidationError("value_not_covered", "藏品价值没有对应的资源消耗区间")


def _write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ConfigStoreError("无法写入配置文件 %s：%s" % (path.name, error)) from error


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ConfigStoreError("无法写入配置文件 %s：%s" % (path.name, error)) from error


def save_configuration(
    raw_specs: Any,
    raw_items: Any,
    spec_path: Path = SPEC_CONFIG_PATH,
    item_path: Path = ITEM_CONFIG_PATH,
    quality_ids: Optional[Set[int]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    specs, items = canonicalize_configuration(raw_specs, raw_items, quality_ids)
    with _STORE_LOCK:
        _write_jsonl(Path(spec_path), specs)
        _write_jsonl(Path(item_path), items)
    return specs, items


def save_all_configuration(
    raw_specs: Any,
    raw_items: Any,
    raw_qualities: Any,
    raw_value_costs: Any,
    spec_path: Path = SPEC_CONFIG_PATH,
    item_path: Path = ITEM_CONFIG_PATH,
    quality_path: Path = QUALITY_CONFIG_PATH,
    value_cost_path: Path = VALUE_COST_CONFIG_PATH,
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Validate and atomically replace every editable JSONL configuration file."""
    qualities = canonicalize_quality_configs(raw_qualities)
    value_costs = canonicalize_value_costs(raw_value_costs)
    specs, items = canonicalize_configuration(
        raw_specs,
        raw_items,
        {quality["qualityId"] for quality in qualities},
    )
    with _STORE_LOCK:
        _write_jsonl(Path(spec_path), specs)
        _write_jsonl(Path(item_path), items)
        _write_jsonl(Path(quality_path), qualities)
        _write_jsonl(Path(value_cost_path), value_costs)
    return specs, items, qualities, value_costs


def _read_jsonl(path: Path, label: str) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigStoreError("无法读取%s文件：%s" % (label, error)) from error
    records: List[Dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConfigStoreError("%s文件第 %d 行不是有效 JSON" % (label, line_number)) from error
        if not isinstance(record, dict):
            raise ConfigStoreError("%s文件第 %d 行必须是对象" % (label, line_number))
        records.append(record)
    if not records:
        raise ConfigStoreError("%s文件中没有有效记录" % label)
    return records


def load_reference_configuration(
    quality_path: Path = QUALITY_CONFIG_PATH,
    value_cost_path: Path = VALUE_COST_CONFIG_PATH,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    with _STORE_LOCK:
        raw_qualities = _read_jsonl(Path(quality_path), "品质配置")
        raw_bands = _read_jsonl(Path(value_cost_path), "价值资源消耗配置")
    if raw_qualities is None or raw_bands is None:
        raise ConfigStoreError("品质配置与价值资源消耗配置文件必须存在")
    try:
        return canonicalize_quality_configs(raw_qualities), canonicalize_value_costs(raw_bands)
    except ValidationError as error:
        raise ConfigStoreError("配置文件校验失败：%s" % error.message) from error


def load_resource_budget_configuration(
    resource_budget_path: Path = RESOURCE_BUDGET_CONFIG_PATH,
) -> List[Dict[str, Any]]:
    with _STORE_LOCK:
        raw_budgets = _read_jsonl(Path(resource_budget_path), "资源预算档位配置")
    if raw_budgets is None:
        raise ConfigStoreError("资源预算档位配置文件必须存在")
    try:
        return canonicalize_resource_budgets(raw_budgets)
    except ValidationError as error:
        raise ConfigStoreError("配置文件校验失败：%s" % error.message) from error


def load_configuration(
    spec_path: Path = SPEC_CONFIG_PATH,
    item_path: Path = ITEM_CONFIG_PATH,
    quality_ids: Optional[Set[int]] = None,
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    with _STORE_LOCK:
        raw_specs = _read_jsonl(Path(spec_path), "道具规格配置")
        raw_items = _read_jsonl(Path(item_path), "道具配置")
    if raw_specs is None and raw_items is None:
        return None
    if raw_specs is None or raw_items is None:
        raise ConfigStoreError("规格配置与道具配置文件必须同时存在")
    try:
        return canonicalize_configuration(raw_specs, raw_items, quality_ids)
    except ValidationError as error:
        raise ConfigStoreError("配置文件校验失败：%s" % error.message) from error


def load_generation_settings(
    settings_path: Path = SETTINGS_CONFIG_PATH,
) -> Dict[str, Any]:
    path = Path(settings_path)
    with _STORE_LOCK:
        if not path.exists():
            return dict(DEFAULT_GENERATION_SETTINGS)
        try:
            raw_settings = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ConfigStoreError("无法读取基础参数文件：%s" % error) from error
        except json.JSONDecodeError as error:
            raise ConfigStoreError("基础参数文件不是有效 JSON") from error
    try:
        return canonicalize_generation_settings(raw_settings)
    except ValidationError as error:
        raise ConfigStoreError("基础参数文件校验失败：%s" % error.message) from error


def save_generation_settings(
    raw_settings: Any,
    settings_path: Path = SETTINGS_CONFIG_PATH,
) -> Dict[str, Any]:
    settings = canonicalize_generation_settings(raw_settings)
    with _STORE_LOCK:
        _write_json(Path(settings_path), settings)
    return settings


def save_configuration_table(
    table: str,
    raw_records: Any,
    spec_path: Path = SPEC_CONFIG_PATH,
    item_path: Path = ITEM_CONFIG_PATH,
    quality_path: Path = QUALITY_CONFIG_PATH,
    value_cost_path: Path = VALUE_COST_CONFIG_PATH,
    resource_budget_path: Path = RESOURCE_BUDGET_CONFIG_PATH,
) -> List[Dict[str, Any]]:
    if table not in CONFIG_TABLES:
        raise ValidationError("unknown_config_table", "未知配表：%s" % table)
    paths = {
        "specs": Path(spec_path),
        "items": Path(item_path),
        "qualities": Path(quality_path),
        "value-costs": Path(value_cost_path),
        "resource-budgets": Path(resource_budget_path),
    }
    with _STORE_LOCK:
        raw_specs = _read_jsonl(paths["specs"], "道具规格配置")
        raw_items = _read_jsonl(paths["items"], "道具配置")
        raw_qualities = _read_jsonl(paths["qualities"], "品质配置")
        raw_value_costs = _read_jsonl(paths["value-costs"], "价值资源消耗配置")
        raw_resource_budgets = _read_jsonl(paths["resource-budgets"], "资源预算档位配置")
        if any(value is None for value in (raw_specs, raw_items, raw_qualities, raw_value_costs, raw_resource_budgets)):
            raise ConfigStoreError("五份配表文件必须同时存在")
        replacement = list(raw_records) if isinstance(raw_records, list) else raw_records
        if table == "specs":
            raw_specs = replacement
        elif table == "items":
            raw_items = replacement
        elif table == "qualities":
            raw_qualities = replacement
        elif table == "value-costs":
            raw_value_costs = replacement
        else:
            raw_resource_budgets = replacement

        qualities = canonicalize_quality_configs(raw_qualities)
        value_costs = canonicalize_value_costs(raw_value_costs)
        resource_budgets = canonicalize_resource_budgets(raw_resource_budgets)
        specs, items = canonicalize_configuration(
            raw_specs,
            raw_items,
            {quality["qualityId"] for quality in qualities},
        )
        records_by_table = {
            "specs": specs,
            "items": items,
            "qualities": qualities,
            "value-costs": value_costs,
            "resource-budgets": resource_budgets,
        }
        _write_jsonl(paths[table], records_by_table[table])
    return records_by_table[table]
