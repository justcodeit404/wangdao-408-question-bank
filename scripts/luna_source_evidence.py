#!/usr/bin/env python3
"""Generate an offline source-evidence packet for the Luna review pipeline.

The packet is deliberately conservative.  A regular choice question is marked
as source-verified only when its published answer, the original OCR answer and
the independently generated fresh OCR answer normalize to the same value.
Questions with a medium-or-higher risk tier are never auto-verified; they are
returned as ``visual_pending`` for a visual pass instead.

This module does not call a model or an HTTP API.  When fresh OCR is requested,
it delegates to :func:`cross_validate_answers.run_fresh_ocr`, which in turn
loads the repository's ``tools/ocr_gpu.py`` entry point.  ``dry_run`` and
``cache_only`` never invoke the OCR runner and never write a packet.
"""

from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable, Iterable, Mapping, Sequence

from config import COURSE_BY_KEY, COURSES, MATH_BANK_DIR
from cross_validate_answers import (
    CACHE_ROOT,
    answer_for_split_question,
    answer_number,
    normalize_answer,
    parse_group_answers,
    run_fresh_ocr,
)
from luna_audit_queue import iter_questions
from utils import write_json_atomic


PROTOCOL = "luna-review-v1"
DEFAULT_PASS_ID = "source-ocr"
OCR_CONFIDENCE = 0.99
CHOICE_MARKER = "选择"
QUESTION_MARKER_RE = re.compile(r"^\s*(\d{1,3})\s*[.．。、:：)]")
ANSWER_HEADING_RE = re.compile(r"答案\s*(与|及)?\s*解析")
# Whitespace is removed by ``normalize_source_text``.  Do not require a
# word-boundary here: OCR commonly emits ``A.1B.2C.3`` for a two-column
# option row, where the next label is directly adjacent to the prior value.
OPTION_LABEL_RE = re.compile(r"([a-g])\s*[.．。、:：)]")
# These are deliberately limited to visible mathematical/program operators.
# Digits and operators are compared in order, so a crop cannot pass after
# silently losing a numeric literal or changing an expression.
OPERATOR_TRANSLATIONS = str.maketrans(
    {
        "−": "-",
        "–": "-",
        "—": "-",
        "﹣": "-",
        "／": "/",
        "÷": "/",
        "×": "*",
        "·": "*",
        "＋": "+",
        "＝": "=",
    }
)
OPERATOR_RE = re.compile(r"[+\-*/=<>≤≥%~^|&→←]")
NUMBER_RE = re.compile(r"\d+(?:[.]\d+)?")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _choice(value: Any) -> str | None:
    normalized = normalize_answer(value)
    return normalized or None


