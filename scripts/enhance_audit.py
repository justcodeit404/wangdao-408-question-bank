#!/usr/bin/env python3
"""408 题库发布门禁：审计源 JSON、图片资源及平台实际读取的数据。"""

from __future__ import annotations

import json
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from config import COURSES, MATH_BANK_DIR, REPORTS_DIR
from parse_patterns import has_real_image_ref

sys.stdout.reconfigure(encoding="utf-8")

OPTION_LETTERS = set("ABCDEF")
CRITICAL_ISSUES = {
    "declared_total_mismatch",
    "empty_content",
    "no_answer",
    "missing_option_letters",
    "empty_option",
    "duplicate_option",
    "answer_outside_options",
    "duplicate_question_id",
    "missing_image_file",
    "published_missing",
    "published_content_mismatch",
    "suspected_misclassified_choice",
    "choice_ocr_noise",
    "cross_validation_manifest_missing",
    "cross_validation_stale",
    "seq_gap",
    "trunc_stem_scan",
    "regression_mismatch",
    "regression_target_missing",
    "vision_verification_manifest_missing",
    "vision_verification_unverified",
    "vision_verification_stale",
}

REGRESSIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "quality" / "quality_regressions.json"


def _questions(data: dict[str, Any]):
    for chapter in data.get("chapters", []):
        chapter_name = chapter.get("name") or chapter.get("topic_title") or "未知章节"
        for question in chapter.get("questions", []):
            yield chapter_name, question


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _answer_obj(question: dict[str, Any]) -> dict[str, Any]:
    answer = question.get("answer")
    return answer if isinstance(answer, dict) else {}


def _image_path(question: dict[str, Any]) -> str:
    ref = question.get("image_ref")
    if isinstance(ref, dict):
        return str(ref.get("cropped") or "").strip()
    return str(ref or "").strip()


def _question_signature(data: dict[str, Any]) -> list[tuple[Any, ...]]:
    """只比较平台会消费的题目内容；忽略 merge_courses 注入的章节 course 字段。"""
    return [
        (
            chapter,
            q.get("id"),
            q.get("type"),
            q.get("content"),
            q.get("options"),
            q.get("answer"),
            q.get("image_ref"),
        )
        for chapter, q in _questions(data)
    ]


