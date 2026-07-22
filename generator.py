"""Resource-budget collectible generation for Collection Showcase Simulator."""

from dataclasses import dataclass
import random
import secrets
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple


MAX_BOARD_WIDTH = 30
MAX_SPEC_TYPES = 20
MAX_ITEMS = 200
MAX_POOL_ITEMS = 1_000
MAX_QUALITY_TYPES = 20
MAX_RESOURCE_BUDGET_OPTIONS = 20
MAX_WEIGHT = 1_000_000
JS_SAFE_INTEGER = 9_007_199_254_740_991
RESOURCE_BUDGETS = (6000, 3800, 2550, 1200)
QUALITY_COLORS = ("gray", "green", "blue", "purple", "orange", "red")
QUALITIES = QUALITY_COLORS


class ValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class GenerationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class QualityConfig:
    quality_id: int
    label: str
    color: str
    weight: int
    quality_index: int


@dataclass(frozen=True)
class CatalogItem:
    item_id: int
    name: str
    quality_id: int
    value: int
    resource_cost: int
    item_index: int


@dataclass(frozen=True)
class ItemSpec:
    spec_id: int
    width: int
    height: int
    items: Tuple[CatalogItem, ...]
    spec_index: int


@dataclass(frozen=True)
class Placement:
    spec: ItemSpec
    item: CatalogItem
    x: int
    y: int
    width: int
    height: int
    rotation: int
    selection_order: int


def _require_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("invalid_integer", "%s 必须是整数" % field_name)
    if value < minimum or value > maximum:
        raise ValidationError(
            "integer_out_of_range",
            "%s 必须在 %d 到 %d 之间" % (field_name, minimum, maximum),
        )
    return value


