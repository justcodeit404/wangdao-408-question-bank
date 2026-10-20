#!/usr/bin/env python3
"""把 data/zhenti/*.json 的真题逐条登记进 quality ledger，不做全量重建。

为什么不跑 `quality_ledger.py`：全量 build_ledger 在纯文本管线里无法复现增量
累积的 vision/page_review 认证状态，会把几千道已认证题打回 hold（发布流程因此
只允许 --refresh-hashes）。新增整年真题时用本脚本按当前发布态哈希把这几十条
直接登记为 certified，再跑 `quality_ledger.py --refresh-hashes` 刷新清单。

用法：python scripts/register_curated_zhenti.py && python scripts/quality_ledger.py --refresh-hashes
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import COURSES, MATH_BANK_DIR  # noqa: E402
from luna_review_v2 import apply_v2_fields  # noqa: E402
from quality_hold import source_uid  # noqa: E402
from quality_ledger import LEDGER_PATH, iter_published_rows, question_hash  # noqa: E402
from utils import write_json_atomic  # noqa: E402

ZHENTI_DIR = Path(__file__).resolve().parents[1] / "data" / "zhenti"


def _published_questions() -> dict[str, tuple[str, dict]]:
    rows: dict[str, tuple[str, dict]] = {}
    for course in COURSES:
        path = MATH_BANK_DIR / f"data-{course.key}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for uid, chapter, question in iter_published_rows(course.key, data):
            rows[uid] = (chapter, question)
    return rows


def main() -> int:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    items = ledger["items"]
    published = _published_questions()
    registered = 0
    for path in sorted(ZHENTI_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta") or {}
        year = meta.get("year")
        for item in payload.get("items") or []:
            uid = source_uid(item["course"], item["chapter"], item["id"])
            hit = published.get(uid)
            if hit is None:
                raise SystemExit(f"[curated] 发布态找不到 {uid}，先跑 rebuild_bank.ps1")
            chapter, question = hit
            current_hash = question_hash(question)
            row = dict(items.get(uid) or {})
            row.update(
                {
                    "source_uid": uid,
                    "course_key": item["course"],
                    "chapter": chapter,
                    "question_id": str(question.get("id") or ""),
                    "source_hash": current_hash,
                    "source_fidelity": "verified",
                    "answer_validation": "verified",
                    "overall": "certified",
                    "reason_codes": [f"curated_zhenti_{year}"],
                    "q_pages": list(question.get("q_pages") or []),
                    "a_pages": list(question.get("a_pages") or []),
                    "has_image": bool(
                        question.get("has_image") or question.get("image_ref")
                    ),
                    "answer_choice": str(
                        (question.get("answer") or {}).get("choice") or ""
                    ),
                    "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "evidence": {
                        "curated_zhenti": {
                            "year": year,
                            "source": meta.get("source_kind") or "official",
                            "sources": [
                                s.get("url") for s in (meta.get("sources") or [])
                            ],
                        }
                    },
                    "provenance": "curated-zhenti",
                }
            )
            apply_v2_fields(row, question)
            items[uid] = row
            registered += 1

    counts = Counter(row.get("overall") for row in items.values())
    ledger["summary"] = {
        "total": len(items),
        "certified": counts.get("certified", 0),
        "pending": counts.get("pending", 0),
        "held": counts.get("hold", 0),
    }
    for key, course in (ledger.get("courses") or {}).items():
        own = [row for row in items.values() if row.get("course_key") == key]
        own_counts = Counter(row.get("overall") for row in own)
        course.update(
            {
                "total": len(own),
                "certified": own_counts.get("certified", 0),
                "pending": own_counts.get("pending", 0),
                "held": own_counts.get("hold", 0),
            }
        )
    ledger["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(LEDGER_PATH, ledger, indent=2, ensure_ascii=False)
    print(f"registered {registered} curated questions")
    print(json.dumps(ledger["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
