#!/usr/bin/env python3
"""408 选择题答案交叉验证。

证据通道：
1. current：发布 JSON 当前答案；
2. raw_ocr：构建题库时保存的原始整页 OCR；
3. fresh_ocr：从原书页面图片重新运行 GPU OCR 的独立缓存。

扫描版 PDF 没有文本层，因此 fresh_ocr 是必须的高置信证据。未获得 fresh_ocr
确认、或证据冲突的题目会写入 math-bank/quality-hold.json，平台导入后自动隔离。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from config import COURSES, MATH_BANK_DIR, PROJECT_ROOT, REPO_ROOT, REPORTS_DIR
from parse_questions import parse_answer_page
from utils import write_json_atomic

sys.stdout.reconfigure(encoding="utf-8")

CACHE_ROOT = REPO_ROOT / "temp" / "408-cross-validation" / "fresh_ocr"
OCR_CACHE_PROTOCOL = "ocr-cache-v2"
HOLD_PATH = MATH_BANK_DIR / "quality-hold.json"
REPORT_PATH = REPORTS_DIR / "cross_validation_report.json"
REVIEW_PATH = REPORTS_DIR / "cross_validation_review.json"
PUBLISHED_DATA = {
    "ds": MATH_BANK_DIR / "data-ds.json",
    "coa": MATH_BANK_DIR / "data-coa.json",
    "net": MATH_BANK_DIR / "data-net.json",
    "os": MATH_BANK_DIR / "data-os.json",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def published_hash(course_key: str) -> str:
    """Hash the file consumed by the viewer and platform quality gate."""
    return sha256_file(PUBLISHED_DATA[course_key])


def answer_number(qid: Any) -> str | None:
    match = re.search(r"(\d+)", str(qid or ""))
    return match.group(1).zfill(2) if match else None


def answer_for_split_question(qid: Any, source_answer: str | None) -> str | None:
    """X06_1…X06_4 对应原书同一题答案串 AAAC 的第 1…4 位。"""
    if not source_answer:
        return None
    match = re.search(r"_(\d+)$", str(qid or ""))
    # 有些 _2 是 OCR 拆出的题干续段，仍对应原题的单个答案，并非多空答案串。
    if not match or len(source_answer) == 1:
        return source_answer
    index = int(match.group(1)) - 1
    return source_answer[index] if 0 <= index < len(source_answer) else None


def normalize_answer(value: Any) -> str | None:
    letters = re.findall(r"[A-G]", str(value or "").upper())
    return "".join(letters) or None


def classify_evidence(
    current: str | None, raw_ocr: str | None, fresh_ocr: str | None
) -> tuple[str, bool]:
    """返回 (状态, 是否隔离)。fresh OCR 是自动放行的必要证据。"""
    if not current:
        return "missing_current", True
    if fresh_ocr == current:
        return "verified", False
    if fresh_ocr is None:
        return "fresh_ocr_missing", True
    if raw_ocr == fresh_ocr and fresh_ocr != current:
        return "source_consensus_conflict", True
    return "evidence_conflict", True


def question_uid(course_key: str, chapter: str, qid: str) -> str:
    return f"408:cs408-{course_key}::{chapter}::{qid}"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def choice_groups(data: dict[str, Any]):
    groups: dict[tuple[str, tuple[int, ...]], list[tuple[str, dict[str, Any]]]] = (
        defaultdict(list)
    )
    for chapter in data.get("chapters", []):
        for q in chapter.get("questions", []):
            if q.get("type") != "选择题":
                continue
            key = (str(q.get("topic_title") or ""), tuple(q.get("a_pages") or []))
            groups[key].append((chapter.get("name") or "", q))
    return groups


def answer_pages_from_raw(course_key: str, groups) -> list[int]:
    """只重跑真正含选择题答案头的页面，避免 OCR 大量正文页。"""
    raw_dir = PROJECT_ROOT / "data" / "ocr" / course_key
    pages: set[int] = set()
    candidate_pages = {p for _, a_pages in groups for p in a_pages}
    for page in sorted(candidate_pages):
        path = raw_dir / f"page_{page:03d}.json"
        if not path.is_file():
            continue
        if parse_answer_page(load_json(path))["choice"]:
            pages.add(page)
    return sorted(pages)


def ocr_engine_version() -> str:
    """Identify the installed RapidOCR package; missing package is not cached."""
    try:
        import rapidocr_onnxruntime
    except ImportError:
        return "missing"
    return str(getattr(rapidocr_onnxruntime, "__version__", "unknown"))


def ocr_cache_valid(path: Path, image_path: Path, *, engine_version: str) -> bool:
    """Reuse a page cache only when image hash, engine, and protocol match."""
    if not path.is_file() or not image_path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("protocol") == OCR_CACHE_PROTOCOL
        and payload.get("engine_version") == engine_version
        and payload.get("image_sha256") == sha256_file(image_path)
    )


def run_fresh_ocr(course, pages: list[int], *, force: bool = False) -> str:
    cache_dir = CACHE_ROOT / course.key
    cache_dir.mkdir(parents=True, exist_ok=True)
    engine_version = ocr_engine_version()
    todo = []
    for page in pages:
        image_path = course.pdf_images_dir / f"page_{page:03d}.png"
        cache_path = cache_dir / f"page_{page:03d}.json"
        if force or not ocr_cache_valid(
            cache_path, image_path, engine_version=engine_version
        ):
            todo.append(page)
    if not todo:
        return "cached"

    tools_dir = REPO_ROOT / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from ocr_gpu import create_rapid_ocr

    engine, backend = create_rapid_ocr()
    print(
        f"[{course.key}] fresh OCR: {len(todo)}/{len(pages)} 页，backend={backend}",
        flush=True,
    )
    for index, page in enumerate(todo, 1):
        image_path = course.pdf_images_dir / f"page_{page:03d}.png"
        if not image_path.is_file():
            print(f"[{course.key}] 缺失页面图片: {image_path}", flush=True)
            continue
        result, _ = engine(str(image_path))
        blocks = []
        for box, text, score in result or []:
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            blocks.append(
                {
                    "text": text,
                    "score": round(float(score), 4),
                    "x0": min(xs),
                    "y0": min(ys),
                    "x1": max(xs),
                    "y1": max(ys),
                }
            )
        write_json_atomic(
            cache_dir / f"page_{page:03d}.json",
            {
                "page": page,
                "backend": backend,
                "protocol": OCR_CACHE_PROTOCOL,
                "engine_version": engine_version,
                "image_sha256": sha256_file(image_path),
                "blocks": blocks,
            },
            indent=2,
            ensure_ascii=False,
        )
        if index % 10 == 0 or index == len(todo):
            print(f"[{course.key}] fresh OCR {index}/{len(todo)}", flush=True)
    return backend


def parse_group_answers(page_dir: Path, pages: tuple[int, ...]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for page in pages:
        path = page_dir / f"page_{page:03d}.json"
        if not path.is_file():
            continue
        parsed = parse_answer_page(load_json(path))["choice"]
        for qid, answer in parsed.items():
            normalized = normalize_answer(answer.get("choice"))
            if normalized:
                answers.setdefault(qid, normalized)
    return answers


def validate_course(course, *, fresh_ocr: bool, force: bool = False) -> dict[str, Any]:
    source_path = Path(course.out_json)
    data = load_json(source_path)
    groups = choice_groups(data)
    answer_pages = answer_pages_from_raw(course.key, groups)
    backend = "not-run"
    if fresh_ocr:
        backend = run_fresh_ocr(course, answer_pages, force=force)

    raw_dir = PROJECT_ROOT / "data" / "ocr" / course.key
    fresh_dir = CACHE_ROOT / course.key
    records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for (topic, pages), questions in groups.items():
        raw_answers = parse_group_answers(raw_dir, pages)
        fresh_answers = parse_group_answers(fresh_dir, pages)
        for chapter, q in questions:
            number = answer_number(q.get("id"))
            current = normalize_answer((q.get("answer") or {}).get("choice"))
            raw = answer_for_split_question(
                q.get("id"), raw_answers.get(number) if number else None
            )
            fresh = answer_for_split_question(
                q.get("id"), fresh_answers.get(number) if number else None
            )
            status, hold = classify_evidence(current, raw, fresh)
            status_counts[status] += 1
            records.append(
                {
                    "course": course.name,
                    "course_key": course.key,
                    "chapter": chapter,
                    "topic_title": topic,
                    "id": q.get("id"),
                    "page": q.get("page"),
                    "source_uid": question_uid(
                        course.key, chapter, str(q.get("id") or "")
                    ),
                    "current": current,
                    "raw_ocr": raw,
                    "fresh_ocr": fresh,
                    "status": status,
                    "hold": hold,
                    "content_preview": (q.get("content") or "")[:120],
                }
            )

    return {
        "course": course.name,
        "course_key": course.key,
        "source_path": str(source_path),
        "source_sha256": sha256_file(source_path),
        "question_count": len(records),
        "answer_page_count": len(answer_pages),
        "fresh_ocr_backend": backend,
        "status_counts": dict(status_counts),
        "verified": sum(1 for r in records if not r["hold"]),
        "held": sum(1 for r in records if r["hold"]),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fresh-ocr", action="store_true", help="对答案页重新运行 GPU OCR"
    )
    parser.add_argument("--force", action="store_true", help="忽略 fresh OCR 缓存")
    parser.add_argument("--course", action="append", choices=[c.key for c in COURSES])
    args = parser.parse_args()

    # --course 只限制本次重新 OCR 的科目；最终报告始终覆盖全库，避免部分运行
    # 意外覆盖 quality-hold.json 后放行其他科目的未核验题。
    fresh_courses = set(args.course or [c.key for c in COURSES])
    results = [
        validate_course(
            c,
            fresh_ocr=args.fresh_ocr and c.key in fresh_courses,
            force=args.force,
        )
        for c in COURSES
    ]
    records = [record for result in results for record in result["records"]]
    held = [record for record in records if record["hold"]]
    summary = {
        "total_choice_questions": len(records),
        "verified": len(records) - len(held),
        "held": len(held),
        "verification_rate": round((len(records) - len(held)) / len(records), 6)
        if records
        else 0,
        "fresh_ocr_requested": args.fresh_ocr,
    }
    report = {
        "schema_version": 1,
        "summary": summary,
        "courses": [
            {key: value for key, value in result.items() if key != "records"}
            for result in results
        ],
        "records": records,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT_PATH, report, indent=2, ensure_ascii=False)
    write_json_atomic(REVIEW_PATH, held, indent=2, ensure_ascii=False)
    # 保留视觉门禁在 merge 前写入的题目级隔离项；本脚本只追加答案冲突，
    # 不能因为重新生成 cross-validation 报告而放行视觉冲突题。
    existing_hold: dict[str, Any] = {}
    if HOLD_PATH.is_file():
        try:
            raw_hold = json.loads(HOLD_PATH.read_text(encoding="utf-8"))
            if isinstance(raw_hold, dict):
                existing_hold = raw_hold
        except (OSError, json.JSONDecodeError):
            existing_hold = {}
    merged_uids = sorted(
        {str(uid) for uid in existing_hold.get("source_uids", []) if str(uid).strip()}
        | {record["source_uid"] for record in held}
    )
    hold_payload = {
        "schema_version": 1,
        "source_hashes": {
            result["course_key"]: published_hash(result["course_key"])
            for result in results
        },
        "source_uids": merged_uids,
        "summary": summary,
    }
    for key in ("vision_reason", "vision_records"):
        if key in existing_hold:
            hold_payload[key] = existing_hold[key]
    write_json_atomic(HOLD_PATH, hold_payload, indent=2, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告: {REPORT_PATH}")
    print(f"复核清单: {REVIEW_PATH}")
    print(f"平台隔离清单: {HOLD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