def _require_string(value: Any, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("invalid_string", "%s 必须是非空字符串" % field_name)
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValidationError(
            "string_too_long", "%s 最多允许 %d 个字符" % (field_name, maximum)
        )
    return normalized


def _reject_extra_fields(value: Dict[str, Any], allowed: Sequence[str], label: str) -> None:
    unsupported = sorted(set(value) - set(allowed))
    if unsupported:
        raise ValidationError(
            "unsupported_field",
            "%s包含不支持的字段：%s" % (label, ", ".join(unsupported)),
        )


def _validate_resource_budget_configs(raw_configs: Any) -> List[int]:
    if raw_configs is None:
        return list(RESOURCE_BUDGETS)
    if not isinstance(raw_configs, list) or not raw_configs:
        raise ValidationError("invalid_resource_budgets", "至少需要一条资源预算档位")
    if len(raw_configs) > MAX_RESOURCE_BUDGET_OPTIONS:
        raise ValidationError(
            "too_many_resource_budgets",
            "资源预算档位最多允许 %d 条" % MAX_RESOURCE_BUDGET_OPTIONS,
        )
    budget_ids = set()
    budget_values = set()
    options = []
    for index, raw_config in enumerate(raw_configs, start=1):
        label = "第 %d 条资源预算档位" % index
        if not isinstance(raw_config, dict):
            raise ValidationError("invalid_resource_budget", "%s必须是对象" % label)
        _reject_extra_fields(raw_config, ("budgetId", "resourceBudget"), label)
        budget_id = _require_int(raw_config.get("budgetId"), "%s ID" % label, 1, JS_SAFE_INTEGER)
        resource_budget = _require_int(raw_config.get("resourceBudget"), "%s资源点" % label, 1, JS_SAFE_INTEGER)
        if budget_id in budget_ids:
            raise ValidationError("duplicate_budget_id", "资源预算档位 ID 不能重复：%s" % budget_id)
        if resource_budget in budget_values:
            raise ValidationError("duplicate_resource_budget", "资源预算不能重复：%s" % resource_budget)
        budget_ids.add(budget_id)
        budget_values.add(resource_budget)
        options.append(resource_budget)
    return options


def _validate_inputs(
    board_width: Any,
    item_specs: Any,
    quality_configs: Any,
    seed: Any,
    target_resource_budget: Any,
) -> Tuple[int, List[ItemSpec], List[QualityConfig], int, Optional[int]]:
    width = _require_int(board_width, "容纳盒宽度", 1, MAX_BOARD_WIDTH)
    if seed is None:
        actual_seed = secrets.randbits(53)
    else:
        actual_seed = _require_int(seed, "随机种子", 0, JS_SAFE_INTEGER)
    configured_budget = None if target_resource_budget is None else _require_int(
        target_resource_budget, "目标资源点", 1, JS_SAFE_INTEGER
    )

    if not isinstance(quality_configs, list) or not quality_configs:
        raise ValidationError("invalid_quality_configs", "至少需要一条品质配置")
    if len(quality_configs) > MAX_QUALITY_TYPES:
        raise ValidationError(
            "too_many_quality_types", "品质最多允许 %d 种" % MAX_QUALITY_TYPES
        )
    qualities: List[QualityConfig] = []
    seen_quality_ids = set()
    for quality_index, raw_quality in enumerate(quality_configs):
        label = "第 %d 条品质" % (quality_index + 1)
        if not isinstance(raw_quality, dict):
            raise ValidationError("invalid_quality_config", "%s必须是对象" % label)
        _reject_extra_fields(
            raw_quality, ("qualityId", "label", "color", "weight"), label
        )
        quality_id = _require_int(
            raw_quality.get("qualityId"), "%s ID" % label, 1, JS_SAFE_INTEGER
        )
        if quality_id in seen_quality_ids:
            raise ValidationError(
                "duplicate_quality_id", "品质 ID 不能重复：%s" % quality_id
            )
        seen_quality_ids.add(quality_id)
        color = _require_string(raw_quality.get("color"), "%s颜色" % label, 16)
        if color not in QUALITY_COLORS:
            raise ValidationError(
                "invalid_quality_color",
                "%s颜色必须是 %s 之一" % (label, " / ".join(QUALITY_COLORS)),
            )
        qualities.append(
            QualityConfig(
                quality_id,
                _require_string(raw_quality.get("label"), "%s名称" % label, 16),
                color,
                _require_int(raw_quality.get("weight"), "%s权重" % label, 1, MAX_WEIGHT),
                quality_index,
            )
        )

    if not isinstance(item_specs, list) or not item_specs:
        raise ValidationError("invalid_item_specs", "至少需要一条藏品规格")
    if len(item_specs) > MAX_SPEC_TYPES:
        raise ValidationError(
            "too_many_spec_types", "藏品规格最多允许 %d 种" % MAX_SPEC_TYPES
        )
    specs: List[ItemSpec] = []
    seen_spec_ids = set()
    seen_item_ids = set()
    maximum_item_value = 0
    for spec_index, raw_spec in enumerate(item_specs):
        label = "第 %d 条规格" % (spec_index + 1)
        if not isinstance(raw_spec, dict):
            raise ValidationError("invalid_item_spec", "%s必须是对象" % label)
        _reject_extra_fields(raw_spec, ("specId", "width", "height", "items"), label)
        spec_id = _require_int(
            raw_spec.get("specId"), "%s ID" % label, 1, JS_SAFE_INTEGER
        )
        if spec_id in seen_spec_ids:
            raise ValidationError("duplicate_spec_id", "规格 ID 不能重复：%s" % spec_id)
        seen_spec_ids.add(spec_id)
        spec_width = _require_int(raw_spec.get("width"), "%s宽度" % label, 1, MAX_BOARD_WIDTH)
        spec_height = _require_int(raw_spec.get("height"), "%s高度" % label, 1, MAX_BOARD_WIDTH)
        if spec_width > width and spec_height > width:
            raise ValidationError(
                "item_too_wide", "%s在 0° 和 90° 方向下都超过容纳盒宽度" % label
            )
        raw_items = raw_spec.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValidationError("invalid_item_pool", "%s至少需要一个具体道具" % label)
        if len(raw_items) > MAX_POOL_ITEMS:
            raise ValidationError(
                "too_many_pool_items", "%s最多允许 %d 个具体道具" % (label, MAX_POOL_ITEMS)
            )
        items: List[CatalogItem] = []
        for item_index, raw_item in enumerate(raw_items):
            item_label = "%s的第 %d 个道具" % (label, item_index + 1)
            if not isinstance(raw_item, dict):
                raise ValidationError("invalid_catalog_item", "%s必须是对象" % item_label)
            _reject_extra_fields(
                raw_item, ("itemId", "name", "qualityId", "value", "resourceCost"), item_label
            )
            item_id = _require_int(
                raw_item.get("itemId"), "%s ID" % item_label, 1, JS_SAFE_INTEGER
            )
            if item_id in seen_item_ids:
                raise ValidationError("duplicate_item_id", "道具 ID 不能重复：%s" % item_id)
            seen_item_ids.add(item_id)
            quality_id = _require_int(
                raw_item.get("qualityId"), "%s品质 ID" % item_label, 1, JS_SAFE_INTEGER
            )
            if quality_id not in seen_quality_ids:
                raise ValidationError(
                    "unknown_quality_id", "%s引用了不存在的品质：%s" % (item_label, quality_id)
                )
            value = _require_int(raw_item.get("value"), "%s价值" % item_label, 0, JS_SAFE_INTEGER)
            maximum_item_value = max(maximum_item_value, value)
            items.append(
                CatalogItem(
                    item_id,
                    _require_string(raw_item.get("name"), "%s名称" % item_label, 64),
                    quality_id,
                    value,
                    _require_int(
                        raw_item.get("resourceCost"), "%s资源点" % item_label, 1, JS_SAFE_INTEGER
                    ),
                    item_index,
                )
            )
        specs.append(ItemSpec(spec_id, spec_width, spec_height, tuple(items), spec_index))
    if maximum_item_value * MAX_ITEMS > JS_SAFE_INTEGER:
        raise ValidationError(
            "value_sum_too_large", "最大藏品价值总和超过 JavaScript 安全整数范围"
        )
    return width, specs, qualities, actual_seed, configured_budget


def _orientations(spec: ItemSpec, board_width: int) -> List[Tuple[int, int, int]]:
    orientations = []
    if spec.width <= board_width:
        orientations.append((spec.width, spec.height, 0))
    if spec.width != spec.height and spec.height <= board_width:
        orientations.append((spec.height, spec.width, 90))
    return orientations


def _skyline_layout(
    board_width: int,
    selected: Sequence[Tuple[ItemSpec, CatalogItem]],
    rng: random.Random,
) -> Tuple[List[Placement], int]:
    skyline = [0] * board_width
    placements: List[Placement] = []
    for selection_order, (spec, item) in enumerate(selected):
        orientations = _orientations(spec, board_width)
        if not orientations:
            raise GenerationError("layout_failed", "存在无法放入固定宽度的规格")
        item_width, item_height, rotation = rng.choice(orientations)
        candidates = []
        for x in range(board_width - item_width + 1):
            y = max(skyline[x : x + item_width])
            resulting_height = max(max(skyline), y + item_height)
            candidates.append((resulting_height, y, x))
        _, y, x = min(candidates)
        for column in range(x, x + item_width):
            skyline[column] = y + item_height
        placements.append(
            Placement(
                spec, item, x, y, item_width, item_height, rotation, selection_order
            )
        )
    return placements, max(skyline)


def _occupied_snapshot(
    placements: Sequence[Placement], board_width: int, board_height: int
) -> Tuple[List[List[bool]], int]:
    occupied = [[False] * board_width for _ in range(board_height)]
    occupied_count = 0
    for placement in placements:
        for y in range(placement.y, placement.y + placement.height):
            for x in range(placement.x, placement.x + placement.width):
                occupied[y][x] = True
                occupied_count += 1
    return occupied, occupied_count


def generate_collection(
    board_width: Any,
    item_specs: Any,
    quality_configs: Any,
    seed: Any = None,
    target_resource_budget: Any = None,
    resource_budget_configs: Any = None,
) -> Dict[str, Any]:
    """Roll a budget, then repeatedly roll quality and a concrete affordable item."""
    width, specs, qualities, actual_seed, configured_budget = _validate_inputs(
        board_width, item_specs, quality_configs, seed, target_resource_budget
    )
    resource_budget_options = _validate_resource_budget_configs(resource_budget_configs)
    rng = random.Random(actual_seed)
    resource_budget = configured_budget if configured_budget is not None else rng.choice(resource_budget_options)
    remaining = resource_budget
    by_quality: Dict[int, List[Tuple[ItemSpec, CatalogItem]]] = {
        quality.quality_id: [] for quality in qualities
    }
    for spec in specs:
        for item in spec.items:
            by_quality[item.quality_id].append((spec, item))

    selected: List[Tuple[ItemSpec, CatalogItem]] = []
    while len(selected) < MAX_ITEMS:
        affordable_qualities = []
        affordable_items = []
        for quality in qualities:
            candidates = [
                pair
                for pair in by_quality[quality.quality_id]
                if pair[1].resource_cost <= remaining
            ]
            if candidates:
                affordable_qualities.append(quality)
                affordable_items.append(candidates)
        if not affordable_qualities:
            break
        selected_quality_index = rng.choices(
            range(len(affordable_qualities)),
            weights=[quality.weight for quality in affordable_qualities],
            k=1,
        )[0]
        chosen = rng.choice(affordable_items[selected_quality_index])
        selected.append(chosen)
        remaining -= chosen[1].resource_cost

    if not selected:
        raise GenerationError(
            "budget_too_low",
            "本局资源预算无法承担任何已配置道具",
        )

    placements, dynamic_height = _skyline_layout(width, selected, rng)
    spatial_placements = sorted(
        placements,
        key=lambda placement: (placement.y, placement.x, placement.selection_order),
    )
    occupied, occupied_count = _occupied_snapshot(
        spatial_placements, width, dynamic_height
    )
    quality_by_id = {quality.quality_id: quality for quality in qualities}
    uid_width = max(3, len(str(len(selected))))
    items: List[Dict[str, Any]] = []
    for order, placement in enumerate(spatial_placements, start=1):
        quality = quality_by_id[placement.item.quality_id]
        items.append(
            {
                "uid": "C%s" % str(order).zfill(uid_width),
                "itemId": placement.item.item_id,
                "name": placement.item.name,
                "qualityId": quality.quality_id,
                "quality": quality.color,
                "qualityLabel": quality.label,
                "value": placement.item.value,
                "resourceCost": placement.item.resource_cost,
                "specId": placement.spec.spec_id,
                "specIndex": placement.spec.spec_index,
                "x": placement.x,
                "y": placement.y,
                "width": placement.width,
                "height": placement.height,
                "sourceWidth": placement.spec.width,
                "sourceHeight": placement.spec.height,
                "rotation": placement.rotation,
                "placementOrder": order,
            }
        )

    item_values = [item.value for _, item in selected]
    total_value = sum(item_values)
    resource_consumed = resource_budget - remaining
    return {
        "boardWidth": width,
        "boardHeight": dynamic_height,
        "seed": actual_seed,
        "resourceBudgetOptions": resource_budget_options,
        "resourceBudget": resource_budget,
        "resourceBudgetMode": "configured" if configured_budget is not None else "rolled",
        "resourceConsumed": resource_consumed,
        "resourceRemaining": remaining,
        "itemCount": len(selected),
        "totalValue": total_value,
        "averageValuePerOccupiedCell": round(total_value / occupied_count, 2),
        "averageItemValue": round(total_value / len(selected), 2),
        "medianItemValue": median(item_values),
        "items": items,
        "occupied": occupied,
        "occupiedCount": occupied_count,
        "qualityRollCount": len(selected),
    }