def normalize_source_text(value: Any) -> str:
    """Normalize OCR/published text without inventing or dropping content."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(normalized.split()).translate(OPERATOR_TRANSLATIONS)


def _question_fields(question: Mapping[str, Any]) -> dict[str, Any]:
    options = (
        question.get("options") if isinstance(question.get("options"), Mapping) else {}
    )
    return {
        "content": normalize_source_text(question.get("content")),
        "options": {
            str(key).upper(): normalize_source_text(value)
            for key, value in sorted(options.items(), key=lambda pair: str(pair[0]))
            if normalize_source_text(value)
        },
    }


def _ocr_text(directory: Path, pages: Sequence[int]) -> str:
    """Read question-page OCR blocks in deterministic y/x order."""
    blocks: list[tuple[float, float, str]] = []
    for page in pages:
        path = directory / f"page_{int(page):03d}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        for block in payload.get("blocks", []) if isinstance(payload, Mapping) else []:
            if not isinstance(block, Mapping) or not _text(block.get("text")):
                continue
            try:
                y = float(block.get("y0") or 0)
                x = float(block.get("x0") or 0)
            except (TypeError, ValueError):
                y, x = 0.0, 0.0
            blocks.append((y, x, _text(block.get("text"))))
    blocks.sort(key=lambda item: (item[0], item[1]))
    return normalize_source_text(" ".join(item[2] for item in blocks))


@lru_cache(maxsize=64)
def _read_ocr_blocks(
    directory: Path, pages: tuple[int, ...]
) -> tuple[dict[str, Any], ...]:
    """Load OCR blocks with page boundaries retained for question cropping."""
    blocks: list[dict[str, Any]] = []
    for page in pages:
        path = directory / f"page_{int(page):03d}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        page_blocks = payload.get("blocks", []) if isinstance(payload, Mapping) else []
        indexed: list[tuple[float, float, int, Mapping[str, Any]]] = []
        for index, block in enumerate(page_blocks):
            if not isinstance(block, Mapping) or not _text(block.get("text")):
                continue
            try:
                y = float(block.get("y0") or 0)
                x = float(block.get("x0") or 0)
            except (TypeError, ValueError):
                y, x = 0.0, 0.0
            indexed.append((y, x, index, block))
        indexed.sort(key=lambda item: (item[0], item[1], item[2]))
        for y, x, index, block in indexed:
            blocks.append(
                {
                    "page": int(page),
                    "index": index,
                    "y0": y,
                    "x0": x,
                    "text": _text(block.get("text")),
                }
            )
    return tuple(blocks)


def _question_crop(
    directory: Path, pages: Sequence[int], question_number: str | None
) -> dict[str, Any]:
    """Return only one question's OCR window, never the whole source pages.

    The source JSON often assigns all pages in a question/answer group to each
    question.  A page-wide substring check therefore mixes adjacent questions
    and diagrams.  A numeric question marker is a hard boundary: start at the
    requested marker and stop before the next marker or an answer heading.
    Missing markers intentionally produce an untrusted crop; callers must not
    auto-verify it.
    """
    blocks = _read_ocr_blocks(directory, tuple(int(page) for page in pages))
    target = int(question_number) if str(question_number or "").isdigit() else None
    start: int | None = None
    answer_heading: int | None = None
    for index, block in enumerate(blocks):
        text = _text(block.get("text"))
        if ANSWER_HEADING_RE.search(text):
            answer_heading = index if answer_heading is None else answer_heading
        marker = QUESTION_MARKER_RE.match(text)
        if target is not None and marker and int(marker.group(1)) == target:
            # Prefer the first target marker before the answer section.  A
            # second marker after the answer heading is the answer key.
            if answer_heading is None or index < answer_heading:
                start = index
                break
    if start is None:
        return {"text": "", "anchor_found": False, "blocks": 0, "pages": []}

    end = len(blocks)
    for index in range(start + 1, len(blocks)):
        text = _text(blocks[index].get("text"))
        if ANSWER_HEADING_RE.search(text):
            end = index
            break
        marker = QUESTION_MARKER_RE.match(text)
        if marker:
            end = index
            break
    cropped = blocks[start:end]
    return {
        "text": normalize_source_text(
            " ".join(str(block["text"]) for block in cropped)
        ),
        "anchor_found": True,
        "blocks": len(cropped),
        "pages": sorted({int(block["page"]) for block in cropped}),
    }


def _critical_tokens(value: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract ordered numeric/operator tokens that fuzzy text may not drop."""
    normalized = normalize_source_text(value)
    return tuple(NUMBER_RE.findall(normalized)), tuple(OPERATOR_RE.findall(normalized))


def _strict_or_near_match(
    expected: str, actual: str, *, minimum_ratio: float = 0.96
) -> bool:
    if not expected or not actual:
        return False
    # The crop includes the question number (e.g. ``01.``) before the stem;
    # remove only that trusted marker before enforcing token parity.  Extra
    # numbers/operators from a neighboring block must never be ignored.
    marker = QUESTION_MARKER_RE.match(actual)
    comparable = actual[marker.end() :] if marker else actual
    if _critical_tokens(expected) != _critical_tokens(comparable):
        return False
    if expected in comparable:
        return True
    # Fallback is intentionally narrow.  It tolerates one or two OCR glyph
    # substitutions while retaining exact number/operator sequences.
    return SequenceMatcher(None, expected, comparable).ratio() >= minimum_ratio


def _option_sections(stem_and_options: str) -> tuple[list[str], dict[str, str]]:
    matches = list(OPTION_LABEL_RE.finditer(stem_and_options))
    labels = [match.group(1).upper() for match in matches]
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(stem_and_options)
        )
        key = match.group(1).upper()
        # Keep first occurrence only; duplicate labels indicate a contaminated
        # crop and are rejected by the exact label-count check below.
        sections[key] = stem_and_options[match.end() : end]
    return labels, sections


