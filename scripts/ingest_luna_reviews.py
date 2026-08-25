#!/usr/bin/env python3
"""摄取两个隔离的 Luna 盲解结果和原书视觉/OCR 结果。

这个模块只处理本地 JSON，不调用模型或其它外部 API。结果包的协议元数据
必须在包级和逐题级保持一致，并且逐题 ``source_hash`` 必须仍然等于当前
quality-ledger 的哈希。只有原书答案与两次独立盲解一致（置信度 >= 0.70），
以及 OCR（置信度 >= 0.80）或两次一致的 visual（各自置信度 >= 0.80）都通过，
题目才会被标记为 certified。

输入包允许使用 ``items``、``results``、``records`` 或 ``rows`` 作为题目列表。
包级的 protocol/pass_id/source_hash/packet_hash 会继承到题目；逐题字段存在时
会再次校验。这样既兼容批次导出，也不会因为缺少重复元数据而放过旧结果。
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from quality_ledger import LEDGER_PATH, _load_json, _utc_now, assert_consistent, write_outputs

ANSWER_MIN_CONFIDENCE = 0.70
SOURCE_MIN_CONFIDENCE = 0.80
LUNA_MODEL = "gpt-5.6-luna"


class LunaReviewError(ValueError):
    """结果包无法安全摄取。"""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _choice(value: Any) -> str:
    """严格规范化单选/多选答案；正文混入时返回空串。

    不能用 ``findall('[A-G]')``：模型偶尔会返回 ``C……理由`` 或整段中文，
    那样会把正文中的字母误当成 choice。只允许 A-G 和题库导出常用分隔符。
    """
    if isinstance(value, (list, tuple, set)):
        parts = [_choice(part) for part in value]
        return "".join(parts) if all(parts) else ""
    if not isinstance(value, str):
        return ""
    raw = value.strip().upper()
    if not raw or not re.fullmatch(r"[A-G\s,，、/／;；|&()\[\]{}]*", raw):
        return ""
    letters = re.findall(r"[A-G]", raw)
    return "".join(letters)


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value: Any = None
    for key in ("items", "results", "records", "rows"):
        if key in payload:
            value = payload[key]
            break
    if value is None:
        # 也接受 {"uid": {...}} 的导出，避免 UID 作为 map key 时丢失。
        value = payload.get("by_uid")
    if isinstance(value, Mapping):
        output = []
        for uid, row in value.items():
            if isinstance(row, Mapping):
                item = dict(row)
                item.setdefault("source_uid", uid)
                output.append(item)
        return output
    if not isinstance(value, list):
        raise LunaReviewError("结果包缺少 items/results/records/rows 列表")
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _meta(payload: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], key: str) -> str:
    top = _text(payload.get(key))
    values = {_text(row.get(key)) for row in rows if _text(row.get(key))}
    if top and values and values != {top}:
        raise LunaReviewError(f"{key} 包级与逐题值不一致")
    if not top and len(values) == 1:
        top = next(iter(values))
    if not top:
        raise LunaReviewError(f"结果包缺少 {key}")
    return top


def _packet(path_or_payload: Path | Mapping[str, Any], role: str) -> dict[str, Any]:
    if isinstance(path_or_payload, Mapping):
        payload = dict(path_or_payload)
        path = "<mapping>"
    else:
        path = str(path_or_payload)
        try:
            payload = json.loads(Path(path_or_payload).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LunaReviewError(f"无法读取 {role} 结果包: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise LunaReviewError(f"{role} 结果包必须是 JSON 对象: {path}")
    rows = _rows(payload)
    protocol = _meta(payload, rows, "protocol")
    pass_id = _meta(payload, rows, "pass_id")
    # packet_hash 是本批次唯一绑定值，必须位于包级。逐题 ``item_hash``
    # 只是题目级兼容字段，绝不能被误当成 packet_hash。
    packet_hash = _text(payload.get("packet_hash"))
    if not packet_hash:
        raise LunaReviewError(f"{role} 结果包缺少顶层 packet_hash")
    # source_hash 可以是每道题不同的字段；如果包级提供，则逐题继承。
    packet_source_hash = _text(payload.get("source_hash"))
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.setdefault("protocol", protocol)
        item.setdefault("pass_id", pass_id)
        item.setdefault("packet_hash", packet_hash)
        if packet_source_hash:
            item.setdefault("source_hash", packet_source_hash)
        for key in ("protocol", "pass_id", "packet_hash"):
            if _text(item.get(key)) != (protocol if key == "protocol" else pass_id if key == "pass_id" else packet_hash):
                raise LunaReviewError(f"{role} 题目 {item.get('source_uid')!r} 的 {key} 不匹配")
        uid = _text(item.get("source_uid") or item.get("uid") or item.get("id"))
        if not uid:
            raise LunaReviewError(f"{role} 结果缺少 source_uid")
        item["source_uid"] = uid
        if not _text(item.get("source_hash")):
            raise LunaReviewError(f"{role} {uid} 缺少 source_hash")
        normalized.append(item)
    return {"protocol": protocol, "pass_id": pass_id, "packet_hash": packet_hash, "rows": normalized}


def _index(packet: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in packet["rows"]:
        result.setdefault(str(row["source_uid"]), []).append(row)
    return result


def _field(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _observation_ok(value: Mapping[str, Any]) -> bool:
    # source_verified 是早期导出的兼容简写；正式 OCR 协议要求同时给出
    # triad（题干/选项/答案三项）和 published_match。
    if "source_verified" in value:
        return bool(value["source_verified"])
    if "triad" in value or "published_match" in value:
        return bool(value.get("triad")) and bool(value.get("published_match"))
    for key in ("verified", "ok", "passed", "match", "consistent", "source_ok"):
        if key in value:
            return bool(value[key])
    # source-visual 导出常用 content/options/answer_match；全部显式匹配才算通过。
    checks = [value[key] for key in ("content_match", "options_match", "answer_match") if key in value]
    if checks:
        return all(bool(check) for check in checks)
    return False


def _as_observations(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _source_status(rows: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:
    """返回 source 是否通过及证据方法；不对模糊结果作乐观推断。"""
    ocr: list[Mapping[str, Any]] = []
    visual: list[Mapping[str, Any]] = []
    for row in rows:
        ocr.extend(_as_observations(_field(row, "ocr", "ocr_result", "source_ocr")))
        visual.extend(_as_observations(_field(row, "visual", "visual_results", "visual_passes")))
        for key in ("visual_a", "visual_b", "visual_1", "visual_2"):
            visual.extend(_as_observations(row.get(key)))
        method = _text(row.get("method") or row.get("source_method")).lower()
        if method in {"ocr", "source-ocr", "source_ocr"}:
            ocr.append(row)
        elif method in {"visual", "source-visual", "source_visual"}:
            visual.append(row)
        elif any(key in row for key in ("source_verified", "source_ok", "ocr_confidence", "transcription_ok", "verified", "ok", "passed")):
            ocr.append(row)
    if any(_observation_ok(obs) and _confidence(obs.get("confidence")) >= SOURCE_MIN_CONFIDENCE for obs in ocr):
        return True, "ocr"
    valid_visual = [
        obs for obs in visual
        if _observation_ok(obs) and _confidence(obs.get("confidence")) >= SOURCE_MIN_CONFIDENCE
    ]
    if len(valid_visual) >= 2:
        # 两轮 visual 若都给了可比字段，必须一致；没有可比字段时仍要求各自明确通过。
        signatures = []
        for obs in valid_visual[:2]:
            signature = _field(obs, "content_hash", "transcription_hash", "text_hash", "answer_choice", "choice")
            if signature is not None:
                signatures.append(str(signature))
        if not signatures or len(set(signatures)) == 1:
            return True, "visual"
    return False, ""


def _answer_status(item: Mapping[str, Any], rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str], list[float]]:
    answer = item.get("answer_choice")
    if not answer and isinstance(item.get("answer"), Mapping):
        answer = item["answer"].get("choice")
    expected = _choice(answer)
    choices: list[str] = []
    confidences: list[float] = []
    for rows in (rows_a, rows_b):
        row = rows[0] if rows else {}
        value = _field(row, "choice", "answer_choice", "luna_choice", "model_choice", "predicted_choice", "answer")
        choices.append(_choice(value))
        confidences.append(_confidence(row.get("confidence")))
    return (
        bool(expected and choices[0] == expected and choices[1] == expected and choices[0] == choices[1]
             and all(value >= ANSWER_MIN_CONFIDENCE for value in confidences)),
        choices,
        confidences,
    )


def _adjudication_certifies(row: Mapping[str, Any]) -> bool:
    """第三轮裁决必须明确 certify，并携带完整的答案/原书证据。"""
    action = _text(row.get("action") or row.get("decision") or row.get("adjudication")).lower()
    if action != "certify":
        return False
    direct = row.get("source_verified") is True and row.get("answer_verified") is True
    nested = isinstance(row.get("source_evidence"), Mapping) and bool(row["source_evidence"]) \
        and isinstance(row.get("answer_evidence"), Mapping) and bool(row["answer_evidence"])
    return direct or nested


def _reason(item: dict[str, Any], code: str) -> None:
    item["reason_codes"] = sorted(set(str(value) for value in item.get("reason_codes") or [] if str(value).strip()) | {code})


def _summary(ledger: dict[str, Any]) -> None:
    counts = Counter(item.get("overall") for item in ledger.get("items", {}).values())
    ledger["summary"] = {
        "total": len(ledger.get("items", {})),
        "certified": counts.get("certified", 0),
        "pending": counts.get("pending", 0),
        "held": counts.get("hold", 0),
    }


def ingest_luna_reviews(
    blind_a: Path | Mapping[str, Any],
    blind_b: Path | Mapping[str, Any],
    source: Path | Mapping[str, Any],
    *,
    ledger_path: Path = LEDGER_PATH,
    dry_run: bool = False,
    adjudication: Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """摄取一个批次；返回统计信息和逐题状态。"""
    packet_a = _packet(blind_a, "blind pass A")
    packet_b = _packet(blind_b, "blind pass B")
    packet_source = _packet(source, "source visual/OCR")
    packets = (packet_a, packet_b, packet_source)
    protocols = {packet["protocol"] for packet in packets}
    if len(protocols) != 1:
        raise LunaReviewError("三个结果包 protocol 不一致")
    pass_ids = [packet["pass_id"] for packet in packets]
    if len(set(pass_ids)) != 3:
        raise LunaReviewError("三个结果包 pass_id 必须互不相同")
    packet_adjudication = _packet(adjudication, "adjudication") if adjudication is not None else None
    all_packets = packets + ((packet_adjudication,) if packet_adjudication else ())
    all_pass_ids = [packet["pass_id"] for packet in all_packets]
    if len(set(all_pass_ids)) != len(all_pass_ids):
        raise LunaReviewError("结果包 pass_id 必须互不相同")
    ledger = _load_json(ledger_path, {})
    if not isinstance(ledger, dict) or not isinstance(ledger.get("items"), dict):
        raise LunaReviewError("缺少 quality-ledger.json 或 items")
    indexes = [_index(packet) for packet in packets]
    adjudication_index = _index(packet_adjudication) if packet_adjudication else {}
    all_uids = set().union(*(set(index) for index in indexes))
    unknown = sorted(uid for uid in all_uids if uid not in ledger["items"])
    if unknown:
        raise LunaReviewError(f"结果包含当前 ledger 不存在的 UID: {unknown[0]}")
    adjudication_unknown = sorted(uid for uid in adjudication_index if uid not in ledger["items"])
    if adjudication_unknown:
        raise LunaReviewError(f"adjudication 包含当前 ledger 不存在的 UID: {adjudication_unknown[0]}")
    results: list[dict[str, Any]] = []
    for uid in sorted(all_uids):
        item = ledger["items"][uid]
        if not isinstance(item, dict):
            raise LunaReviewError(f"ledger item 不是对象: {uid}")
        current_hash = _text(item.get("source_hash"))
        rows = [index.get(uid, []) for index in indexes]
        evidence: dict[str, Any] = {
            "protocol": packet_a["protocol"],
            "model": LUNA_MODEL,
            "pass_ids": all_pass_ids,
            "packet_hashes": [packet["packet_hash"] for packet in all_packets],
            "source_hash": current_hash,
            "choices": [],
            "confidence": [],
            "updated_at": _utc_now(),
        }
        was_hold = item.get("overall") == "hold"
        stale = any(not group or any(_text(row.get("source_hash")) != current_hash for row in group) for group in rows)
        missing = any(not group for group in rows)
        if stale:
            _reason(item, "luna_stale_source_hash")
            item["overall"] = "hold"
            evidence["status"] = "hold"
            evidence["reason"] = "stale_source_hash"
        elif missing:
            _reason(item, "luna_missing_result")
            item["overall"] = "hold"
            evidence["status"] = "hold"
            evidence["reason"] = "missing_result"
        else:
            answer_ok, choices, confidences = _answer_status(item, rows[0], rows[1])
            source_ok, source_method = _source_status(rows[2])
            evidence.update({
                "choices": choices,
                "confidence": confidences,
                # 保留旧字段名，方便已有审计页读取。
                "blind_choices": choices,
                "blind_confidence": confidences,
                "source_method": source_method,
            })
            if answer_ok:
                item["answer_validation"] = "verified"
            else:
                item["answer_validation"] = "conflict"
                _reason(item, "luna_answer_conflict")
            if source_ok:
                item["source_fidelity"] = "verified"
            else:
                item["source_fidelity"] = "conflict"
                _reason(item, "luna_source_conflict")
            # 历史 hold 是人工/结构性隔离，新的自动证据不能越过它。
            adjudication_row = (adjudication_index.get(uid) or [None])[0]
            adjudicated = (
                was_hold
                and isinstance(adjudication_row, Mapping)
                and _text(adjudication_row.get("source_hash")) == current_hash
                and _adjudication_certifies(adjudication_row)
                and answer_ok
                and source_ok
            )
            if adjudicated:
                item["overall"] = "certified"
                evidence["status"] = "certified"
                evidence["adjudication"] = "certify"
            elif was_hold:
                evidence["status"] = "hold"
                evidence["reason"] = "existing_hold"
            elif answer_ok and source_ok:
                item["overall"] = "certified"
                evidence["status"] = "certified"
            else:
                item["overall"] = "hold"
                evidence["status"] = "hold"
        item.setdefault("evidence", {})["luna_reviews"] = evidence
        results.append({"source_uid": uid, **evidence})
    _summary(ledger)
    assert_consistent(ledger)
    if not dry_run:
        write_outputs(ledger)
    return {"processed": len(results), "certified": sum(row.get("status") == "certified" for row in results),
            "held": sum(row.get("status") == "hold" for row in results), "dry_run": dry_run, "results": results}


# 便于调用方按旧摄取器命名调用。
apply_reviews = ingest_luna_reviews


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="摄取 Luna 双盲解与 source visual/OCR 结果")
    parser.add_argument("blind_a", type=Path)
    parser.add_argument("blind_b", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--adjudication", type=Path, help="可选第三轮裁决结果（仅解除原有 hold）")
    parser.add_argument("--dry-run", action="store_true", help="只校验和打印，不写 quality-ledger 输出")
    args = parser.parse_args(argv)
    try:
        result = ingest_luna_reviews(
            args.blind_a, args.blind_b, args.source,
            ledger_path=args.ledger, dry_run=args.dry_run, adjudication=args.adjudication,
        )
    except LunaReviewError as exc:
        parser.error(str(exc))
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
