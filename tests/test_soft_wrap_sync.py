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
        assert not remaining, (
            f"published prose drift remains: {published_path.name} {remaining[:5]}"
        )


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


def test_x01_traversal_stem_has_no_threaded_tree_bleed():
    data = _load(COURSES["ds"][1])
    question = next(
        q
        for chapter in data["chapters"]
        if "二叉树的遍历和线索二叉树" in str(chapter.get("name"))
        and "选择题" in str(chapter.get("name"))
        for q in chapter["questions"]
        if q.get("id") == "X01"
    )
    assert question["content"] == "在下列关于二叉树遍历的说法中，正确的是（）。"
    assert "函数1" not in question["content"]
    assert "ltag" not in question["content"]


def test_x07_ipv4_stem_has_no_icmp_footnote_bleed():
    data = _load(COURSES["net"][1])
    question = next(
        q
        for chapter in data["chapters"]
        if "IPv4" in str(chapter.get("name")) and "选择题" in str(chapter.get("name"))
        for q in chapter["questions"]
        if q.get("id") == "X07"
    )
    assert question["content"] == "在IP首部的字段中，与分片和重组无关的字段是（）。"
    assert "ICMP" not in question["content"]
    assert "RFC" not in question["content"]


def test_x05_sequential_storage_stem_keeps_array_table():
    data = _load(COURSES["ds"][1])
    question = next(
        q
        for chapter in data["chapters"]
        if "二叉树的遍历和线索二叉树" in str(chapter.get("name"))
        and "选择题" in str(chapter.get("name"))
        for q in chapter["questions"]
        if q.get("id") == "X05"
        and "gdbhefca" in json.dumps(q.get("options") or {}, ensure_ascii=False)
    )
    content = question["content"]
    assert "一维数组" in content
    assert question.get("has_image") is True
    assert (question.get("image_ref") or {}).get(
        "cropped"
    ) == "crops/ds/page_152_X05.png"
    assert "D b C d e f g h" not in content
    assert "|" not in content
    assert "2i+1和2i+2" not in str((question.get("answer") or {}).get("explanation"))


def test_quality_ledger_hashes_match_all_published_json():
    bank_dir = COURSES["ds"][1].parent
    ledger = _load(bank_dir / "quality-ledger.json")
    for course_key in COURSES:
        path = bank_dir / f"data-{course_key}.json"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert ledger["published_hashes"][course_key] == actual
