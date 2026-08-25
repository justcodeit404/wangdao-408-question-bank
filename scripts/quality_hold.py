#!/usr/bin/env python3
"""从发布 JSON 收集刷题不可用的 408 选择题 UID，写入 quality-hold.json。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from config import COURSES, MATH_BANK_DIR
from utils import write_json_atomic

HOLD_PATH: Final[Path] = MATH_BANK_DIR / "quality-hold.json"
OCR_NOISE_RE: Final[re.Pattern[str]] = re.compile(
    r"2027年.{0,25}考研复习指导|(?<![A-Za-z])(?:IIL|IIl)(?![A-Za-z])|é|[=:]{4,}"
)
TRUNC_STEM_RE: Final[re.Pattern[str]] = re.compile(r"当扫描到时")
TRUNC_STEM_OK_RE: Final[re.Pattern[str]] = re.compile(r"当扫描到\s+\S+\s*时")


def source_uid(course_key: str, chapter: str, qid: str) -> str:
    """与 platform-v2 import 约定一致：408:cs408-ds::章 · 节 · 选择题::X01。"""
    return f"408:cs408-{course_key}::{chapter}::{qid}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _answer_obj(question: Mapping[str, object]) -> Mapping[str, object]:
    answer = question.get("answer")
    return answer if isinstance(answer, Mapping) else {}


def _options_map(question: Mapping[str, object]) -> dict[str, str]:
    raw = question.get("options")
    if not isinstance(raw, dict):
        return {}
    return {str(key): "" if value is None else str(value) for key, value in raw.items()}


def collect_hold_uids(course_key: str, data: Mapping[str, object]) -> frozenset[str]:
    """扫描一科发布 JSON，返回应隔离的选择题 source_uid。"""
    held: set[str] = set()
    raw_chapters = data.get("chapters")
    chapters = raw_chapters if isinstance(raw_chapters, list) else []
    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            continue
        chapter_name = str(chapter.get("name") or chapter.get("topic_title") or "")
        raw_questions = chapter.get("questions")
        questions = raw_questions if isinstance(raw_questions, list) else []
        for question in questions:
            if not isinstance(question, Mapping):
                continue
            qid = str(question.get("id") or "").strip()
            if not qid:
                continue
            if _choice_should_hold(question):
                held.add(source_uid(course_key, chapter_name, qid))
    return frozenset(held)


def _choice_should_hold(question: Mapping[str, object]) -> bool:
    qtype = str(question.get("type") or "")
    if "选择" not in qtype:
        return False
    content = str(question.get("content") or "").strip()
    if not content:
        return True
    if TRUNC_STEM_RE.search(content) and not TRUNC_STEM_OK_RE.search(content):
        return True
    options = _options_map(question)
    keys = {str(key).strip().upper() for key in options}
    if sorted(set("ABCD") - keys):
        return True
    if any(not str(value or "").strip() for value in options.values()):
        return True
    bodies = [
        str(value).strip() for value in options.values() if str(value or "").strip()
    ]
    if len(bodies) != len(set(bodies)):
        return True
    choice = str(_answer_obj(question).get("choice") or "").strip().upper()
    letters = [char for char in choice if char.isalpha()]
    if not choice or any(char not in keys or char not in "ABCDEF" for char in letters):
        return True
    blob = "\n".join(
        [
            content,
            *[str(value or "") for value in options.values()],
            str(_answer_obj(question).get("explanation") or ""),
        ]
    )
    return bool(OCR_NOISE_RE.search(blob))


def collect_all_hold_uids() -> frozenset[str]:
    held: set[str] = set()
    for course in COURSES:
        published = MATH_BANK_DIR / f"data-{course.key}.json"
        if not published.is_file():
            continue
        loaded = json.loads(published.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            held.update(collect_hold_uids(course.key, loaded))
    return frozenset(held)


def write_manifest() -> Path:
    """重写 quality-hold.json：当前发布文件哈希 + 隔离 UID。"""
    source_hashes: dict[str, str] = {}
    files: dict[str, str] = {}
    for course in COURSES:
        published = MATH_BANK_DIR / f"data-{course.key}.json"
        if published.is_file():
            digest = _sha256(published)
            source_hashes[course.key] = digest
            files[published.name] = digest
        out_path = Path(course.out_json)
        if out_path.is_file():
            files[out_path.name] = _sha256(out_path)

    uids = sorted(collect_all_hold_uids())
    hold = {
        "schema_version": 2,
        "source_hashes": source_hashes,
        "files": files,
        "source_uids": uids,
        "summary": {
            "held": len(uids),
            "note": "structural choice defects isolated from drill/import",
            "courses": list(source_hashes.keys()),
        },
    }
    write_json_atomic(HOLD_PATH, hold, indent=2, ensure_ascii=False)
    return HOLD_PATH


def main() -> int:
    path = write_manifest()
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path}")
    print(f"held={data['summary']['held']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
