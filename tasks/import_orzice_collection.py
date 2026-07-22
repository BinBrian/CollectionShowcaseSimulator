"""Import Orzice collection names, grades and current prices into items JSONL."""

import argparse
import html
import json
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
    imported = []
    for item_id, name, quality_id, value in rows:
        if quality_id not in quality_ids:
            raise RuntimeError("网页品质等级未在本地配置：%d" % quality_id)
        try:
            resource_cost = resource_cost_for_value(value, value_costs)
        except Exception as error:
            raise RuntimeError("道具 %s（ID %d，价值 %d）没有对应的资源区间" % (name, item_id, value)) from error
        imported.append(
            {
                "itemId": item_id,
                "name": name,
                "qualityId": quality_id,
                "value": value,
                "resourceCost": resource_cost,
                "specId": args.spec_id,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in imported)
    args.output.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "source": SOURCE_URL,
                "records": len(imported),
                "minimumValue": min(row["value"] for row in imported),
                "maximumValue": max(row["value"] for row in imported),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
