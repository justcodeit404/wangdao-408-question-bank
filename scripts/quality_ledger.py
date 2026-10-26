#!/usr/bin/env python3
"""408 题库质量 ledger。

ledger 是题库质量状态的唯一来源；quality-hold.json 和
quality-verification.json 只是给旧构建/平台使用的派生清单。这个模块故意不
调用模型，只负责稳定的 UID、内容哈希、状态迁移和清单一致性。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from config import COURSES, MATH_BANK_DIR, REPORTS_DIR
from luna_review_v2 import apply_v2_fields
from quality_hold import _choice_should_hold, source_uid
from utils import write_json_atomic, write_text_atomic

DATA_QUALITY_DIR = Path(__file__).resolve().parents[1] / "data" / "quality"
CURATED_DIR = Path(__file__).resolve().parents[1] / "data" / "zhenti"
# 全量 ledger（含本机证据路径）只落本地 data/quality，不进发布目录。
LEDGER_PATH = DATA_QUALITY_DIR / "quality-ledger.json"
# quality-verification 只是给旧构建/追溯用的派生清单，同样不发布。
VERIFICATION_PATH = DATA_QUALITY_DIR / "quality-verification.json"
# QA 页（window.__QUALITY_LEDGER__）用的本地脚本副本。
LEDGER_JS_PATH = DATA_QUALITY_DIR / "quality-ledger.js"
# 平台后端按 bank 路径读它，必须剥掉本机绝对路径。
PUBLISHED_LEDGER_PATH = MATH_BANK_DIR / "quality-ledger.json"
# 存量逐题哈希漂移基线：历史 normalize/repage 造成的已知漂移不阻断热更，
# 但新增漂移（不在基线内）必须阻断，避免警告长期失去意义。
DRIFT_BASELINE_PATH = DATA_QUALITY_DIR / "item-hash-drift-baseline.json"
HOLD_PATH = MATH_BANK_DIR / "quality-hold.json"
PAGE_REVIEW_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "quality" / "page_review_evidence.json"
)

TERMINAL_SOURCE = {"verified", "conflict"}
TERMINAL_ANSWER = {"verified", "conflict"}

# 改号 / 题型迁移登记：旧 UID → 现行 UID。
# 只登记「同一道题换了号」的已确认迁移，用来把 hold/certified、证据与逐页复核
# 记录搬到新 UID；删除或内容重写不要登记在这里。
RENAMED_UIDS: dict[str, str] = {
    "408:cs408-ds::绪论 · 算法和算法评价 · 解答题::A01_2": (
        "408:cs408-ds::绪论 · 算法和算法评价 · 解答题::A03"
    ),
    "408:cs408-net::网络层 · IPv4 · 选择题::X11_2": (
        "408:cs408-net::网络层 · IPv4 · 解答题::A11_2"
    ),
}


_LOCAL_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def strip_local_paths(obj: Any) -> Any:
    """发布副本剥掉本机绝对路径（隐私）；全量 ledger 保留在 data/quality。"""
    if isinstance(obj, dict):
        return {
            key: strip_local_paths(value)
            for key, value in obj.items()
            if not (key == "path" and isinstance(value, str) and _LOCAL_ABS_PATH_RE.match(value))
        }
    if isinstance(obj, list):
        return [strip_local_paths(value) for value in obj]
    return obj


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# 答案区原书截图行（gen_answer_crops.py 前置进 explanation）。截图只是同一解析的
# 另一种展示，不改变 OCR 文字的可信度，哈希与证据比对前先剥掉，避免台账全量掉 verified。
_ANSWER_CROP_LINE_RE = re.compile(
    r"^(?:答案图片|解析图片|题图|答图)\s*[：:]\s*answer_crops/\S+\s*$", re.IGNORECASE
)


def stable_explanation(value: Any) -> str:
    """剥掉 explanation 里的 answer_crops 图片行，返回参与哈希/比对的稳定文本。"""
    lines = str(value or "").splitlines()
    return "\n".join(ln for ln in lines if not _ANSWER_CROP_LINE_RE.match(ln.strip())).strip()


def question_hash(question: Mapping[str, Any]) -> str:
    """只对会影响题目/答案可信度的内容做哈希。"""
    answer = question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    payload = {
        "id": question.get("id"),
        "type": question.get("type"),
        "content": question.get("content"),
        "options": question.get("options"),
        "answer": {
            "choice": answer.get("choice"),
            "explanation": stable_explanation(answer.get("explanation")),
        },
        "has_image": bool(question.get("has_image")),
        "image_ref": question.get("image_ref"),
        "q_pages": question.get("q_pages"),
        "a_pages": question.get("a_pages"),
    }
    return _sha256_bytes(_canonical(payload).encode("utf-8"))


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
    except (OSError, json.JSONDecodeError):
        return default


def _published_path(course_key: str) -> Path:
    return MATH_BANK_DIR / f"data-{course_key}.json"


def iter_published_rows(
    course_key: str,
    data: Mapping[str, Any],
) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """遍历所有有题号的已发布题目。"""
    for chapter in data.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        chapter_name = str(chapter.get("name") or chapter.get("topic_title") or "")
        for question in chapter.get("questions") or []:
            if not isinstance(question, Mapping):
                continue
            qid = str(question.get("id") or "").strip()
            if not qid:
                continue
            yield source_uid(course_key, chapter_name, qid), chapter_name, question


def iter_choice_rows(
    course_key: str,
    data: Mapping[str, Any],
) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    for row in iter_published_rows(course_key, data):
        if "选择" in str(row[2].get("type") or ""):
            yield row


def published_uid_counts(course_key: str, data: Mapping[str, Any]) -> Counter[str]:
    """返回发布题目 UID 的出现次数，供构建前检查重复。"""
    return Counter(uid for uid, _, _ in iter_published_rows(course_key, data))


def _old_verified_records() -> dict[str, Mapping[str, Any]]:
    old = _load_json(VERIFICATION_PATH, {})
    rows = old.get("records") if isinstance(old, Mapping) else []
    records = {
        str(row.get("source_uid")): row
        for row in rows or []
        if isinstance(row, Mapping) and row.get("source_uid")
    }
    state = _load_json(REPORTS_DIR / "quality_verification_state.json", {})
    if isinstance(state, Mapping):
        for uid, verified_hash in (state.get("verified") or {}).items():
            records.setdefault(
                str(uid),
                {
                    "source_uid": str(uid),
                    "status": "verified",
                    "verified_hash": verified_hash,
                },
            )
        if not records:
            for row in state.get("last_records") or []:
                if isinstance(row, Mapping) and row.get("source_uid"):
                    records[str(row["source_uid"])] = row
    # 原书逐页复核是当前正式的人工视觉证据。把已完成的 certify/patch
    # 记录纳入迁移索引，重建 ledger 时仍按题目 source_hash 严格匹配；
    # 这样重新运行 quality_ledger 不会把人工认证回退成历史 OCR 冲突。
    page_review = _load_json(PAGE_REVIEW_EVIDENCE_PATH, {})

    # 证据文件允许断点续跑产生同一 UID 的多条记录；必须按审核时间选最新
    # 记录，不能因迁移占位行排在末尾而覆盖当前哈希。migrated 行永远最低。
    def _review_rank(row: Mapping[str, Any]) -> str:
        value = str(row.get("reviewed_at") or "")
        return "" if value.startswith("migrated:") else value

    page_review_latest: dict[str, Mapping[str, Any]] = {}
    for row in (page_review.get("records") or []) if isinstance(page_review, Mapping) else []:
        if not isinstance(row, Mapping) or not row.get("source_uid"):
            continue
        uid = str(row["source_uid"])
        previous = page_review_latest.get(uid)
        if previous is not None and _review_rank(row) < _review_rank(previous):
            continue
        page_review_latest[uid] = row
    for row in page_review_latest.values():
        action = str(row.get("final_action") or "").lower()
        if action not in {"certify", "patch"}:
            continue
        if action == "patch" and row.get("post_patch_verified") is not True:
            continue
        if (
            not row.get("source_hash")
            or not row.get("q_pages_viewed")
            or not row.get("a_pages_viewed")
        ):
            continue
        records[str(row["source_uid"])] = {
            "source_uid": str(row["source_uid"]),
            "status": "verified",
            "verified_hash": str(row["source_hash"]),
            "source_hash": str(row["source_hash"]),
            "page_review": dict(row),
        }
    return records


def _record_matches_current(question: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    """旧版本记录没有 verified_hash 时，用双读图字段确认补丁仍在当前题上。"""
    fields = record.get("fields") if isinstance(record.get("fields"), Mapping) else {}
    if not fields:
        return False
    if "content" in fields and str(fields.get("content")) != str(question.get("content")):
        return False
    if "options" in fields and _canonical(fields.get("options")) != _canonical(
        question.get("options")
    ):
        return False
    answer = question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    if "answer.choice" in fields and str(fields.get("answer.choice")) != str(answer.get("choice")):
        return False
    if "explanation" in fields and stable_explanation(
        fields.get("explanation")
    ) != stable_explanation(answer.get("explanation")):
        return False
    return True


def _old_hold_uids() -> set[str]:
    old = _load_json(HOLD_PATH, {})
    return {str(uid) for uid in (old.get("source_uids") or []) if str(uid).strip()}


def _curated_records() -> dict[str, dict[str, Any]]:
    """真题增补的核验登记：data/zhenti/*.json → {uid: {hash, year}}。

    这些题不是原书 OCR，不能套用逐页复核。只有「题干 + 选项 + 答案」哈希与登记
    一致时才认证；题面或答案被改动后自动回到 pending，必须重新核对再登记。
    """
    records: dict[str, dict[str, Any]] = {}
    if not CURATED_DIR.is_dir():
        return records
    for path in sorted(CURATED_DIR.glob("*.json")):
        payload = _load_json(path, {})
        if not isinstance(payload, Mapping):
            continue
        meta = payload.get("meta") or {}
        year = meta.get("year")
        for item in payload.get("items") or []:
            course_key = str(item.get("course") or "").strip()
            chapter = str(item.get("chapter") or "").strip()
            qid = str(item.get("id") or "").strip()
            if not (course_key and chapter and qid):
                continue
            image = item.get("image")
            question = {
                "id": qid,
                "type": item.get("type") or "选择题",
                "content": item.get("content") or "",
                "options": item.get("options") or None,
                "answer": {
                    "choice": item.get("choice") or "",
                    "explanation": item.get("explanation") or "",
                },
                "has_image": bool(image),
                "image_ref": {"cropped": image, "note": f"{year} 统考真题题图"} if image else None,
                "q_pages": [],
                "a_pages": [],
            }
            records[source_uid(course_key, chapter, qid)] = {
                "hash": question_hash(question),
                "year": year,
            }
    return records


def _new_item(
    *,
    uid: str,
    course_key: str,
    chapter: str,
    question: Mapping[str, Any],
    old: Mapping[str, Any] | None,
    old_verified: Mapping[str, Any] | None,
    old_holds: set[str],
    curated: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    current_hash = question_hash(question)
    structural = bool(_choice_should_hold(question))
    same_hash = bool(old and old.get("source_hash") == current_hash)
    curated_row = curated.get(uid) if curated else None
    curated_ok = bool(curated_row and curated_row.get("hash") == current_hash and not structural)
    old_row = old_verified.get(uid) if old_verified else None
    vision_verified = bool(
        old_row
        and (
            (old_row.get("verified_hash") or old_row.get("source_hash")) == current_hash
            or _record_matches_current(question, old_row)
        )
        and old_row.get("status") in {"verified", "auto_fixed"}
    )
    vision_held = bool(old_row and old_row.get("status") == "held" and same_hash)
    # 原书逐页复核同时核对题面和答案页，属于比历史 OCR/Luna 冲突更高等级的
    # 当前证据。不能只把 source_fidelity 改成 verified 后再沿用旧的
    # answer_validation=conflict，否则重建会把已经亲眼复核的题重新判回 hold。
    page_review_verified = bool(
        old_row and isinstance(old_row.get("page_review"), Mapping) and same_hash
    )
    reasons = list(old.get("reason_codes") or []) if same_hash and old else []
    if structural or vision_held:
        reasons = sorted(
            set(reasons) | ({"structural_check"} if structural else {"vision_conflict"})
        )
        source_status = "conflict"
        answer_status = "conflict"
        overall = "hold"
    elif curated_ok:
        # 真题增补：内容来自官方原卷与官方答案扫描件，不套用原书逐页复核；
        # 只认登记文件里的题干+答案哈希，改题后自动回到 pending。
        source_status = "verified"
        answer_status = "verified"
        overall = "certified"
        reasons = [f"curated_zhenti_{curated_row.get('year')}"]
    elif vision_verified:
        source_status = "verified"
        if page_review_verified:
            answer_status = "verified"
            overall = "certified"
        else:
            answer_status = (
                str(old.get("answer_validation") or "pending") if same_hash and old else "pending"
            )
            overall = str(old.get("overall") or "pending") if same_hash and old else "pending"
    elif same_hash and old:
        source_status = str(old.get("source_fidelity") or "pending")
        answer_status = str(old.get("answer_validation") or "pending")
        overall = str(old.get("overall") or "pending")
    else:
        # 旧视觉门禁只证明了转录，不代表独立盲解已完成。
        source_status = "verified" if vision_verified else "pending"
        answer_status = "pending"
        overall = "pending"
        reasons = []
    if uid in old_holds and not structural and not same_hash:
        # 历史隔离是迁移证据，但内容变化后重新进入 pending，避免永久污染。
        reasons.append("legacy_hold_recheck")
    answer = question.get("answer") if isinstance(question.get("answer"), Mapping) else {}
    row = {
        "source_uid": uid,
        "course_key": course_key,
        "chapter": chapter,
        "question_id": str(question.get("id") or ""),
        "source_hash": current_hash,
        "source_fidelity": source_status,
        "answer_validation": answer_status,
        "overall": overall if overall in {"pending", "certified", "hold"} else "pending",
        "reason_codes": sorted(set(str(x) for x in reasons if str(x).strip())),
        "q_pages": list(question.get("q_pages") or []),
        "a_pages": list(question.get("a_pages") or []),
        "has_image": bool(question.get("has_image") or question.get("image_ref")),
        "answer_choice": str(answer.get("choice") or ""),
        "verified_at": old.get("verified_at") if same_hash and old else None,
        "evidence": dict(old.get("evidence") or {}) if same_hash and old else {},
    }
    apply_v2_fields(row, question)
    if curated_ok:
        row["provenance"] = "curated-zhenti"
    return row


def _recompute_overall(item: dict[str, Any], strict: bool = False) -> None:
    if item["source_fidelity"] == "conflict" or item["answer_validation"] == "conflict":
        item["overall"] = "hold"
    elif item["source_fidelity"] == "verified" and item["answer_validation"] == "verified":
        item["overall"] = "certified"
    else:
        item["overall"] = "hold" if strict else "pending"


def build_ledger(*, strict_courses: set[str] | None = None) -> dict[str, Any]:
    """从当前发布 JSON 重算 ledger；旧状态只在 source_hash 未变时保留。"""
    old_ledger = _load_json(LEDGER_PATH, {})
    old_items = old_ledger.get("items") if isinstance(old_ledger, Mapping) else {}
    old_items = old_items if isinstance(old_items, Mapping) else {}
    old_verified = dict(_old_verified_records())
    old_holds = _old_hold_uids()
    # 改号迁移：新旧 UID 共享同一份旧状态，避免换号后 hold/证据整条丢失
    for old_uid, new_uid in RENAMED_UIDS.items():
        if old_uid in old_verified and new_uid not in old_verified:
            old_verified[new_uid] = old_verified[old_uid]
        if old_uid in old_holds:
            old_holds.add(new_uid)
    previous_uid_by_uid = {new: old for old, new in RENAMED_UIDS.items()}
    previous_courses = old_ledger.get("courses") if isinstance(old_ledger, Mapping) else {}
    previous_courses = previous_courses if isinstance(previous_courses, Mapping) else {}
    strict_courses = (
        strict_courses
        if strict_courses is not None
        else {
            key
            for key, value in previous_courses.items()
            if isinstance(value, Mapping) and value.get("mode") == "strict"
        }
    )
    items: dict[str, dict[str, Any]] = {}
    courses: dict[str, dict[str, Any]] = {}
    published_hashes: dict[str, str] = {}
    curated = _curated_records()
    for course in COURSES:
        path = _published_path(course.key)
        if not path.is_file():
            continue
        data = _load_json(path, {})
        published_hashes[course.key] = sha256_file(path)
        rows = iter_published_rows(course.key, data)
        for uid, chapter, question in rows:
            if uid in items:
                item = items[uid]
                item["source_fidelity"] = "conflict"
                item["answer_validation"] = "conflict"
                item["reason_codes"] = sorted(
                    set(item["reason_codes"]) | {"structural_error", "duplicate_uid"}
                )
                _recompute_overall(item, course.key in strict_courses)
                continue
            previous_uid = previous_uid_by_uid.get(uid)
            old_item = old_items.get(uid) if isinstance(old_items, Mapping) else None
            if old_item is None and previous_uid and isinstance(old_items, Mapping):
                old_item = old_items.get(previous_uid)
            item = _new_item(
                uid=uid,
                course_key=course.key,
                chapter=chapter,
                question=question,
                old=old_item,
                old_verified=old_verified,
                old_holds=old_holds,
                curated=curated,
            )
            if old_item is not None and old_item.get("source_uid") == previous_uid:
                # 改号只换身份，不重新判可信度：沿用旧状态后按现行内容重算
                item["source_fidelity"] = str(
                    old_item.get("source_fidelity") or item["source_fidelity"]
                )
                item["answer_validation"] = str(
                    old_item.get("answer_validation") or item["answer_validation"]
                )
                if old_item.get("evidence"):
                    item["evidence"] = dict(old_item["evidence"])
                if old_item.get("verified_at"):
                    item["verified_at"] = old_item["verified_at"]
                item["reason_codes"] = sorted(
                    set(item["reason_codes"]) | {f"renamed_from:{previous_uid.split('::')[-1]}"}
                )
            _recompute_overall(item, course.key in strict_courses)
            items[uid] = item
        counts = Counter(
            item["overall"] for item in items.values() if item["course_key"] == course.key
        )
        courses[course.key] = {
            "name": course.name,
            "mode": "strict" if course.key in strict_courses else "progressive",
            "total": sum(counts.values()),
            "certified": counts.get("certified", 0),
            "pending": counts.get("pending", 0),
            "held": counts.get("hold", 0),
        }
    summary = Counter(item["overall"] for item in items.values())
    ledger = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "published_hashes": published_hashes,
        "courses": courses,
        "summary": {
            "total": len(items),
            "certified": summary.get("certified", 0),
            "pending": summary.get("pending", 0),
            "held": summary.get("hold", 0),
        },
        "items": dict(sorted(items.items())),
    }
    assert_consistent(ledger)
    return ledger


def assert_consistent(ledger: Mapping[str, Any]) -> None:
    items = ledger.get("items") or {}
    summary = ledger.get("summary") or {}
    counts = Counter(
        str(item.get("overall")) for item in items.values() if isinstance(item, Mapping)
    )
    expected = {
        "total": len(items),
        "certified": counts.get("certified", 0),
        "pending": counts.get("pending", 0),
        "held": counts.get("hold", 0),
    }
    actual = {key: int(summary.get(key, -1)) for key in expected}
    if expected != actual:
        raise ValueError(f"quality ledger summary mismatch: expected={expected} actual={actual}")
    for uid, item in items.items():
        if item.get("source_uid") != uid:
            raise ValueError(f"quality ledger UID mismatch: {uid}")
        if item.get("overall") == "certified" and not (
            item.get("source_fidelity") == "verified"
            and item.get("answer_validation") == "verified"
        ):
            raise ValueError(f"certified item is not dual verified: {uid}")
    source_uids = [str(item.get("source_uid")) for item in items.values()]
    if len(source_uids) != len(set(source_uids)):
        raise ValueError("quality ledger contains duplicate source UIDs")
    for course, data in (ledger.get("courses") or {}).items():
        if data.get("mode") == "strict" and int(data.get("pending", 0)):
            raise ValueError(f"strict course has pending items: {course}")


def derive_manifests(
    ledger: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assert_consistent(ledger)
    items = ledger.get("items") or {}
    hold_uids = sorted(uid for uid, item in items.items() if item.get("overall") == "hold")
    hashes = dict(ledger.get("published_hashes") or {})
    hold = {
        "schema_version": 3,
        "ledger_sha256": _sha256_bytes(_canonical(ledger).encode("utf-8")),
        "source_hashes": hashes,
        "source_uids": hold_uids,
        "summary": {
            "held": len(hold_uids),
            "note": "derived from quality-ledger.json",
            "courses": sorted((ledger.get("courses") or {}).keys()),
        },
    }
    verification = {
        "schema_version": 2,
        "status": "published",
        "generated_at": ledger.get("generated_at"),
        "round_id": "ledger",
        "summary": dict(ledger.get("summary") or {}),
        "published_hashes": hashes,
        "ledger_sha256": hold["ledger_sha256"],
        "courses": ledger.get("courses") or {},
    }
    # 保留旧视觉门禁的逐题记录，供 audit-only、追溯和下一次 ledger 迁移使用。
    previous = _load_json(VERIFICATION_PATH, {})
    records = previous.get("records") if isinstance(previous, Mapping) else []
    if not records:
        state = _load_json(REPORTS_DIR / "quality_verification_state.json", {})
        records = state.get("last_records") if isinstance(state, Mapping) else []
    if isinstance(records, list) and records:
        verification["records"] = records
    return hold, verification


def write_outputs(ledger: Mapping[str, Any]) -> None:
    MATH_BANK_DIR.mkdir(parents=True, exist_ok=True)
    DATA_QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    hold, verification = derive_manifests(ledger)
    write_json_atomic(LEDGER_PATH, ledger, indent=2, ensure_ascii=False)
    write_json_atomic(VERIFICATION_PATH, verification, indent=2, ensure_ascii=False)
    write_json_atomic(HOLD_PATH, hold, indent=2, ensure_ascii=False)
    published = strip_local_paths(ledger)
    write_json_atomic(PUBLISHED_LEDGER_PATH, published, indent=2, ensure_ascii=False)
    wrapper = "// Auto-generated; do not edit by hand.\nwindow.__QUALITY_LEDGER__ = "
    wrapper += json.dumps(published, ensure_ascii=False, separators=(",", ":")) + ";\n"
    write_text_atomic(LEDGER_JS_PATH, wrapper, encoding="utf-8")


def _published_index(
    course_key: str, data: Mapping[str, Any] | None = None
) -> dict[str, Mapping[str, Any]]:
    """发布数据里的 {uid: question}，重复 UID 会被 check_published 单独报出来。"""
    data = data if data is not None else _load_json(_published_path(course_key), {})
    index: dict[str, Mapping[str, Any]] = {}
    for uid, _chapter, question in iter_published_rows(course_key, data):
        index.setdefault(uid, question)
    return index


def load_drift_baseline(path: Path | None = None) -> set[str]:
    """读取存量漂移基线；文件缺失/损坏时返回空集合（不阻断，先让基线可建立）。"""
    payload = _load_json(path or DRIFT_BASELINE_PATH, {})
    items = payload.get("items") if isinstance(payload, Mapping) else None
    return {str(item) for item in items or [] if str(item)}


def write_drift_baseline(items: list[str], path: Path | None = None) -> Path:
    target = path or DRIFT_BASELINE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        target,
        {
            "schema_version": 1,
            "updated_at": _utc_now(),
            "count": len(items),
            "items": sorted(set(items)),
        },
        indent=2,
        ensure_ascii=False,
    )
    return target


def check_published(
    ledger: Mapping[str, Any] | None = None,
    *,
    strict_item_hashes: bool = False,
    drift_out: list[str] | None = None,
    drift_baseline: set[str] | None = None,
) -> list[str]:
    """发布态自检：课程哈希、UID 集合、逐题哈希。

    热更前跑一次；返回问题清单（空 = 通过）。缺记录不能默认放行——那样会把
    未经质量登记的题直接推给刷题池。

    逐题哈希默认只报告不拦截：发布数据被重排/规范化后（normalize_spaces 之类）
    几乎所有题的内容哈希都会变，但题面和答案没有语义变化；这种漂移需要重建
    ledger 才能消掉，不能当作「题目有问题」阻断热更。存量漂移记录在
    item-hash-drift-baseline.json；只有新增漂移会进入 problems。
    ``strict_item_hashes=True`` 时仍然阻断全部漂移。
    """
    ledger = ledger if ledger is not None else _load_json(LEDGER_PATH, {})
    problems: list[str] = []
    items = ledger.get("items") if isinstance(ledger, Mapping) else None
    items = items if isinstance(items, Mapping) else {}
    hashes = ledger.get("published_hashes") if isinstance(ledger, Mapping) else None
    hashes = hashes if isinstance(hashes, Mapping) else {}
    drift: list[str] = []
    drift_keys: list[str] = []
    baseline = load_drift_baseline() if drift_baseline is None else drift_baseline

    for course in COURSES:
        path = _published_path(course.key)
        if not path.is_file():
            problems.append(f"{course.key}: 发布文件缺失 {path.name}")
            continue
        actual = sha256_file(path)
        if hashes.get(course.key) != actual:
            problems.append(
                f"{course.key}: published_hashes 过期"
                f"（ledger={str(hashes.get(course.key))[:12]} 实际={actual[:12]}）"
            )
        data = _load_json(path, {})
        counts = published_uid_counts(course.key, data)
        for uid, count in sorted(counts.items()):
            if count > 1:
                problems.append(f"{course.key}: 发布数据重复 UID ×{count} {uid}")
        published = _published_index(course.key, data)
        ledger_uids = {
            uid
            for uid, item in items.items()
            if isinstance(item, Mapping) and item.get("course_key") == course.key
        }
        for uid in sorted(set(published) - ledger_uids):
            problems.append(f"{course.key}: 发布有此题但 ledger 无记录 {uid}")
        for uid in sorted(ledger_uids - set(published)):
            problems.append(f"{course.key}: ledger 有记录但已不在发布数据 {uid}")
        for uid, question in published.items():
            item = items.get(uid)
            if not isinstance(item, Mapping):
                continue
            if item.get("source_hash") != question_hash(question):
                drift.append(f"{course.key}: 逐题哈希过期 {uid}")
                drift_keys.append(f"{course.key}: {uid}")
                if drift_out is not None:
                    drift_out.append(f"{course.key}: {uid}")
    if strict_item_hashes:
        problems.extend(drift)
    else:
        problems.extend(
            problem for problem, key in zip(drift, drift_keys) if key not in baseline
        )
    return problems


def item_hash_drift(ledger: Mapping[str, Any] | None = None) -> list[str]:
    """发布数据与 ledger 逐题哈希不一致的条目（重排/规范化后常见，需要重建才消）。"""
    ledger = ledger if ledger is not None else _load_json(LEDGER_PATH, {})
    items = ledger.get("items") if isinstance(ledger, Mapping) else {}
    items = items if isinstance(items, Mapping) else {}
    drift: list[str] = []
    for course in COURSES:
        path = _published_path(course.key)
        if not path.is_file():
            continue
        for uid, _chapter, question in iter_published_rows(course.key, _load_json(path, {})):
            item = items.get(uid)
            if isinstance(item, Mapping) and item.get("source_hash") != question_hash(question):
                drift.append(f"{course.key}: {uid}")
    return drift


def migrate_drift(ledger: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """最小迁移：改号记录搬家、新发布题登记、删除题出账。

    只动有漂移的条目，不重算其它题的逐页/视觉证据（全量重建会把这些增量状态
    抹掉）。返回 (新 ledger, 变更说明)。
    """
    ledger = dict(ledger if ledger is not None else _load_json(LEDGER_PATH, {}))
    items: dict[str, Any] = dict(ledger.get("items") or {})
    changes: list[str] = []
    old_verified = dict(_old_verified_records())
    old_holds = _old_hold_uids()
    curated = _curated_records()
    previous_courses = ledger.get("courses") or {}
    strict_courses = {
        key
        for key, value in previous_courses.items()
        if isinstance(value, Mapping) and value.get("mode") == "strict"
    }

    published_hashes: dict[str, str] = {}
    for course in COURSES:
        path = _published_path(course.key)
        if not path.is_file():
            continue
        published_hashes[course.key] = sha256_file(path)
        published = {}
        chapter_of: dict[str, str] = {}
        for uid, chapter, question in iter_published_rows(course.key, _load_json(path, {})):
            if uid in published:
                continue
            published[uid] = question
            chapter_of[uid] = chapter

        # 1) 改号：旧记录搬成新 UID
        for old_uid, new_uid in RENAMED_UIDS.items():
            if old_uid not in items or new_uid not in published:
                continue
            if new_uid in items:
                items.pop(old_uid, None)
                changes.append(f"{course.key}: 删除旧号重复记录 {old_uid}")
                continue
            row = dict(items.pop(old_uid))
            row["source_uid"] = new_uid
            row["course_key"] = course.key
            row["chapter"] = chapter_of.get(new_uid, row.get("chapter") or "")
            row["question_id"] = str(published[new_uid].get("id") or "")
            row["source_hash"] = question_hash(published[new_uid])
            row["reason_codes"] = sorted(
                set(row.get("reason_codes") or []) | {f"renamed_from:{old_uid.split('::')[-1]}"}
            )
            _recompute_overall(row, course.key in strict_courses)
            items[new_uid] = row
            changes.append(
                f"{course.key}: 改号迁移 {old_uid.split('::')[-1]} → {new_uid.split('::')[-1]}"
            )

        # 2) 新发布题：登记为 pending，等证据；不能悄悄发布无记录题
        for uid, question in published.items():
            if uid in items:
                continue
            row = _new_item(
                uid=uid,
                course_key=course.key,
                chapter=chapter_of.get(uid, ""),
                question=question,
                old=None,
                old_verified=old_verified,
                old_holds=old_holds,
                curated=curated,
            )
            row["reason_codes"] = sorted(
                set(row.get("reason_codes") or []) | {"unregistered_publication"}
            )
            _recompute_overall(row, course.key in strict_courses)
            items[uid] = row
            changes.append(f"{course.key}: 补登记发布题 {uid} → {row['overall']}")

        # 3) 已删除的题：出账，避免 hold 清单指向不存在的题
        for uid in sorted(k for k, v in items.items() if v.get("course_key") == course.key):
            if uid not in published:
                items.pop(uid, None)
                changes.append(f"{course.key}: 移出已删除题 {uid}")

    courses: dict[str, Any] = {}
    for course in COURSES:
        if course.key not in published_hashes:
            continue
        counts = Counter(
            item.get("overall") for item in items.values() if item.get("course_key") == course.key
        )
        courses[course.key] = {
            "name": course.name,
            "mode": "strict" if course.key in strict_courses else "progressive",
            "total": sum(counts.values()),
            "certified": counts.get("certified", 0),
            "pending": counts.get("pending", 0),
            "held": counts.get("hold", 0),
        }
    summary = Counter(item.get("overall") for item in items.values())
    ledger["schema_version"] = 1
    ledger["generated_at"] = _utc_now()
    ledger["published_hashes"] = published_hashes
    ledger["courses"] = courses
    ledger["summary"] = {
        "total": len(items),
        "certified": summary.get("certified", 0),
        "pending": summary.get("pending", 0),
        "held": summary.get("hold", 0),
    }
    ledger["items"] = dict(sorted(items.items()))
    assert_consistent(ledger)
    return ledger, changes


def refresh_published_hashes() -> dict[str, Any]:
    """只更新 published_hashes 并重派生兼容清单，不迁移逐题状态。

    供 gen_answer_crops 改写发布 JSON 后调用：full rebuild 在纯文本管线里
    无法复现增量累积的 vision/page_review 状态，禁止在发布流程外随意全量重建。
    """
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    hashes = dict(ledger.get("published_hashes") or {})
    for c in COURSES:
        p = MATH_BANK_DIR / f"data-{c.key}.json"
        if p.exists():
            hashes[c.key] = sha256_file(p)
    ledger["published_hashes"] = hashes
    write_outputs(ledger)
    print("published_hashes refreshed:", {k: v[:12] for k, v in hashes.items()})
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="重算 408 质量 ledger 和兼容清单")
    parser.add_argument(
        "--strict-course", action="append", default=[], choices=[c.key for c in COURSES]
    )
    parser.add_argument(
        "--refresh-hashes",
        action="store_true",
        help="仅按当前 data-*.json 刷新 published_hashes 并重派生 hold/verification",
    )
    parser.add_argument(
        "--check-published",
        action="store_true",
        help="只校验发布态（课程哈希、UID 集合、逐题哈希）；有问题返回 1",
    )
    parser.add_argument(
        "--update-drift-baseline",
        action="store_true",
        help="把当前逐题哈希漂移固化为存量基线；此后只有新增漂移阻断热更",
    )
    parser.add_argument(
        "--strict-item-hashes",
        action="store_true",
        help="与 --check-published 同用：把逐题哈希漂移也算作失败",
    )
    parser.add_argument(
        "--fix-drift",
        action="store_true",
        help="最小迁移：改号记录搬家、新发布题登记、删除题出账（不动其它题的证据）",
    )
    args = parser.parse_args()
    if args.update_drift_baseline:
        ledger = _load_json(LEDGER_PATH, {})
        drift = item_hash_drift(ledger)
        path = write_drift_baseline(drift)
        print(f"drift baseline: {len(drift)} 条 -> {path}")
        return 0
    if args.check_published:
        refreshed = refresh_published_hashes() if args.refresh_hashes else None
        drift: list[str] = []
        baseline = load_drift_baseline()
        problems = check_published(
            refreshed,
            strict_item_hashes=args.strict_item_hashes,
            drift_out=drift,
            drift_baseline=baseline,
        )
        for problem in problems:
            print(f"  ! {problem}")
        if drift:
            new_drift = [item for item in drift if item not in baseline]
            print(
                f"  · 逐题哈希漂移 {len(drift)} 条"
                f"（存量 {len(drift) - len(new_drift)}，新增 {len(new_drift)}）"
            )
            if new_drift:
                print(f"    ! 新增漂移首条：{new_drift[0]}")
        print(f"check-published: {len(problems)} 个问题")
        return 1 if problems else 0
    if args.fix_drift:
        ledger, changes = migrate_drift()
        for change in changes:
            print(f"  - {change}")
        if not changes:
            print("ledger 无漂移")
            return 0
        write_outputs(ledger)
        print(json.dumps(ledger["summary"], ensure_ascii=False))
        return 0
    if args.refresh_hashes:
        refresh_published_hashes()
        return 0
    ledger = build_ledger(strict_courses=set(args.strict_course) or None)
    write_outputs(ledger)
    print(json.dumps(ledger["summary"], ensure_ascii=False, indent=2))
    print(f"ledger: {LEDGER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