def _load_regressions() -> list[dict[str, Any]]:
    if not REGRESSIONS_PATH.is_file():
        return []
    try:
        raw = json.loads(REGRESSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return raw if isinstance(raw, list) else (raw.get("items") or []) if isinstance(raw, dict) else []


def _regression_matches(course, chapter: str, q: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, str]:
    """只比较回归样例声明的字段，避免把无关 OCR 排版变化锁死。"""
    if "content" in expected and q.get("content") != expected["content"]:
        return False, "content"
    if "options" in expected:
        actual = q.get("options") if isinstance(q.get("options"), dict) else {}
        for key, value in (expected["options"] or {}).items():
            if actual.get(key) != value:
                return False, f"options.{key}"
    answer = q.get("answer") if isinstance(q.get("answer"), dict) else {}
    exp_answer = expected.get("answer") or {}
    if "choice" in exp_answer and answer.get("choice") != exp_answer["choice"]:
        return False, "answer.choice"
    if "explanation" in exp_answer and answer.get("explanation") != exp_answer["explanation"]:
        return False, "answer.explanation"
    if "explanation_contains" in exp_answer and str(exp_answer["explanation_contains"]) not in str(answer.get("explanation") or ""):
        return False, "answer.explanation_contains"
    if "image_ref" in expected:
        actual_ref = q.get("image_ref")
        actual_ref = actual_ref.get("cropped") if isinstance(actual_ref, dict) else actual_ref
        if actual_ref != expected["image_ref"]:
            return False, "image_ref"
    return True, ""


def audit_file(course) -> dict[str, Any]:
    path = Path(course.out_json)
    pub = MATH_BANK_DIR / f"data-{course.key}.json"
    # 门禁以平台实际读取的 published 为准；out_json 仅作对照
    primary = pub if pub.is_file() else path
    data = json.loads(primary.read_text(encoding="utf-8"))
    rows = list(_questions(data))
    issues: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[tuple[str, str]] = set()
    ordered_choice_count = 0
    image_count = 0

    # 发布门禁必须由本次视觉抽检 manifest 锁定实际读取的 data-*.json 哈希。
    verification_path = Path(__file__).resolve().parent.parent / "data" / "quality" / "quality-verification.json"
    if not verification_path.is_file():
        issues["vision_verification_manifest_missing"].append({"path": str(verification_path)})
    else:
        try:
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            status = str(verification.get("status") or "")
            expected = (verification.get("published_hashes") or {}).get(course.key)
            actual = _sha256(primary)
            if status != "published":
                issues["vision_verification_unverified"].append({"status": status})
            elif not expected or expected != actual:
                issues["vision_verification_stale"].append({"expected": expected, "actual": actual})
        except (OSError, json.JSONDecodeError, AttributeError):
            issues["vision_verification_manifest_missing"].append({"path": str(verification_path), "error": "invalid JSON"})

    # 已修复问题的回归样例：只校验声明过的字段，且必须能定位到发布题目。
    course_regressions = [
        r for r in _load_regressions()
        if str(r.get("source_uid") or "").startswith(f"408:cs408-{course.key}::")
    ]
    row_by_uid = {
        f"408:cs408-{course.key}::{chapter}::{q.get('id')}": (chapter, q)
        for chapter, q in rows
    }
    for regression in course_regressions:
        uid = str(regression.get("source_uid") or "")
        target = row_by_uid.get(uid)
        if not target:
            issues["regression_target_missing"].append({"source_uid": uid})
            continue
        expected = regression.get("expected") or {}
        ok, field = _regression_matches(course, target[0], target[1], expected)
        if not ok:
            issues["regression_mismatch"].append(
                {"source_uid": uid, "field": field, "expected": expected}
            )

    hold_path = MATH_BANK_DIR / "quality-hold.json"
    if not hold_path.is_file():
        issues["cross_validation_manifest_missing"].append({"path": str(hold_path)})
    else:
        try:
            hold = json.loads(hold_path.read_text(encoding="utf-8"))
            actual_hash = _sha256(primary)
            hashes = hold.get("source_hashes") or {}
            files = hold.get("files") or {}
            expected_hash = (
                hashes.get(course.key)
                or files.get(primary.name)
                or files.get(path.name)
            )
            if not expected_hash or expected_hash != actual_hash:
                issues["cross_validation_stale"].append(
                    {
                        "expected": expected_hash,
                        "actual": actual_hash,
                        "checked": str(primary),
                    }
                )
        except Exception as exc:
            issues["cross_validation_manifest_missing"].append(
                {"path": str(hold_path), "error": str(exc)}
            )

    held_uids: set[str] = set()
    if hold_path.is_file():
        try:
            held_uids = {
                str(uid)
                for uid in (
                    json.loads(hold_path.read_text(encoding="utf-8")).get("source_uids")
                    or []
                )
                if str(uid).strip()
            }
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            held_uids = set()

    def add(kind: str, chapter: str, q: dict[str, Any], **extra):
        qid = str(q.get("id") or "?")
        uid = f"408:cs408-{course.key}::{chapter}::{qid}"
        if kind in CRITICAL_ISSUES and uid in held_uids:
            issues["held_acknowledged"].append(
                {
                    "chapter": chapter,
                    "id": qid,
                    "type": q.get("type"),
                    "held_as": kind,
                }
            )
            return
        issues[kind].append(
            {
                "chapter": chapter,
                "id": q.get("id", "?"),
                "type": q.get("type"),
                "page": q.get("page"),
                "content_preview": (q.get("content") or "").strip()[:100],
                **extra,
            }
        )

    declared = int(data.get("total_questions") or 0)
    if declared != len(rows):
        issues["declared_total_mismatch"].append(
            {"declared": declared, "actual": len(rows)}
        )

    # 每章 X/A 题号连续性（子题 X06_1 不参与主序号空洞判定）
    chapter_nums: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for chapter, q in rows:
        qid = str(q.get("id") or "").strip()
        m = re.fullmatch(r"([XA])(\d+)$", qid)
        if m:
            chapter_nums[chapter][m.group(1)].append(int(m.group(2)))

    for chapter, by_prefix in chapter_nums.items():
        for prefix, nums in by_prefix.items():
            if len(nums) < 3:
                continue
            nums_u = sorted(set(nums))
            missing = sorted(set(range(min(nums_u), max(nums_u) + 1)) - set(nums_u))
            if missing:
                issues["seq_gap"].append(
                    {
                        "chapter": chapter,
                        "prefix": prefix,
                        "missing": missing,
                        "range": [min(nums_u), max(nums_u)],
                        "count": len(nums_u),
                    }
                )

    for chapter, q in rows:
        content = (q.get("content") or "").strip()
        answer = _answer_obj(q)
        qid = str(q.get("id") or "").strip()
        key = (chapter, qid)

        if not content:
            add("empty_content", chapter, q)
        if re.search(r"当扫描到时", content) and not re.search(
            r"当扫描到\s+\S+\s*时", content
        ):
            add("trunc_stem_scan", chapter, q)
        if not answer or not (answer.get("choice") or answer.get("explanation")):
            add("no_answer", chapter, q)
        if not qid or key in seen_ids:
            add("duplicate_question_id", chapter, q)
        seen_ids.add(key)

        if q.get("type") == "选择题":
            options = q.get("options") if isinstance(q.get("options"), dict) else {}
            keys = {str(k).strip().upper() for k in options}
            missing = sorted(set("ABCD") - keys)
            if missing:
                add("missing_option_letters", chapter, q, missing=missing)
            empty = sorted(
                k for k, value in options.items() if not str(value or "").strip()
            )
            if empty:
                add("empty_option", chapter, q, letters=empty)
            bodies = [
                str(value).strip()
                for value in options.values()
                if str(value or "").strip()
            ]
            if len(bodies) != len(set(bodies)):
                add("duplicate_option", chapter, q)

            choice = str(answer.get("choice") or "").strip().upper()
            answer_letters = [c for c in choice if c.isalpha()]
            if len(answer_letters) > 1:
                ordered_choice_count += 1
            invalid = sorted(
                {c for c in answer_letters if c not in keys or c not in OPTION_LETTERS}
            )
            if not choice or invalid:
                add(
                    "answer_outside_options", chapter, q, answer=choice, invalid=invalid
                )

            choice_text = "\n".join(
                [
                    content,
                    *[str(v or "") for v in options.values()],
                    str(answer.get("explanation") or ""),
                ]
            )
            if re.search(
                r"2027年.{0,25}考研复习指导|(?<![A-Za-z])(?:IIL|IIl)(?![A-Za-z])|é|[=:]{4,}",
                choice_text,
            ):
                add("choice_ocr_noise", chapter, q)
        elif (
            not q.get("options")
            and not q.get("sub_questions")
            and len(content) < 320
            and re.search(r"(?<![A-Za-z0-9_])[（(]\s*[）)]", content)
        ):
            add("suspected_misclassified_choice", chapter, q)

        image_path = _image_path(q)
        if image_path:
            image_count += 1
            if (
                ".." in Path(image_path).parts
                or not (MATH_BANK_DIR / image_path).is_file()
            ):
                add("missing_image_file", chapter, q, image_ref=image_path)
        elif has_real_image_ref(content):
            add("missing_image_file", chapter, q, image_ref="")

    published_path = MATH_BANK_DIR / f"data-{course.key}.json"
    if not published_path.is_file():
        issues["published_missing"].append({"path": str(published_path)})
    else:
        published = json.loads(published_path.read_text(encoding="utf-8"))
        if _question_signature(data) != _question_signature(published):
            issues["published_content_mismatch"].append(
                {
                    "source_questions": len(rows),
                    "published_questions": len(list(_questions(published))),
                }
            )

    issue_totals = {kind: len(items) for kind, items in issues.items()}
    return {
        "total": len(rows),
        "declared_total": declared,
        "chapters": len(data.get("chapters", [])),
        "ordered_choice_questions": ordered_choice_count,
        "image_questions": image_count,
        "issue_totals": issue_totals,
        "issues": {kind: items[:200] for kind, items in issues.items()},
        "critical_count": sum(
            count for kind, count in issue_totals.items() if kind in CRITICAL_ISSUES
        ),
    }


def build_report() -> dict[str, Any]:
    report: dict[str, Any] = {"courses": {}, "summary": {}}
    for course in COURSES:
        if not Path(course.out_json).exists():
            report["courses"][course.name] = {
                "critical_count": 1,
                "issues": {"source_missing": [{"path": str(course.out_json)}]},
                "issue_totals": {"source_missing": 1},
            }
            continue
        report["courses"][course.name] = audit_file(course)

    courses = list(report["courses"].values())
    report["summary"] = {
        "total_questions": sum(int(r.get("total") or 0) for r in courses),
        "ordered_choice_questions": sum(
            int(r.get("ordered_choice_questions") or 0) for r in courses
        ),
        "image_questions": sum(int(r.get("image_questions") or 0) for r in courses),
        "critical_count": sum(int(r.get("critical_count") or 0) for r in courses),
    }
    return report


def main() -> int:
    report = build_report()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "quality_report.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = report["summary"]
    print(f"质量报告已保存: {out_path}")
    print(f"总题数: {summary['total_questions']}")
    print(f"连续选项题: {summary['ordered_choice_questions']}")
    print(f"图片题: {summary['image_questions']}")
    print(f"阻断问题: {summary['critical_count']}")
    for name, result in report["courses"].items():
        print(f"  {name}: {result.get('critical_count', 0)} 个阻断问题")
        for kind, count in result.get("issue_totals", {}).items():
            if count:
                print(f"    {kind}: {count}")
    return 1 if summary["critical_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
