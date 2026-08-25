#!/usr/bin/env python3
"""408 选择题答案独立盲解门禁。

模型只接收题干、选项和（必要时）题目图，不接收原书答案/解析。结果逐题
落入 quality-ledger.json；冲突题进入 hold，绝不自动改答案。状态按 UID+题目
哈希断点保存，重建题目后会自动重新核验。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from config import COURSES, MATH_BANK_DIR, REPO_ROOT
from quality_ledger import (
    LEDGER_PATH,
    _load_json,
    _utc_now,
    assert_consistent,
    question_hash,
    write_outputs,
)
from vision_quality_gate import (
    TEMP_ROOT,
    _api_config,
    _create_completion,
    _data_url,
    _kimi_request,
    _message_content,
    _rows,
    _parse_json_value,
    question_crop,
)
from utils import write_json_atomic

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

sys.stdout.reconfigure(encoding="utf-8")

STATE_PATH = REPO_ROOT / "temp" / "408-blind-answer-state.json"
MIN_CONFIDENCE = 0.6


class BlindAnswerInfrastructureError(RuntimeError):
    pass


def normalize_choice(value: Any) -> str:
    raw = str(value or "").upper()
    # 保留有序多空的顺序；忽略模型输出中的空格、逗号和括号。
    return "".join(re.findall(r"[A-G]", raw))


def _question_text(row: Mapping[str, Any]) -> str:
    q = row["question"]
    lines = [str(q.get("content") or "")]
    options = q.get("options") if isinstance(q.get("options"), Mapping) else {}
    for key in sorted(options, key=str):
        lines.append(f"{key}. {options[key]}")
    if q.get("sub_questions"):
        lines.extend(f"({i + 1}) {text}" for i, text in enumerate(q["sub_questions"]))
    return "\n".join(lines)


def _blind_prompt(row: Mapping[str, Any]) -> str:
    return (
        "你是 408 计算机考研题目的独立解题器。只根据题目内容和选项作答，"
        "禁止读取或猜测题库已有答案，不要复述题库解析。返回严格 JSON："
        '{"choice":"B","confidence":0.0,"rationale":"一句话说明关键依据"}。'
        "choice 对单选返回一个字母；多选返回按字母排序的字符串；有序多空按题目顺序返回。"
        "看不清或题意不足时 choice 留空并降低 confidence。\n题目：\n"
        + _question_text(row)
    )


def _call_solver(client: Any, model: str, row: Mapping[str, Any], crop_path: Path | None) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": _blind_prompt(row)}]
    if crop_path is not None and crop_path.is_file():
        content.insert(0, {"type": "image_url", "image_url": {"url": _data_url(crop_path)}})
        content.insert(0, {"type": "text", "text": "下面附有题目原图；图中信息优先于 OCR 文本。"})
    request = _kimi_request(model, content, 768)
    try:
        response = _create_completion(client, request)
        value = _parse_json_value(_message_content(response))
    except Exception as exc:
        raise BlindAnswerInfrastructureError(f"{model} 调用失败: {exc}") from exc
    if not isinstance(value, dict):
        raise BlindAnswerInfrastructureError(f"{model} 返回格式不是 JSON 对象")
    try:
        confidence = float(value.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "choice": normalize_choice(value.get("choice") or value.get("answer")),
        "confidence": confidence,
        "rationale": str(value.get("rationale") or "")[:1000],
    }


def _load_state() -> dict[str, Any]:
    value = _load_json(STATE_PATH, {})
    return value if isinstance(value, dict) else {}


def _save_state(state: Mapping[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(STATE_PATH, state, indent=2, ensure_ascii=False)


def _rows_by_course(course_keys: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for course in COURSES:
        if course_keys and course.key not in course_keys:
            continue
        path = MATH_BANK_DIR / f"data-{course.key}.json"
        data = _load_json(path, {})
        for values in _rows(course.key, data).values():
            rows.extend(values)
    return rows


def run_gate(
    *, course_keys: set[str] | None = None, client_factory: Callable[[], Any] | None = None,
    retry_held: bool = False, strict_courses: set[str] | None = None,
) -> dict[str, Any]:
    api_key, base_url, models = _api_config()
    if not api_key and client_factory is None:
        raise BlindAnswerInfrastructureError("未配置 KIMI_CODE_API_KEY 或 MOONSHOT_API_KEY")
    if not models[0] or models[0] == models[1]:
        raise BlindAnswerInfrastructureError("答案盲解必须配置两个不同模型（KIMI_CODE_MODEL_B 不能等于模型 A）")
    client = client_factory() if client_factory else OpenAI(api_key=api_key, base_url=base_url)
    ledger = _load_json(LEDGER_PATH, {})
    if not isinstance(ledger, dict) or not isinstance(ledger.get("items"), dict):
        raise BlindAnswerInfrastructureError("缺少 quality-ledger.json，请先运行 quality_ledger.py")
    state = _load_state()
    results = state.setdefault("results", {})
    rows = _rows_by_course(course_keys or set())
    processed = passed = conflicted = skipped = 0
    for index, row in enumerate(rows, 1):
        uid = row["source_uid"]
        item = ledger["items"].get(uid)
        if not isinstance(item, dict):
            continue
        current_hash = question_hash(row["question"])
        previous = results.get(uid) if isinstance(results.get(uid), dict) else None
        if (
            previous and previous.get("source_hash") == current_hash
            and previous.get("status") in {"verified", "conflict"}
            and not (retry_held and previous.get("status") == "conflict")
        ):
            skipped += 1
            continue
        answer = row["question"].get("answer") if isinstance(row["question"].get("answer"), Mapping) else {}
        expected = normalize_choice(answer.get("choice"))
        if not expected:
            item["answer_validation"] = "conflict"
            item["overall"] = "hold"
            item.setdefault("reason_codes", []).append("missing_source_answer")
            results[uid] = {"source_hash": current_hash, "status": "conflict", "reason": "missing_source_answer"}
            conflicted += 1
            continue
        crop_path = None
        if row["question"].get("has_image") or row["question"].get("image_ref"):
            crop_path = question_crop(row["course_key"], row, TEMP_ROOT / "blind", margin=40).path
        first = _call_solver(client, models[0], row, crop_path)
        second = _call_solver(client, models[1], row, crop_path)
        ok = (
            first["choice"] == expected == second["choice"]
            and first["confidence"] >= MIN_CONFIDENCE
            and second["confidence"] >= MIN_CONFIDENCE
        )
        processed += 1
        result_status = "verified" if ok else "conflict"
        results[uid] = {
            "source_hash": current_hash,
            "status": result_status,
            "models": list(models),
            "expected_choice": expected,
            "first": first,
            "second": second,
            "updated_at": _utc_now(),
        }
        item["answer_validation"] = "verified" if ok else "conflict"
        item["evidence"] = {
            "answer_models": list(models),
            "blind_choices": [first["choice"], second["choice"]],
            "blind_confidence": [first["confidence"], second["confidence"]],
        }
        reasons = set(item.get("reason_codes") or [])
        if ok:
            reasons.discard("blind_conflict")
            if item.get("source_fidelity") == "verified":
                item["overall"] = "certified"
            else:
                item["overall"] = "pending"
            passed += 1
        else:
            reasons.add("blind_conflict")
            item["overall"] = "hold"
            conflicted += 1
        item["reason_codes"] = sorted(reasons)
        item["verified_at"] = _utc_now() if ok else None
        if index % 10 == 0:
            _save_state(state)
            write_json_atomic(LEDGER_PATH, ledger, indent=2, ensure_ascii=False)
    state.update({"models": list(models), "base_url": base_url, "updated_at": _utc_now()})
    _save_state(state)
    if strict_courses:
        for key in strict_courses:
            course = (ledger.get("courses") or {}).get(key)
            if not isinstance(course, dict):
                continue
            course["mode"] = "strict"
            for item in ledger["items"].values():
                if item.get("course_key") == key and item.get("overall") == "pending":
                    item["overall"] = "hold"
                    item.setdefault("reason_codes", []).append("strict_cutover_pending")
    ledger["generated_at"] = _utc_now()
    # 重新计算摘要，确保写入前就能发现状态不一致。
    from collections import Counter
    counts = Counter(item.get("overall") for item in ledger["items"].values())
    ledger["summary"] = {
        "total": len(ledger["items"]), "certified": counts.get("certified", 0),
        "pending": counts.get("pending", 0), "held": counts.get("hold", 0),
    }
    assert_consistent(ledger)
    write_outputs(ledger)
    return {"processed": processed, "passed": passed, "conflicted": conflicted, "skipped": skipped, "models": list(models)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", action="append", choices=[c.key for c in COURSES])
    parser.add_argument("--retry-held", action="store_true")
    parser.add_argument("--strict-course", action="append", choices=[c.key for c in COURSES], default=[])
    args = parser.parse_args()
    try:
        result = run_gate(course_keys=set(args.course or []), retry_held=args.retry_held, strict_courses=set(args.strict_course))
    except BlindAnswerInfrastructureError as exc:
        print(f"[blind-gate] BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
