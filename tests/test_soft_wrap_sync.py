"""软换行选择性同步与发布包一致性回归。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sync_published_prose import COURSES, candidate, question_map


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pure_prose_candidates_are_exhausted_after_sync():
    for source_path, published_path, _course_name in COURSES.values():
        source = _load(source_path)
        published = _load(published_path)
        source_rows = question_map(source)
        remaining = []
        for chapter in published.get("chapters", []):
            for question in chapter.get("questions", []):
                source_question = source_rows.get(
                    (str(chapter.get("name") or ""), str(question.get("id") or ""))
                )
                if source_question and candidate(source_question, question):
                    remaining.append(question.get("id"))
        assert not remaining, f"published prose drift remains: {published_path.name} {remaining[:5]}"


def test_x28_has_no_ocr_line_break_in_published_ds():
    data = _load(COURSES["ds"][1])
    question = next(
        q
        for chapter in data["chapters"]
        if "二叉树的概念" in str(chapter.get("name"))
        for q in chapter["questions"]
        if q.get("id") == "X28"
    )
    assert "结\n构" not in question["content"]
    assert "需要\n的" not in question["content"]


def test_quality_ledger_hashes_match_all_published_json():
    bank_dir = COURSES["ds"][1].parent
    ledger = _load(bank_dir / "quality-ledger.json")
    for course_key in COURSES:
        path = bank_dir / f"data-{course_key}.json"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert ledger["published_hashes"][course_key] == actual