def _field_matches(
    question: Mapping[str, Any], ocr_text: str, *, anchor_found: bool = True
) -> dict[str, Any]:
    fields = _question_fields(question)
    stem = fields["content"]
    labels, sections = _option_sections(ocr_text)
    first_option = min(
        (match.start() for match in OPTION_LABEL_RE.finditer(ocr_text)),
        default=len(ocr_text),
    )
    stem_text = ocr_text[:first_option]
    content_match = bool(anchor_found and _strict_or_near_match(stem, stem_text))
    options = fields["options"]
    expected_labels = list(options)
    # Exact label cardinality prevents a neighboring question's options from
    # satisfying a partial mapping, while preserving A/B/C/D/E distinctions.
    labels_match = bool(options) and sorted(labels) == sorted(expected_labels)
    option_matches = {}
    for key, value in options.items():
        section = sections.get(key, "")
        option_matches[key] = bool(
            labels_match and _strict_or_near_match(value, section)
        )
    return {
        "content": content_match,
        "options": option_matches,
        "all_options": bool(options) and labels_match and all(option_matches.values()),
        "anchor_found": anchor_found,
        "labels": labels,
        "labels_match": labels_match,
        "published_fields": fields,
    }


def _choice_for_row(row: Mapping[str, Any], answers: Mapping[str, str]) -> str | None:
    question = row.get("question") if isinstance(row.get("question"), Mapping) else {}
    number = answer_number(question.get("id"))
    if number is None:
        return None
    return _choice(answer_for_split_question(question.get("id"), answers.get(number)))


def _published_choice(row: Mapping[str, Any]) -> str | None:
    question = row.get("question") if isinstance(row.get("question"), Mapping) else {}
    answer = (
        question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    )
    return _choice(answer.get("choice"))


