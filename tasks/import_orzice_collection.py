"""Import Orzice collection names, grades and current prices into items JSONL."""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config_store import (  # noqa: E402
    QUALITY_CONFIG_PATH,
    VALUE_COST_CONFIG_PATH,
    load_reference_configuration,
    resource_cost_for_value,
)


SOURCE_URL = "https://orzice.com/v/collection"
ROW_PATTERN = re.compile(r'<tr[^>]*class="[^"]*table-row[^"]*"[^>]*>(.*?)</tr>', re.S)
ID_PATTERN = re.compile(r'href="/v/info/(\d+)"')
GRADE_PATTERN = re.compile(r'data-grade="(\d+)"')
NAME_PATTERN = re.compile(r'<div[^>]*class="[^"]*item-name[^"]*"[^>]*>(.*?)</div>', re.S)
PRICE_PATTERN = re.compile(
    r'<span[^>]*class="(?:[^"]* )?icon-gold(?: [^"]*)?"[^>]*>(.*?)</span>',
    re.S,
)
PAGE_PATTERN = re.compile(r'<li[^>]*class="[^"]*number[^"]*"[^>]*>\s*(\d+)\s*</li>')
COUNT_PATTERN = re.compile(r"this\.count\s*=\s*(\d+)")
TAG_PATTERN = re.compile(r"<[^>]+>")


def fetch_page(page: int, grade: int) -> str:
    query = urlencode(
        {"a": "collection", "p": page, "top": "3-1", "grade": grade, "mtype": -1, "n": ""}
    )
    request = Request(
        "%s?%s" % (SOURCE_URL, query),
        headers={"User-Agent": "Collection Showcase Simulator importer/1.0"},
    )
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def clean_text(value: str) -> str:
    return html.unescape(TAG_PATTERN.sub("", value)).strip()


def parse_page(document: str) -> List[Tuple[int, str, int, int]]:
    records = []
    for row in ROW_PATTERN.findall(document):
        item_id = ID_PATTERN.search(row)
        grade = GRADE_PATTERN.search(row)
        name = NAME_PATTERN.search(row)
        price = PRICE_PATTERN.search(row)
        if not all((item_id, grade, name, price)):
            raise RuntimeError("收集品页面存在无法识别的表格行")
        price_text = clean_text(price.group(1)).replace(",", "")
        formatted_price = re.search(r"NumQfw\((\d+)\)", price_text)
        if formatted_price:
            price_text = formatted_price.group(1)
        if not price_text.isdigit():
            raise RuntimeError("道具 %s 的当前价格无效：%s" % (clean_text(name.group(1)), price_text))
        records.append(
            (
                int(item_id.group(1)),
                clean_text(name.group(1)),
                int(grade.group(1)),
                int(price_text),
            )
        )
    return records


def collect_records(grades: List[int]) -> List[Tuple[int, str, int, int]]:
    records = []
    expected_count = 0
    for grade in sorted(grades):
        first_page = fetch_page(1, grade)
        count_match = COUNT_PATTERN.search(first_page)
        if not count_match:
            raise RuntimeError("页面未返回 %d 级品质的记录总数" % grade)
        grade_count = int(count_match.group(1))
        expected_count += grade_count
        grade_records = parse_page(first_page)
        for page in range(2, (grade_count + 9) // 10 + 1):
            grade_records.extend(parse_page(fetch_page(page, grade)))
        if len(grade_records) != grade_count:
            raise RuntimeError(
                "%d 级品质应有 %d 条，实际读取 %d 条"
                % (grade, grade_count, len(grade_records))
            )
        if any(record[2] != grade for record in grade_records):
            raise RuntimeError("%d 级品质分页混入了其他品质" % grade)
        records.extend(grade_records)
    unique: Dict[int, Tuple[int, str, int, int]] = {}
    for record in records:
        if record[0] in unique:
            raise RuntimeError("网页返回了重复道具 ID：%d" % record[0])
        unique[record[0]] = record
    if len(unique) != expected_count:
        raise RuntimeError("网页总数为 %d，唯一道具数为 %d" % (expected_count, len(unique)))
    return [unique[item_id] for item_id in sorted(unique)]


def load_existing_items(path: Path) -> Dict[int, Dict[str, object]]:
    if not path.exists():
        return {}
    existing: Dict[int, Dict[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("现有输出文件第 %d 行不是有效 JSON" % line_number) from error
        item_id = record.get("itemId") if isinstance(record, dict) else None
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            raise RuntimeError("现有输出文件第 %d 行缺少有效道具 ID" % line_number)
        if item_id in existing:
            raise RuntimeError("现有输出文件包含重复道具 ID：%d" % item_id)
        existing[item_id] = record
    return existing


def write_jsonl_atomically(path: Path, records: List[Dict[str, object]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec-id", type=int, default=1)
    args = parser.parse_args()

    qualities, value_costs = load_reference_configuration(
        ROOT / QUALITY_CONFIG_PATH,
        ROOT / VALUE_COST_CONFIG_PATH,
    )
    quality_ids = {record["qualityId"] for record in qualities}
    rows = collect_records(sorted(quality_ids))
    existing = load_existing_items(args.output)
    imported = []
    for item_id, name, quality_id, value in rows:
        if quality_id not in quality_ids:
            raise RuntimeError("网页品质等级未在本地配置：%d" % quality_id)
        try:
            resource_cost = resource_cost_for_value(value, value_costs)
        except Exception as error:
            raise RuntimeError("道具 %s（ID %d，价值 %d）没有对应的资源区间" % (name, item_id, value)) from error
        previous = existing.get(item_id)
        imported.append(
            {
                "itemId": item_id,
                "name": name,
                "qualityId": quality_id,
                "value": value,
                "resourceCost": resource_cost,
                "specId": previous["specId"] if previous is not None else args.spec_id,
            }
        )

    imported_ids = {row["itemId"] for row in imported}
    preserved = [record for item_id, record in existing.items() if item_id not in imported_ids]
    output_records = sorted(imported + preserved, key=lambda record: int(record["itemId"]))
    write_jsonl_atomically(args.output, output_records)
    print(
        json.dumps(
            {
                "source": SOURCE_URL,
                "records": len(output_records),
                "updated": sum(row["itemId"] in existing for row in imported),
                "new": sum(row["itemId"] not in existing for row in imported),
                "preservedLocal": len(preserved),
                "minimumValue": min(row["value"] for row in imported),
                "maximumValue": max(row["value"] for row in imported),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
