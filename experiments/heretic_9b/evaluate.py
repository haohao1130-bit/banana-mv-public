"""Offline, non-blocking text comparison for Heretic BANANAMV experiments.

No GPU, project files, packages, or network access required.
Inputs are UTF-8 JSONL:
  cases: {"id":"x","required":["..."],"forbidden":["..."],"expect_json":false}
  responses: {"id":"x","output":"..."}
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FILLER_PREFIXES = (
    "好的，我來", "以下是", "當然可以", "沒問題", "首先", "讓我們",
    "here is", "certainly", "of course",
)
CAMERA_TERMS = ("鏡頭", "攝影機", "跟拍", "推近", "特寫", "wide shot", "close-up", "camera")


def load_jsonl(path: Path) -> dict[str, dict]:
    rows = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSONL: {exc}") from exc
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError(f"{path}:{lineno}: expected object with nonempty string id")
        if item["id"] in rows:
            raise ValueError(f"{path}:{lineno}: duplicate id {item['id']!r}")
        rows[item["id"]] = item
    return rows


def assess(case: dict, response: dict) -> dict:
    output = response.get("output", "")
    if not isinstance(output, str):
        raise ValueError(f"response {case['id']}: output must be string")
    lower = output.casefold()
    required = case.get("required", [])
    forbidden = case.get("forbidden", [])
    if not isinstance(required, list) or not isinstance(forbidden, list):
        raise ValueError(f"case {case['id']}: required/forbidden must be lists")
    if not all(isinstance(x, str) and x for x in required + forbidden):
        raise ValueError(f"case {case['id']}: terms must be nonempty strings")

    found_required = [term for term in required if term.casefold() in lower]
    found_forbidden = [term for term in forbidden if term.casefold() in lower]
    lines = [s.strip() for s in re.split(r"[。！？!?;\n]+", lower) if s.strip()]
    repeated = len(lines) - len(set(lines))
    json_valid = None
    if case.get("expect_json", False):
        try:
            json.loads(output)
            json_valid = True
        except json.JSONDecodeError:
            json_valid = False
    return {
        "id": case["id"],
        "characters": len(output),
        "required_coverage": round(len(found_required) / len(required), 3) if required else None,
        "forbidden_hits": found_forbidden,
        "filler_opening": lower.lstrip().startswith(FILLER_PREFIXES),
        "has_camera_term": any(term in lower for term in CAMERA_TERMS),
        "duplicate_sentences": repeated,
        "json_valid": json_valid,
    }


def aggregate(rows: list[dict]) -> dict:
    count = len(rows)
    if not count:
        return {"cases": 0}
    coverage = [x["required_coverage"] for x in rows if x["required_coverage"] is not None]
    json_checked = [x["json_valid"] for x in rows if x["json_valid"] is not None]
    return {
        "cases": count,
        "avg_characters": round(sum(x["characters"] for x in rows) / count, 1),
        "required_coverage_avg": round(sum(coverage) / len(coverage), 3) if coverage else None,
        "cases_with_forbidden_hits": sum(bool(x["forbidden_hits"]) for x in rows),
        "filler_openings": sum(x["filler_opening"] for x in rows),
        "cases_with_camera_term": sum(x["has_camera_term"] for x in rows),
        "duplicate_sentences": sum(x["duplicate_sentences"] for x in rows),
        "json_valid": sum(x is True for x in json_checked) if json_checked else None,
        "json_checked": len(json_checked),
    }


def compare(cases: dict, baseline: dict, candidate: dict) -> dict:
    expected = set(cases)
    for name, responses in (("baseline", baseline), ("candidate", candidate)):
        if set(responses) != expected:
            missing = sorted(expected - set(responses))
            extra = sorted(set(responses) - expected)
            raise ValueError(f"{name}: id mismatch; missing={missing}, extra={extra}")
    before = [assess(cases[key], baseline[key]) for key in sorted(expected)]
    after = [assess(cases[key], candidate[key]) for key in sorted(expected)]
    return {
        "warning": "Text-only diagnostics; not an H3/video or role-continuity validation.",
        "baseline": aggregate(before),
        "candidate": aggregate(after),
        "per_case": [
            {"id": b["id"], "baseline": b, "candidate": a}
            for b, a in zip(before, after)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    result = compare(load_jsonl(args.cases), load_jsonl(args.baseline), load_jsonl(args.candidate))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