def _raw_ocr_dir(course_key: str, root: Path) -> Path:
    """Resolve raw OCR for both the real bank and small test fixtures."""
    candidates = (
        root / "data" / "ocr" / course_key,
        root / "ocr" / course_key,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    course = COURSE_BY_KEY.get(course_key)
    if course is None:
        raise ValueError(f"unknown course: {course_key}")
    return course.ocr_dir


def _choice_rows(root: Path, courses: Iterable[str]) -> list[dict[str, Any]]:
    """All published rows, including 解答题. Name kept for call-site compatibility."""
    return iter_questions(root, courses, include_untracked=True)


def _pages(rows: Sequence[Mapping[str, Any]], course_key: str) -> list[int]:
    result: set[int] = set()
    for row in rows:
        if row.get("course") != course_key:
            continue
        question = (
            row.get("question") if isinstance(row.get("question"), Mapping) else {}
        )
        for page in question.get("a_pages") or []:
            try:
                if int(page) > 0:
                    result.add(int(page))
            except (TypeError, ValueError):
                continue
    return sorted(result)


def _question_pages(rows: Sequence[Mapping[str, Any]], course_key: str) -> list[int]:
    """Return source pages needed for question-field evidence.

    Fresh OCR used to run only on answer pages, while field matching read
    ``q_pages``.  That made every fresh field check empty and inflated
    ``visual_pending`` even when the answer triad agreed.
    """
    result: set[int] = set()
    for row in rows:
        if row.get("course") != course_key:
            continue
        question = (
            row.get("question") if isinstance(row.get("question"), Mapping) else {}
        )
        for page in question.get("q_pages") or []:
            try:
                if int(page) > 0:
                    result.add(int(page))
            except (TypeError, ValueError):
                continue
    return sorted(result)


def _load_answers(directory: Path, pages: Sequence[int]) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return parse_group_answers(directory, tuple(pages))


def _pending_reasons(
    row: Mapping[str, Any],
    *,
    published: str | None,
    raw: str | None,
    fresh: str | None,
    raw_fields: Mapping[str, Any],
    fresh_fields: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not _text(row.get("source_hash")):
        reasons.append("source_hash_missing")
    if not published:
        reasons.append("published_answer_missing")
    if not raw:
        reasons.append("raw_ocr_missing")
    elif published and raw != published:
        reasons.append("raw_ocr_mismatch")
    if not fresh:
        reasons.append("fresh_ocr_missing")
    elif published and fresh != published:
        reasons.append("fresh_ocr_mismatch")
    if published and raw and fresh and raw != fresh:
        reasons.append("ocr_disagreement")
    for label, fields in (("raw", raw_fields), ("fresh", fresh_fields)):
        if not fields.get("anchor_found"):
            reasons.append(f"{label}_question_anchor_missing")
        if not fields.get("content"):
            reasons.append(f"{label}_content_mismatch")
        if not fields.get("all_options"):
            reasons.append(f"{label}_options_mismatch")
    return reasons or ["source_evidence_incomplete"]


def _evidence_item(
    row: Mapping[str, Any],
    *,
    protocol: str,
    pass_id: str,
    published: str | None,
    raw: str | None,
    fresh: str | None,
    raw_fields: Mapping[str, Any],
    fresh_fields: Mapping[str, Any],
) -> dict[str, Any]:
    tier = _text(row.get("risk_tier")) or "high"
    score = int(row.get("risk_score") or 0)
    risk_reasons = [str(value) for value in row.get("risk_reasons") or [] if str(value)]
    answer_matches = bool(published and published == raw == fresh)
    fields_match = bool(
        raw_fields.get("anchor_found")
        and raw_fields.get("content")
        and raw_fields.get("all_options")
        and fresh_fields.get("anchor_found")
        and fresh_fields.get("content")
        and fresh_fields.get("all_options")
    )
    matches = answer_matches and fields_match
    # 图/代码/公式仍走视觉；三方题干+选项+答案已一致时，旧 hold 不再挡住 OCR 原书认证。
    visual_risk = any(
        reason in {"visual_evidence", "empty_stem", "missing_options"}
        for reason in risk_reasons
    ) or bool(
        (row.get("question") or {}).get("has_image")
        or (row.get("question") or {}).get("image_ref")
    )
    passed = matches and bool(_text(row.get("source_hash"))) and not visual_risk
    if passed:
        method = "ocr"
        source_verified = True
        confidence = OCR_CONFIDENCE
        reason_codes: list[str] = []
    else:
        method = "visual_pending"
        source_verified = False
        confidence = 0.0
        reason_codes = _pending_reasons(
            row,
            published=published,
            raw=raw,
            fresh=fresh,
            raw_fields=raw_fields,
            fresh_fields=fresh_fields,
        )
        if visual_risk or tier != "low":
            reason_codes.insert(0, f"risk_{tier}")

    item: dict[str, Any] = {
        "protocol": protocol,
        "pass_id": pass_id,
        "source_uid": _text(row.get("source_uid")),
        "source_hash": _text(row.get("source_hash")),
        "method": method,
        "source_verified": source_verified,
        "confidence": confidence,
        "risk_tier": tier,
        "risk_score": score,
        "risk_reasons": risk_reasons,
        "published_choice": published,
        "raw_ocr_choice": raw,
        "fresh_ocr_choice": fresh,
        "answer_match": answer_matches,
        "raw_fields_match": bool(
            raw_fields.get("anchor_found")
            and raw_fields.get("content")
            and raw_fields.get("all_options")
        ),
        "fresh_fields_match": bool(
            fresh_fields.get("anchor_found")
            and fresh_fields.get("content")
            and fresh_fields.get("all_options")
        ),
        "triad": matches,
        "published_match": matches,
    }
    if reason_codes:
        item["reason_codes"] = sorted(set(reason_codes))
    item["item_hash"] = _sha(
        {key: value for key, value in item.items() if key != "item_hash"}
    )
    return item


def build_source_packet(
    items: Sequence[Mapping[str, Any]],
    *,
    pass_id: str = DEFAULT_PASS_ID,
    protocol: str = PROTOCOL,
) -> dict[str, Any]:
    """Build a stable ingest-compatible source packet from evidence items."""
    if not _text(pass_id):
        raise ValueError("pass_id must not be empty")
    if not _text(protocol):
        raise ValueError("protocol must not be empty")
    normalized = [dict(item) for item in items]
    normalized.sort(key=lambda item: _text(item.get("source_uid")))
    packet: dict[str, Any] = {
        "schema_version": 1,
        "protocol": protocol,
        "packet_type": "source-evidence",
        "pass_id": pass_id,
        "items": normalized,
    }
    packet["packet_hash"] = _sha(packet)
    return packet


def generate_source_evidence(
    *,
    root: Path = MATH_BANK_DIR,
    courses: Iterable[str] | None = None,
    pass_id: str = DEFAULT_PASS_ID,
    protocol: str = PROTOCOL,
    cache_root: Path = CACHE_ROOT,
    fresh_ocr: bool = True,
    cache_only: bool = False,
    force: bool = False,
    dry_run: bool = False,
    output: Path | None = None,
    ocr_runner: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Generate a packet and summary without touching tracked bank data.

    ``ocr_runner`` is injectable for tests; production defaults to the
    imported ``run_fresh_ocr`` implementation, whose GPU setup is centralized
    in ``tools/ocr_gpu.py``.  No runner is invoked in ``dry_run`` or
    ``cache_only`` mode.
    """
    root = Path(root)
    cache_root = Path(cache_root)
    if courses is None:
        courses = [course.key for course in COURSES]
    selected_courses = tuple(sorted(set(str(course) for course in courses)))
    unknown = sorted(set(selected_courses) - set(COURSE_BY_KEY))
    if unknown:
        raise ValueError(f"unknown course: {unknown[0]}")
    rows = _choice_rows(root, selected_courses)
    by_course: dict[str, list[dict[str, Any]]] = {
        course: [] for course in selected_courses
    }
    for row in rows:
        by_course.setdefault(str(row.get("course")), []).append(row)

    runners: list[dict[str, Any]] = []
    runner = ocr_runner or run_fresh_ocr
    if fresh_ocr and not cache_only and not dry_run:
        for course_key in selected_courses:
            answer_pages = _pages(by_course.get(course_key, []), course_key)
            question_pages = _question_pages(by_course.get(course_key, []), course_key)
            pages = sorted(set(answer_pages) | set(question_pages))
            if not pages:
                continue
            course = COURSE_BY_KEY[course_key]
            backend = runner(course, pages, force=force)
            runners.append({"course": course_key, "pages": pages, "backend": backend})

    answers: dict[str, dict[str, str]] = {}
    for course_key in selected_courses:
        pages = _pages(by_course.get(course_key, []), course_key)
        answers[course_key] = {
            "raw": _load_answers(_raw_ocr_dir(course_key, root), pages),
            "fresh": _load_answers(cache_root / course_key, pages),
        }

    evidence_items: list[dict[str, Any]] = []
    for row in rows:
        course_key = str(row.get("course"))
        current = answers.get(course_key, {"raw": {}, "fresh": {}})
        question = (
            row.get("question") if isinstance(row.get("question"), Mapping) else {}
        )
        q_pages = []
        for page in question.get("q_pages") or []:
            try:
                if int(page) > 0:
                    q_pages.append(int(page))
            except (TypeError, ValueError):
                continue
        raw_dir = _raw_ocr_dir(course_key, root)
        fresh_dir = cache_root / course_key
        question_number = answer_number(question.get("id"))
        raw_crop = _question_crop(raw_dir, q_pages, question_number)
        fresh_crop = _question_crop(fresh_dir, q_pages, question_number)
        evidence_items.append(
            _evidence_item(
                row,
                protocol=protocol,
                pass_id=pass_id,
                published=_published_choice(row),
                raw=_choice_for_row(row, current["raw"]),
                fresh=_choice_for_row(row, current["fresh"]),
                raw_fields=_field_matches(
                    question,
                    raw_crop["text"],
                    anchor_found=bool(raw_crop["anchor_found"]),
                ),
                fresh_fields=_field_matches(
                    question,
                    fresh_crop["text"],
                    anchor_found=bool(fresh_crop["anchor_found"]),
                ),
            )
        )
    packet = build_source_packet(evidence_items, pass_id=pass_id, protocol=protocol)
    if output is not None and not dry_run:
        write_json_atomic(Path(output), packet, indent=2, ensure_ascii=False)
    counts = Counter(str(item["method"]) for item in evidence_items)
    summary = {
        "total": len(evidence_items),
        "ocr_verified": counts.get("ocr", 0),
        "visual_pending": counts.get("visual_pending", 0),
        "courses": list(selected_courses),
        "fresh_ocr_runs": runners,
        "dry_run": dry_run,
        "cache_only": cache_only,
        "output": str(output) if output is not None and not dry_run else None,
    }
    return {"packet": packet, "summary": summary}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=MATH_BANK_DIR)
    parser.add_argument(
        "--course", action="append", choices=[course.key for course in COURSES]
    )
    parser.add_argument("--pass-id", default=DEFAULT_PASS_ID)
    parser.add_argument("--protocol", default=PROTOCOL)
    parser.add_argument("--cache-root", type=Path, default=CACHE_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-fresh-ocr", action="store_true")
    parser.add_argument(
        "--cache-only", action="store_true", help="只读取已有 fresh OCR 缓存"
    )
    parser.add_argument(
        "--force", action="store_true", help="忽略 fresh OCR 缓存并重跑 GPU OCR"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="不运行 OCR、不写结果包，只打印摘要"
    )
    args = parser.parse_args(argv)
    result = generate_source_evidence(
        root=args.root,
        courses=args.course or [course.key for course in COURSES],
        pass_id=args.pass_id,
        protocol=args.protocol,
        cache_root=args.cache_root,
        fresh_ocr=not args.no_fresh_ocr,
        cache_only=args.cache_only,
        force=args.force,
        dry_run=args.dry_run,
        output=args.output,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if args.dry_run:
        print(json.dumps(result["packet"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
