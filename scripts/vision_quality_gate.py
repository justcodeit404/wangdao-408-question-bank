#!/usr/bin/env python3
"""408 题库全自动章节抽检门禁。

这个脚本只把原书页面当作事实来源：两个不同视觉模型独立读取题目和答案裁图。
Provider 顺序：火山方舟/豆包（ARK_API_KEY 或 DOUBAO_API_KEY）→ Moonshot Open
Platform（MOONSHOT_API_KEY）。禁止 Kimi Coding Plan。模型无法一致确认的题目会
进入 quality-hold；网络/API 故障直接阻断构建，不会修改发布题库。

默认由 build_all.py 在 merge 前调用。脚本也可单独用于测试，模型客户端可注入，
避免测试触发真实网络。已有 OCR 坐标只用来裁答案区，不参与通过判定。
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from config import COURSES, MATH_BANK_DIR, REPORTS_DIR
from cross_validate_answers import CACHE_ROOT, parse_group_answers, run_fresh_ocr
from quality_hold import collect_hold_uids, source_uid
from utils import write_json_atomic

try:  # Pillow 已是题库构建依赖；导入失败时给出清晰的门禁错误。
    from PIL import Image
except Exception:  # pragma: no cover - 仅在破损环境触发
    Image = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - 测试可注入 client
    OpenAI = None

sys.stdout.reconfigure(encoding="utf-8")

STATE_PATH = REPORTS_DIR / "quality_verification_state.json"
MANIFEST_PATH = MATH_BANK_DIR / "quality-verification.json"
PATCH_PATH = Path(__file__).resolve().parent.parent / "data" / "quality" / "vision_patches.json"
HOLD_PATH = MATH_BANK_DIR / "quality-hold.json"
TEMP_ROOT = Path(__file__).resolve().parents[2] / "temp" / "408-vision-audit"

OPEN_PLATFORM_MODELS = ("kimi-k3", "kimi-k2.6")
DOUBAO_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_DEFAULT_MODELS = (
    "doubao-1-5-vision-pro-32k-250115",
    "doubao-1-5-thinking-vision-pro",
)
# 历史 Coding Plan 模型前缀仍用于 request 侧 temperature/extra_body 门控；
# _api_config 不再选择 Coding Plan（会 pop KIMI_CODE_*）。
CODING_PLAN_DEFAULT_MODEL = "kimi-for-coding"
DEFAULT_PER_CHAPTER = 5
DEFAULT_BATCH_SIZE = 5
# 视觉模型自评置信度偏保守；真正门禁是双模型字段一致。低于 0.5 仍视为看不清。
MIN_CONFIDENCE = 0.5
PASS_STATUSES = {"verified", "auto_fixed"}


class VisionInfrastructureError(RuntimeError):
    """API、图片或 OCR 基础设施故障；与题目冲突严格区分。"""


class VisionConflictError(RuntimeError):
    """模型无法在给定原书证据上达成一致。"""


# 放大裁剪重试只对“可能是裁图不够”的冲突有意义。
# 字段已经读出来但不一致，再跑一轮 API 几乎不会和解。
_RETRYABLE_CONFLICTS = (
    "双模型未返回该题",
    "双模型置信度不足",
    "双模型未提取出",
    "配图需求判断冲突",
    "原书配图与题库配图状态不一致",
)


def retryable_conflict(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _RETRYABLE_CONFLICTS)


@dataclass(frozen=True)
class Crop:
    path: Path
    page: int
    kind: str
    sha256: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_text(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def canonical_choice(value: Any) -> str:
    return "".join(ch for ch in canonical_text(value).upper() if ch in "ABCDEF")


def canonical_content(value: Any) -> str:
    """去掉答案裁图偶尔重复识别出的题号，保留题干原文。"""
    return re.sub(r"^\s*\d{1,3}\s*[.)、．]\s*", "", canonical_text(value))


def source_hash(question: dict[str, Any]) -> str:
    answer = question.get("answer") if isinstance(question.get("answer"), dict) else {}
    payload = {
        "content": question.get("content"),
        "options": question.get("options"),
        "answer": answer,
        "image_ref": question.get("image_ref"),
        "bbox": question.get("bbox"),
        "page": question.get("page"),
        "q_pages": question.get("q_pages"),
        "a_pages": question.get("a_pages"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def apply_patch_to_question(
    question: dict[str, Any], patch: dict[str, Any] | None
) -> dict[str, Any]:
    """把视觉补丁套到题目副本上，供写入 verified hash，避免下轮抽回刚修过的题。"""
    updated = json.loads(json.dumps(question))
    patch = patch or {}
    for field in ("content", "options"):
        if field in patch:
            updated[field] = patch[field]
    if isinstance(patch.get("answer"), dict):
        current = updated.get("answer")
        if not isinstance(current, dict):
            current = {}
            updated["answer"] = current
        current.update(patch["answer"])
    return updated


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _held_uids() -> set[str]:
    payload = _load_json(HOLD_PATH, {})
    return (
        {str(value) for value in payload.get("source_uids", [])}
        if isinstance(payload, dict)
        else set()
    )


def _priority_uids() -> set[str]:
    """质量报告中的高风险和历史隔离题，始终额外检查。"""
    result = _held_uids()
    for filename in ("quality_report.json", "cross_validation_review.json"):
        payload = _load_json(REPORTS_DIR / filename, {})
        records = payload.get("records", []) if isinstance(payload, dict) else payload
        if isinstance(records, list):
            result.update(
                str(row.get("source_uid"))
                for row in records
                if isinstance(row, dict) and row.get("source_uid")
            )
    return result


def _api_config() -> tuple[str, str, tuple[str, str]]:
    """Provider 顺序：Doubao Ark → Moonshot Open Platform。永不选 Kimi Coding Plan。"""
    # Coding Plan 默认 B=A，且会抢占选择；进程内清掉，避免误用。
    os.environ.pop("KIMI_CODE_API_KEY", None)
    os.environ.pop("KIMI_CODE_KEY_FILE", None)

    doubao_key = os.getenv("ARK_API_KEY", "").strip() or os.getenv("DOUBAO_API_KEY", "").strip()
    if doubao_key:
        model_a = (
            os.getenv("DOUBAO_MODEL", DOUBAO_DEFAULT_MODELS[0]).strip() or DOUBAO_DEFAULT_MODELS[0]
        )
        model_b = (
            os.getenv("DOUBAO_MODEL_B", DOUBAO_DEFAULT_MODELS[1]).strip()
            or DOUBAO_DEFAULT_MODELS[1]
        )
        return (
            doubao_key,
            os.getenv("DOUBAO_BASE_URL", DOUBAO_DEFAULT_BASE_URL).rstrip("/"),
            (model_a, model_b),
        )

    open_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    if open_key:
        return (
            open_key,
            os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/"),
            OPEN_PLATFORM_MODELS,
        )
    return "", "", OPEN_PLATFORM_MODELS


def require_distinct_models(models: tuple[str, str]) -> None:
    """Live API 路径一律要求两个不同视觉模型（rotation / priority / full / uids-file）。"""
    if models[0] == models[1]:
        raise VisionInfrastructureError(
            "原书核对必须配置两个不同视觉模型"
            "（Doubao: DOUBAO_MODEL ≠ DOUBAO_MODEL_B；"
            "Open Platform: kimi-k3 + kimi-k2.6）"
        )


def load_uids_file(path: Path | str) -> set[str]:
    """读取 --uids-file：JSON 数组 of source_uid。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise VisionInfrastructureError("--uids-file 必须是 JSON 数组")
    return {str(item) for item in payload if str(item).strip()}


def select_full_candidates(
    rows: list[dict[str, Any]],
    verified: dict[str, Any],
    hold_uids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """--full：未验证 hash 的题 + quality-hold 中的 UID（即使 hash 已匹配也重试）。"""
    hold = hold_uids or set()
    return [
        row
        for row in rows
        if verified.get(row["source_uid"]) != source_hash(row["question"])
        or row["source_uid"] in hold
    ]


def select_by_uids(rows: list[dict[str, Any]], uids: set[str]) -> list[dict[str, Any]]:
    """--uids-file：仅选 uids ∩ 已发布选择题行。"""
    if not uids:
        return []
    return [row for row in rows if row["source_uid"] in uids]


def _rows(course_key: str, data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chapter_index, chapter in enumerate(data.get("chapters", [])):
        major = str(chapter.get("l1_name") or chapter.get("name") or "未知章节")
        minor = str(chapter.get("name") or chapter.get("topic_title") or major)
        for question_index, question in enumerate(chapter.get("questions", [])):
            if "选择" not in str(question.get("type") or ""):
                continue
            qid = str(question.get("id") or "").strip()
            if not qid:
                continue
            grouped.setdefault(major, []).append(
                {
                    "course_key": course_key,
                    "major_chapter": major,
                    "minor_chapter": minor,
                    "chapter_index": chapter_index,
                    "question_index": question_index,
                    "source_uid": source_uid(course_key, minor, qid),
                    "question": question,
                }
            )
    for values in grouped.values():
        values.sort(
            key=lambda row: (
                int(row["question"].get("page") or 0),
                row["question_index"],
                str(row["question"].get("id") or ""),
            )
        )
    return grouped


def _strata(rows: list[dict[str, Any]], count: int) -> Iterable[list[dict[str, Any]]]:
    count = min(max(1, count), len(rows))
    for index in range(count):
        yield rows[index * len(rows) // count : (index + 1) * len(rows) // count]


def select_rotating(
    rows: list[dict[str, Any]], state: dict[str, Any], per_chapter: int, round_id: str
) -> list[dict[str, Any]]:
    """优先从未验证题中每个原书分层取一题，覆盖完后开启新 epoch。"""
    verified = state.setdefault("verified", {})
    pending = [
        row for row in rows if verified.get(row["source_uid"]) != source_hash(row["question"])
    ]
    if not pending:
        state["epoch"] = int(state.get("epoch") or 0) + 1
        pending = list(rows)
        for row in rows:
            verified.pop(row["source_uid"], None)
    if not pending:
        return []
    chosen: list[dict[str, Any]] = []
    for segment in _strata(rows, min(per_chapter, len(rows))):
        available = [row for row in segment if row in pending]
        if available:
            chosen.append(
                min(
                    available,
                    key=lambda row: hashlib.sha256(
                        f"{round_id}\0{row['source_uid']}".encode()
                    ).hexdigest(),
                )
            )
    if len(chosen) < min(per_chapter, len(pending)):
        rest = [row for row in pending if row not in chosen]
        chosen.extend(rest[: min(per_chapter, len(pending)) - len(chosen)])
    return chosen[:per_chapter]


def _page_image(course_key: str, page: int) -> Path:
    for course in COURSES:
        if course.key == course_key:
            path = course.pdf_images_dir / f"page_{page:03d}.png"
            if not path.is_file():
                raise VisionInfrastructureError(f"原书页图缺失: {path}")
            return path
    raise VisionInfrastructureError(f"未知课程: {course_key}")


def _crop_box(
    image: Path, box: tuple[float, float, float, float], out: Path, margin: int = 24
) -> Crop:
    if Image is None:
        raise VisionInfrastructureError("Pillow 不可用，无法裁剪原书页")
    with Image.open(image) as source:
        width, height = source.size
        x0, y0, x1, y1 = box
        crop = (
            max(0, int(x0) - margin),
            max(0, int(y0) - margin),
            min(width, int(x1) + margin),
            min(height, int(y1) + margin),
        )
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            raise VisionInfrastructureError(f"无效裁剪框: {image} {box}")
        out.parent.mkdir(parents=True, exist_ok=True)
        source.crop(crop).save(out, format="PNG")
    return Crop(out, int(image.stem.split("_")[-1]), out.stem.split("-")[-1], _sha256_file(out))


def question_crop(course_key: str, row: dict[str, Any], out_dir: Path, margin: int = 28) -> Crop:
    question = row["question"]
    page = int(question.get("page") or (question.get("q_pages") or [0])[0])
    bbox = question.get("bbox")
    image = _page_image(course_key, page)
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise VisionInfrastructureError(f"题目缺少 bbox: {row['source_uid']}")
    return _crop_box(
        image,
        tuple(float(value) for value in bbox),
        out_dir / f"{row['source_uid'].replace(':', '_')}-question.png",
        margin,
    )


def _answer_number(qid: str) -> str:
    match = re.search(r"(\d+)", qid)
    return match.group(1).zfill(2) if match else ""


def answer_crop(course_key: str, row: dict[str, Any], out_dir: Path, margin: int = 30) -> Crop:
    """按 OCR 坐标从答案页裁到当前题号和下一题号之间，避免上传整页。"""
    question = row["question"]
    number = _answer_number(str(question.get("id") or ""))
    pages = [int(value) for value in question.get("a_pages") or [] if value]
    if not pages:
        raise VisionInfrastructureError(f"题目缺少答案页: {row['source_uid']}")
    q_page = int(question.get("page") or (question.get("q_pages") or [0])[0] or 0)
    # a_pages 经常从题干页起算一整段；必须先搜题干页之后、且带“16. C”的答案行。
    ordered_pages = [page for page in pages if page > q_page] + [
        page for page in pages if page <= q_page
    ]
    for page in ordered_pages:
        ocr_path = next(
            (
                course.ocr_dir / f"page_{page:03d}.json"
                for course in COURSES
                if course.key == course_key
            ),
            None,
        )
        payload = _load_json(ocr_path, {}) if ocr_path else {}
        blocks = payload.get("blocks", []) if isinstance(payload, dict) else []
        number_re = rf"(?<!\d){re.escape(number)}\s*[.)、．]"
        all_matches = [
            block for block in blocks if re.search(number_re, str(block.get("text") or ""))
        ]
        # 同一答案页可能先出现“综合应用题 01”，必须优先选带选择字母的
        # “01. C”答案行，否则裁图会落到错误题型。
        choice_matches = [
            block
            for block in all_matches
            if re.search(rf"{number_re}\s*[A-F](?:\b|$)", str(block.get("text") or ""), re.I)
        ]
        if choice_matches:
            matches = choice_matches
        elif page > q_page:
            matches = all_matches
        else:
            continue
        if not matches:
            continue
        start = min(matches, key=lambda block: float(block.get("y0") or 0))
        start_y = float(start.get("y0") or 0)
        later = [
            block
            for block in blocks
            if float(block.get("y0") or 0) > start_y + 2
            and re.search(r"(?<!\d)\d{1,3}\s*[.)、．]", str(block.get("text") or ""))
        ]
        end_y = min((float(block.get("y0") or 0) for block in later), default=None)
        image = _page_image(course_key, page)
        with Image.open(image) as source:
            width, height = source.size
        bottom = end_y if end_y is not None else height - 20
        return _crop_box(
            image,
            (20, start_y, width - 20, bottom),
            out_dir / f"{row['source_uid'].replace(':', '_')}-answer.png",
            margin,
        )
    raise VisionInfrastructureError(f"答案题号无法定位: {row['source_uid']} / {number}")


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    size = max(1, int(size or 1))
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _prompt(row: dict[str, Any]) -> str:
    return _batch_prompt([row])


def _batch_prompt(rows: list[dict[str, Any]]) -> str:
    uids = "、".join(row["source_uid"] for row in rows)
    return (
        "你是原书读图校验器。下面有多道题，每题两张图：先题目区后答案解析区。"
        "只根据附带的原书裁图提取文字，禁止推理、改写、补全或参考题库。"
        "返回一个 JSON 对象，不要 Markdown："
        '{"items":[{"uid":"题目UID","content":"原书题干","options":{"A":"...","B":"..."},'
        '"answer_choice":"C","explanation":"原书解析原文","requires_image":false,"confidence":0.0}]}。'
        f"必须覆盖全部 {len(rows)} 道题，UID 为：{uids}。"
        "若某题看不清，该题字段留空并降低 confidence。"
    )


def _parse_json_value(content: Any) -> Any:
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisionInfrastructureError(f"Kimi 返回非 JSON: {text[:200]}") from exc


def _parse_response(content: Any) -> dict[str, Any]:
    value = _parse_json_value(content)
    if not isinstance(value, dict):
        raise VisionInfrastructureError("Kimi JSON 根节点不是对象")
    return value


def index_batch_results(value: Any, expected_uids: list[str]) -> dict[str, dict[str, Any]]:
    """把模型返回的数组/对象按 UID 对齐；缺 uid 时按顺序补位。"""
    rows: list[Any] | None = None
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        for key in ("items", "results", "questions"):
            if isinstance(value.get(key), list):
                rows = value[key]
                break
        if rows is None and any(
            key in value for key in ("content", "answer_choice", "uid", "source_uid")
        ):
            rows = [value]
    if not isinstance(rows, list):
        raise VisionInfrastructureError("Kimi JSON 不是题目数组")
    expected_set = set(expected_uids)
    indexed: dict[str, dict[str, Any]] = {}
    leftovers: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid") or item.get("source_uid") or "").strip()
        if uid in expected_set and uid not in indexed:
            indexed[uid] = item
        else:
            leftovers.append(item)
    for uid in expected_uids:
        if uid in indexed:
            continue
        if leftovers:
            indexed[uid] = leftovers.pop(0)
    return indexed


def _max_tokens_for(count: int) -> int:
    configured = int(os.getenv("KIMI_VISION_MAX_TOKENS", "2048"))
    return max(configured, 768 * max(1, count))


def _thinking_disabled() -> bool:
    return os.getenv("KIMI_CODE_THINKING", "disabled").lower() in {
        "disabled",
        "off",
        "false",
        "none",
    }


def _kimi_request(model: str, content: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出严格 JSON。"},
            {"role": "user", "content": content},
        ],
        "max_tokens": max_tokens,
    }
    # Coding Plan K2.7 固定 temperature=1；关闭 thinking 路由到 K2.6，
    # 该路由固定 temperature=0.6；Open Platform K2.6 固定接受 0。
    if model.startswith("kimi-for-coding"):
        request["temperature"] = 0.6 if _thinking_disabled() else 1
    else:
        request["temperature"] = 0
    if model.startswith("kimi-for-coding") and _thinking_disabled():
        request["extra_body"] = {"thinking": {"type": "disabled"}}
    return request


def _create_completion(client: Any, request: dict[str, Any]) -> Any:
    try:
        return client.chat.completions.create(**request, response_format={"type": "json_object"})
    except Exception:
        # 某些 Kimi 账户/模型版本尚未开放 response_format；仍要求并严格解析
        # prompt 中的 JSON，不能因为供应商能力差异误判为题目冲突。
        return client.chat.completions.create(**request)


def _message_content(response: Any) -> Any:
    message = response.choices[0].message
    return getattr(message, "content", message.get("content") if isinstance(message, dict) else "")


def call_kimi_batch(
    client: Any,
    model: str,
    rows: list[dict[str, Any]],
    crops_by_uid: dict[str, list[Crop]],
    retries: int = 3,
) -> dict[str, dict[str, Any]]:
    if not rows:
        return {}
    last: Exception | None = None
    expected = [row["source_uid"] for row in rows]
    max_tokens = _max_tokens_for(len(rows))
    for attempt in range(retries):
        try:
            content: list[dict[str, Any]] = []
            for row in rows:
                crops = crops_by_uid[row["source_uid"]]
                content.append({"type": "text", "text": f"【题目 {row['source_uid']} 题目区】"})
                content.append(
                    {"type": "image_url", "image_url": {"url": _data_url(crops[0].path)}}
                )
                content.append({"type": "text", "text": f"【题目 {row['source_uid']} 答案解析区】"})
                content.append(
                    {"type": "image_url", "image_url": {"url": _data_url(crops[1].path)}}
                )
            content.append({"type": "text", "text": _batch_prompt(rows)})
            response = _create_completion(client, _kimi_request(model, content, max_tokens))
            return index_batch_results(_parse_json_value(_message_content(response)), expected)
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise VisionInfrastructureError(f"{model} 批量调用失败: {last}") from last


def call_kimi(
    client: Any, model: str, row: dict[str, Any], crops: list[Crop], retries: int = 3
) -> dict[str, Any]:
    indexed = call_kimi_batch(client, model, [row], {row["source_uid"]: crops}, retries=retries)
    result = indexed.get(row["source_uid"])
    if not isinstance(result, dict):
        raise VisionInfrastructureError(f"{model} 未返回该题")
    return result


def _model_value(result: dict[str, Any], field: str) -> Any:
    if field == "answer.choice":
        return canonical_choice(
            result.get("answer_choice") or (result.get("answer") or {}).get("choice")
        )
    value = (
        result.get(field)
        if field in result
        else (result.get("answer") or {}).get(field.split(".")[-1])
    )
    return canonical_content(value) if field == "content" else value


def _same_field(left: Any, right: Any, field: str) -> bool:
    if field == "options":
        l = {str(key).upper(): canonical_text(value) for key, value in (left or {}).items()}
        r = {str(key).upper(): canonical_text(value) for key, value in (right or {}).items()}
        return l == r
    if field == "answer.choice":
        return canonical_choice(left) == canonical_choice(right)
    if field == "content":
        return canonical_content(left) == canonical_content(right)
    return canonical_text(left) == canonical_text(right)


def compare_results(
    row: dict[str, Any], first: dict[str, Any], second: dict[str, Any], fresh_choice: str | None
) -> dict[str, Any]:
    if (
        min(float(first.get("confidence") or 0), float(second.get("confidence") or 0))
        < MIN_CONFIDENCE
    ):
        raise VisionConflictError("双模型置信度不足")
    question = row["question"]
    answer = question.get("answer") if isinstance(question.get("answer"), dict) else {}
    fields = ("content", "options", "answer.choice", "explanation")
    consensus: dict[str, Any] = {}
    for field in fields:
        left, right = _model_value(first, field), _model_value(second, field)
        if not _same_field(left, right, field):
            raise VisionConflictError(f"双模型字段冲突: {field}")
        if field == "options" and question.get("options") and not left:
            raise VisionConflictError("双模型未提取出选项")
        expected_source = (
            question.get("content")
            if field == "content"
            else (question.get("answer") or {}).get("explanation")
        )
        if field in {"content", "explanation"} and expected_source and not canonical_text(left):
            raise VisionConflictError(f"双模型未提取出{field}")
        if field == "answer.choice" and not canonical_choice(left):
            raise VisionConflictError("双模型未提取出答案")
        consensus[field] = left
    image_left = bool(first.get("requires_image"))
    image_right = bool(second.get("requires_image"))
    if image_left != image_right:
        raise VisionConflictError("配图需求判断冲突")
    if image_left != bool(question.get("has_image") or question.get("image_ref")):
        raise VisionConflictError("原书配图与题库配图状态不一致")
    patch: dict[str, Any] = {}
    if not _same_field(consensus["content"], question.get("content"), "content"):
        patch["content"] = consensus["content"]
    if not _same_field(consensus["options"], question.get("options"), "options"):
        patch["options"] = consensus["options"]
    if not _same_field(consensus["answer.choice"], answer.get("choice"), "answer.choice"):
        patch.setdefault("answer", {})["choice"] = canonical_choice(consensus["answer.choice"])
    if not _same_field(consensus["explanation"], answer.get("explanation"), "explanation"):
        patch.setdefault("answer", {})["explanation"] = consensus["explanation"]
    return {"status": "auto_fixed" if patch else "verified", "patch": patch, "consensus": consensus}


def _load_state() -> dict[str, Any]:
    value = _load_json(STATE_PATH, {})
    return value if isinstance(value, dict) else {}


def _load_patches() -> dict[str, Any]:
    value = _load_json(PATCH_PATH, {})
    return value if isinstance(value, dict) else {}


def apply_patches() -> int:
    patches = _load_patches().get("items", [])
    applied = 0
    for course in COURSES:
        path = Path(course.out_json)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for chapter in data.get("chapters", []):
            minor = str(chapter.get("name") or chapter.get("topic_title") or "未知章节")
            for question in chapter.get("questions", []):
                uid = source_uid(course.key, minor, str(question.get("id") or ""))
                item = next(
                    (
                        item
                        for item in patches
                        if item.get("source_uid") == uid
                        and item.get("source_hash") == source_hash(question)
                    ),
                    None,
                )
                if not item:
                    continue
                expected = item.get("patch") or {}
                for field in ("content", "options"):
                    if field in expected:
                        question[field] = expected[field]
                        changed = True
                if "answer" in expected:
                    question.setdefault("answer", {}).update(expected["answer"])
                    changed = True
                applied += 1
        if changed:
            write_json_atomic(path, data, indent=2, ensure_ascii=False)
    return applied


def refresh_verified_for_patches(state: dict[str, Any]) -> int:
    """补丁落地后，把已通过题的 hash 改成修补后的值，避免下轮又抽到刚修过的题。"""
    verified = state.setdefault("verified", {})
    patched = {
        str(item.get("source_uid"))
        for item in _load_patches().get("items", [])
        if item.get("source_uid")
    }
    if not verified or not patched:
        return 0
    updated = 0
    for course in COURSES:
        path = Path(course.out_json)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for chapter in data.get("chapters", []):
            minor = str(chapter.get("name") or chapter.get("topic_title") or "未知章节")
            for question in chapter.get("questions", []):
                uid = source_uid(course.key, minor, str(question.get("id") or ""))
                if uid not in verified or uid not in patched:
                    continue
                current = source_hash(question)
                if verified[uid] != current:
                    verified[uid] = current
                    updated += 1
    return updated


def _append_regressions(items: list[dict[str, Any]]) -> None:
    path = MATH_BANK_DIR / "quality_regressions.json"
    current = _load_json(path, [])
    if isinstance(current, dict):
        rows = current.setdefault("items", [])
    else:
        rows = current if isinstance(current, list) else []
    existing = {
        (row.get("source_uid"), json.dumps(row.get("expected"), ensure_ascii=False, sort_keys=True))
        for row in rows
        if isinstance(row, dict)
    }
    for item in items:
        expected = item.get("patch") or {}
        key = (item.get("source_uid"), json.dumps(expected, ensure_ascii=False, sort_keys=True))
        if key in existing:
            continue
        rows.append(
            {
                "source_uid": item["source_uid"],
                "expected": expected,
                "reason": "vision_dual_consensus",
                "evidence_sha256": item.get("evidence_sha256"),
            }
        )
        existing.add(key)
    write_json_atomic(
        path, current if isinstance(current, dict) else rows, indent=2, ensure_ascii=False
    )


def _write_hold(uids: set[str], reason: str) -> None:
    current = _load_json(HOLD_PATH, {})
    existing = set(current.get("source_uids", [])) if isinstance(current, dict) else set()
    all_uids = sorted(existing | uids)
    payload = current if isinstance(current, dict) else {}
    payload.update({"schema_version": 1, "source_uids": all_uids, "vision_reason": reason})
    write_json_atomic(HOLD_PATH, payload, indent=2, ensure_ascii=False)


def _accuracy(records: list[dict[str, Any]], selection: str | None = None) -> dict[str, Any]:
    """返回通过率；自动修正也算通过，隔离题不算通过。"""
    scoped = [
        record for record in records if selection is None or record.get("selection") == selection
    ]
    passed = sum(record.get("status") in PASS_STATUSES for record in scoped)
    total = len(scoped)
    return {"passed": passed, "total": total, "rate": round(passed / total, 4) if total else None}


def build_manifest(
    records: list[dict[str, Any]],
    state: dict[str, Any],
    status: str,
    models: tuple[str, str],
    base_url: str,
) -> dict[str, Any]:
    overall = _accuracy(records)
    rotation = _accuracy(records, "rotation")
    return {
        "schema_version": 1,
        "status": status,
        "round_id": state.get("round_id"),
        "per_chapter": DEFAULT_PER_CHAPTER,
        "models": list(models),
        "base_url": base_url,
        "records": records,
        "round_history": state.get("round_history", []),
        "summary": {
            "total": len(records),
            "verified": sum(record["status"] == "verified" for record in records),
            "auto_fixed": sum(record["status"] == "auto_fixed" for record in records),
            "held": sum(record["status"] == "held" for record in records),
            "accuracy": overall["rate"],
            "sample_accuracy": rotation["rate"],
            "sample_passed": rotation["passed"],
            "sample_total": rotation["total"],
            "timing": state.get("timing") or {},
        },
    }


def run_gate(
    *,
    per_chapter: int = DEFAULT_PER_CHAPTER,
    round_id: str | None = None,
    client_factory: Callable[[], Any] | None = None,
    fresh_ocr: bool = False,
    course_keys: set[str] | None = None,
    include_priority: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    full: bool = False,
    uids: set[str] | None = None,
) -> dict[str, Any]:
    api_key, base_url, models = _api_config()
    if not api_key and client_factory is None:
        raise VisionInfrastructureError(
            "未配置 ARK_API_KEY/DOUBAO_API_KEY 或 MOONSHOT_API_KEY，拒绝生成未核验发布包"
        )
    require_distinct_models(models)
    client = client_factory() if client_factory else OpenAI(api_key=api_key, base_url=base_url)
    t_round = time.perf_counter()
    # 每次 OCR 重建后先把已确认补丁重新套回源 JSON，避免 merge 覆盖修复。
    apply_patches()
    state = _load_state()
    refreshed = refresh_verified_for_patches(state)
    if refreshed:
        print(f"[vision] refreshed {refreshed} verified hashes after patches", flush=True)
    state["round_id"] = round_id or time.strftime("%Y-%m-%d")
    priority = _priority_uids()
    hold_uids = _held_uids()
    selected: list[dict[str, Any]] = []
    active_courses = [course for course in COURSES if not course_keys or course.key in course_keys]
    target_uids = set(uids) if uids is not None else None
    for course in active_courses:
        path = Path(course.out_json)
        if not path.is_file():
            raise VisionInfrastructureError(f"源题库缺失: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        grouped = _rows(course.key, data)
        for major_rows in grouped.values():
            if target_uids is not None:
                selected.extend(select_by_uids(major_rows, target_uids))
                continue
            if full:
                verified_state = state.setdefault("verified", {})
                selected.extend(select_full_candidates(major_rows, verified_state, hold_uids))
                continue
            rotation_rows = (
                major_rows
                if include_priority
                else [row for row in major_rows if row["source_uid"] not in priority]
            )
            if rotation_rows:
                selected.extend(
                    select_rotating(rotation_rows, state, per_chapter, state["round_id"])
                )
        if include_priority and not full and target_uids is None:
            for rows in grouped.values():
                selected.extend(
                    row for row in rows if row["source_uid"] in priority and row not in selected
                )
    if not selected:
        if full and target_uids is None:
            existing = _load_json(MANIFEST_PATH, {})
            if isinstance(existing, dict) and existing.get("status") in {
                "published",
                "verified",
                "verified_with_holds",
            }:
                return existing
        raise VisionInfrastructureError("没有可抽检题目")
    answer_choices: dict[str, str] = {}
    if fresh_ocr:
        by_course: dict[str, set[int]] = {}
        for row in selected:
            by_course.setdefault(row["course_key"], set()).update(
                int(page) for page in row["question"].get("a_pages") or [] if page
            )
        for course in active_courses:
            pages = sorted(by_course.get(course.key, set()))
            if not pages:
                continue
            run_fresh_ocr(course, pages, force=False)
            fresh_dir = CACHE_ROOT / course.key
            parsed = parse_group_answers(fresh_dir, tuple(pages))
            for row in selected:
                if row["course_key"] != course.key:
                    continue
                number = _answer_number(str(row["question"].get("id") or ""))
                answer_choices[row["source_uid"]] = parsed.get(number, "")
    records: list[dict[str, Any]] = []
    fixed: list[dict[str, Any]] = []
    held: set[str] = set()
    total_selected = len(selected)
    n_batches = (total_selected + batch_size - 1) // batch_size if batch_size else 0
    setup_s = time.perf_counter() - t_round
    print(
        f"[vision] setup={setup_s:.1f}s selected={total_selected} batches={n_batches} batch_size={batch_size}",
        flush=True,
    )
    timing: dict[str, Any] = {
        "setup_s": round(setup_s, 1),
        "api_s": 0.0,
        "crop_s": 0.0,
        "retry_batches": 0,
        "api_calls": 0,
    }
    # 一批多题只打两路盲审，避免每题单独两次请求。
    pair_pool = ThreadPoolExecutor(max_workers=2)
    completed = 0
    for batch_index, batch in enumerate(_chunks(selected, batch_size), 1):
        crop_dir = TEMP_ROOT / state["round_id"]
        pending = list(batch)
        last_conflicts: dict[str, Exception] = {}
        crops_used: dict[str, list[Crop]] = {}
        decisions: dict[str, dict[str, Any]] = {}
        batch_crop = 0.0
        batch_api = 0.0
        attempts = 0
        t_batch = time.perf_counter()
        for margin in (28, 64):
            if not pending:
                break
            t_crop = time.perf_counter()
            crops_by_uid: dict[str, list[Crop]] = {}
            for row in pending:
                crops = [
                    question_crop(row["course_key"], row, crop_dir, margin),
                    answer_crop(row["course_key"], row, crop_dir, margin),
                ]
                crops_by_uid[row["source_uid"]] = crops
                crops_used[row["source_uid"]] = crops
            batch_crop += time.perf_counter() - t_crop
            t_api = time.perf_counter()
            first_future = pair_pool.submit(
                call_kimi_batch, client, models[0], pending, crops_by_uid
            )
            second_future = pair_pool.submit(
                call_kimi_batch, client, models[1], pending, crops_by_uid
            )
            first_map = first_future.result()
            second_map = second_future.result()
            batch_api += time.perf_counter() - t_api
            attempts += 1
            timing["api_calls"] += 2
            still: list[dict[str, Any]] = []
            for row in pending:
                uid = row["source_uid"]
                try:
                    if uid not in first_map or uid not in second_map:
                        raise VisionConflictError("双模型未返回该题")
                    decisions[uid] = compare_results(
                        row, first_map[uid], second_map[uid], answer_choices.get(uid)
                    )
                    last_conflicts.pop(uid, None)
                except VisionConflictError as exc:
                    last_conflicts[uid] = exc
                    if retryable_conflict(exc):
                        still.append(row)
            pending = still
        timing["crop_s"] += batch_crop
        timing["api_s"] += batch_api
        if attempts > 1:
            timing["retry_batches"] += 1
        batch_held = sum(1 for row in batch if row["source_uid"] not in decisions)
        print(
            f"[vision] batch {batch_index}/{n_batches} n={len(batch)} crop={batch_crop:.1f}s "
            f"api={batch_api:.1f}s attempts={attempts} held={batch_held} wall={time.perf_counter() - t_batch:.1f}s",
            flush=True,
        )
        for row in batch:
            uid = row["source_uid"]
            decision = decisions.get(uid)
            if decision is None:
                held.add(uid)
                record = {
                    "source_uid": uid,
                    "course_key": row["course_key"],
                    "chapter": row["major_chapter"],
                    "question_id": row["question"].get("id"),
                    "source_hash": source_hash(row["question"]),
                    "status": "held",
                    "selection": "priority" if uid in priority else "rotation",
                    "reason": str(last_conflicts.get(uid) or "双模型无法确认"),
                }
            else:
                crops = crops_used[uid]
                patched_question = apply_patch_to_question(row["question"], decision.get("patch"))
                record = {
                    "source_uid": uid,
                    "course_key": row["course_key"],
                    "chapter": row["major_chapter"],
                    "question_id": row["question"].get("id"),
                    "source_hash": source_hash(row["question"]),
                    "verified_hash": source_hash(patched_question),
                    "status": decision["status"],
                    "selection": "priority" if uid in priority else "rotation",
                    "models": list(models),
                    "evidence_sha256": [crop.sha256 for crop in crops],
                    "fields": decision["consensus"],
                }
                if decision["patch"]:
                    fixed.append({**record, "patch": decision["patch"]})
                state.setdefault("verified", {})[uid] = source_hash(
                    apply_patch_to_question(row["question"], decision.get("patch"))
                )
            records.append(record)
            completed += 1
            print(f"[vision] {completed}/{total_selected} {uid} -> {record['status']}", flush=True)
        # 全量模式按批次落盘，API 中断后从上一批继续；running 状态不参与发布。
        if full:
            state["last_records"] = records
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(STATE_PATH, state, indent=2, ensure_ascii=False)
    pair_pool.shutdown(wait=True)
    timing["crop_s"] = round(timing["crop_s"], 1)
    timing["api_s"] = round(timing["api_s"], 1)
    timing["wall_s"] = round(time.perf_counter() - t_round, 1)
    print(
        f"[vision] timing setup={timing['setup_s']}s crop={timing['crop_s']}s "
        f"api={timing['api_s']}s retry_batches={timing['retry_batches']} "
        f"api_calls={timing['api_calls']} wall={timing['wall_s']}s",
        flush=True,
    )
    if fixed:
        patches = _load_patches()
        items = patches.setdefault("items", [])
        for item in fixed:
            items[:] = [
                old
                for old in items
                if not (
                    old.get("source_uid") == item["source_uid"]
                    and old.get("source_hash") == item["source_hash"]
                )
            ]
            items.append(item)
        PATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(PATCH_PATH, patches, indent=2, ensure_ascii=False)
        _append_regressions(fixed)
        apply_patches()
    if held:
        _write_hold(held, "vision_conflict")
        # 冲突是题目级隔离，不是 API 故障；门禁允许下一阶段发布剔除这些题。
    state["last_records"] = records
    state["timing"] = timing
    round_summary = build_manifest(records, state, "", models, base_url)["summary"]
    history = [
        row for row in state.get("round_history", []) if row.get("round_id") != state["round_id"]
    ]
    history.append(
        {
            "round_id": state["round_id"],
            "sample_accuracy": round_summary["sample_accuracy"],
            "sample_passed": round_summary["sample_passed"],
            "sample_total": round_summary["sample_total"],
            "accuracy": round_summary["accuracy"],
            "total": round_summary["total"],
        }
    )
    state["round_history"] = history
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(STATE_PATH, state, indent=2, ensure_ascii=False)
    manifest = build_manifest(
        records,
        state,
        "verified"
        if not any(record["status"] == "held" for record in records)
        else "verified_with_holds",
        models,
        base_url,
    )
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(MANIFEST_PATH, manifest, indent=2, ensure_ascii=False)
    return manifest


def summarize_round(records: list[dict[str, Any]]) -> dict[str, Any]:
    """按本轮样本归纳错误类型，供全库审核和下轮抽样使用。"""
    rotation = [record for record in records if record.get("selection") == "rotation"]
    scoped = rotation or records
    held = [record for record in scoped if record.get("status") == "held"]
    fixed = [record for record in scoped if record.get("status") == "auto_fixed"]
    verified = [record for record in scoped if record.get("status") == "verified"]
    reasons = Counter(str(record.get("reason") or "unknown") for record in held)
    chapter_holds = Counter(
        f"{record.get('course_key')}/{record.get('chapter')}" for record in held
    )
    patch_fields: Counter[str] = Counter()
    for item in _load_patches().get("items", []):
        if not isinstance(item, dict) or item.get("source_uid") not in {
            record.get("source_uid") for record in fixed
        }:
            continue
        patch = item.get("patch") or {}
        for field in ("content", "options"):
            if field in patch:
                patch_fields[field] += 1
        if isinstance(patch.get("answer"), dict):
            patch_fields.update(f"answer.{key}" for key in patch["answer"])
    digest = {
        "sample_total": len(scoped),
        "verified": len(verified),
        "auto_fixed": len(fixed),
        "held": len(held),
        "hold_reasons": dict(reasons.most_common()),
        "hold_chapters": dict(chapter_holds.most_common(12)),
        "auto_fixed_fields": dict(patch_fields.most_common()),
        "held_examples": [
            {"source_uid": record.get("source_uid"), "reason": record.get("reason")}
            for record in held[:12]
        ],
    }
    print("[vision] round error summary:", flush=True)
    print(json.dumps(digest, ensure_ascii=False, indent=2), flush=True)
    return digest


def audit_bank_after_round(records: list[dict[str, Any]]) -> dict[str, Any]:
    """根据本轮错误，先落补丁再扫描全库结构性缺陷；不调用视觉 API。"""
    applied = apply_patches()
    structural: set[str] = set()
    scanned = 0
    for course in COURSES:
        path = Path(course.out_json)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        scanned += sum(
            1
            for _chapter, _question in (
                (chapter, question)
                for chapter in data.get("chapters", [])
                for question in chapter.get("questions", [])
            )
            if "选择" in str(_question.get("type") or "")
        )
        structural.update(collect_hold_uids(course.key, data))
    current = _load_json(HOLD_PATH, {})
    existing = set(current.get("source_uids", [])) if isinstance(current, dict) else set()
    vision_held = {
        str(record.get("source_uid"))
        for record in records
        if record.get("status") == "held" and record.get("source_uid")
    }
    merged = sorted(existing | structural | vision_held)
    payload = current if isinstance(current, dict) else {}
    payload.update(
        {
            "schema_version": payload.get("schema_version") or 1,
            "source_uids": merged,
            "vision_reason": "vision_conflict_then_structural_audit",
            "last_bank_audit": {
                "scanned_choices": scanned,
                "patches_applied": applied,
                "structural_holds": len(structural),
                "new_structural_holds": len(structural - existing),
                "vision_holds": len(vision_held),
                "hold_total": len(merged),
            },
        }
    )
    write_json_atomic(HOLD_PATH, payload, indent=2, ensure_ascii=False)
    report = payload["last_bank_audit"]
    print("[vision] full-bank audit:", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


def export_rotation_sample(
    *,
    per_chapter: int = DEFAULT_PER_CHAPTER,
    round_id: str | None = None,
    course_keys: set[str] | None = None,
    include_priority: bool = True,
) -> dict[str, Any]:
    """抽本章轮换样本并裁原书图，不调用任何视觉 API。"""
    apply_patches()
    state = _load_state()
    refreshed = refresh_verified_for_patches(state)
    state["round_id"] = round_id or time.strftime("%Y-%m-%d")
    priority = _priority_uids()
    selected: list[dict[str, Any]] = []
    active_courses = [course for course in COURSES if not course_keys or course.key in course_keys]
    for course in active_courses:
        path = Path(course.out_json)
        if not path.is_file():
            raise VisionInfrastructureError(f"源题库缺失: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        grouped = _rows(course.key, data)
        for major_rows in grouped.values():
            rotation_rows = (
                major_rows
                if include_priority
                else [row for row in major_rows if row["source_uid"] not in priority]
            )
            if rotation_rows:
                selected.extend(
                    select_rotating(rotation_rows, state, per_chapter, state["round_id"])
                )
        if include_priority:
            for rows in grouped.values():
                selected.extend(
                    row for row in rows if row["source_uid"] in priority and row not in selected
                )
    if not selected:
        raise VisionInfrastructureError("没有可抽检题目")
    crop_dir = TEMP_ROOT / state["round_id"] / "crops"
    items: list[dict[str, Any]] = []
    for index, row in enumerate(selected, 1):
        question = row["question"]
        qcrop = question_crop(row["course_key"], row, crop_dir)
        acrop = answer_crop(row["course_key"], row, crop_dir)
        answer = question.get("answer") if isinstance(question.get("answer"), dict) else {}
        items.append(
            {
                "source_uid": row["source_uid"],
                "course_key": row["course_key"],
                "chapter": row["major_chapter"],
                "question_id": question.get("id"),
                "source_hash": source_hash(question),
                "question_crop": str(qcrop.path),
                "answer_crop": str(acrop.path),
                "has_image": bool(question.get("has_image") or question.get("image_ref")),
                "bank": {
                    "content": question.get("content"),
                    "options": question.get("options"),
                    "answer.choice": answer.get("choice"),
                    "explanation": answer.get("explanation"),
                },
            }
        )
        print(f"[vision] export {index}/{len(selected)} {row['source_uid']}", flush=True)
    worklist = {
        "round_id": state["round_id"],
        "per_chapter": per_chapter,
        "refreshed_hashes": refreshed,
        "items": items,
    }
    out = TEMP_ROOT / state["round_id"] / "worklist.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out, worklist, indent=2, ensure_ascii=False)
    print(f"[vision] exported {len(items)} crops -> {out}", flush=True)
    return {
        "round_id": state["round_id"],
        "selected": len(items),
        "refreshed_hashes": refreshed,
        "worklist": str(out),
    }


def finalize_manifest() -> dict[str, Any]:
    manifest = _load_json(MANIFEST_PATH, {})
    if not isinstance(manifest, dict) or manifest.get("status") not in {
        "verified",
        "verified_with_holds",
    }:
        raise VisionInfrastructureError("缺少已通过视觉门禁的 manifest")
    manifest["published_hashes"] = {
        course.key: _sha256_file(MATH_BANK_DIR / f"data-{course.key}.json")
        for course in COURSES
        if (MATH_BANK_DIR / f"data-{course.key}.json").is_file()
    }
    manifest["status"] = "published"
    write_json_atomic(MANIFEST_PATH, manifest, indent=2, ensure_ascii=False)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-chapter", type=int, default=DEFAULT_PER_CHAPTER)
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="一次视觉调用打包的题目数"
    )
    parser.add_argument("--round", dest="round_id")
    parser.add_argument("--fresh-ocr", action="store_true", help="额外跑 GPU OCR（不参与通过判定）")
    parser.add_argument(
        "--no-fresh-ocr", action="store_true", help="兼容旧开关；默认已跳过 fresh OCR"
    )
    parser.add_argument(
        "--course",
        action="append",
        choices=[course.key for course in COURSES],
        help="仅用于局部冒烟；正式构建不要限制科目",
    )
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument(
        "--until-accuracy", action="store_true", help="继续轮换抽检，直到章节样本通过率严格高于阈值"
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="只根据已有 manifest 总结错误并审核全库，不调用视觉 API",
    )
    parser.add_argument(
        "--export-sample",
        action="store_true",
        help="只抽轮换样本并裁图，供本地读图；不调用视觉 API",
    )
    parser.add_argument("--accuracy-threshold", type=float, default=0.9)
    parser.add_argument("--max-rounds", type=int, default=10)
    parser.add_argument(
        "--rotation-only",
        action="store_true",
        help="只抽每章轮换样本；高风险题保留既有隔离，不重复计入本轮",
    )
    parser.add_argument(
        "--full", action="store_true", help="全量核对所有选择题，断点状态仍写入原有 manifest"
    )
    parser.add_argument(
        "--uids-file",
        type=Path,
        help="JSON 数组 of source_uid；仅核对这些 UID ∩ 发布选择题",
    )
    args = parser.parse_args()
    try:
        if args.finalize:
            result = finalize_manifest()
        elif args.export_sample:
            result = export_rotation_sample(
                per_chapter=args.per_chapter,
                round_id=args.round_id,
                course_keys=set(args.course or []),
                include_priority=not args.rotation_only,
            )
        elif args.audit_only:
            manifest = _load_json(MANIFEST_PATH, {})
            records = manifest.get("records", []) if isinstance(manifest, dict) else []
            if not isinstance(records, list) or not records:
                raise VisionInfrastructureError("缺少可审核的 quality-verification.json")
            result = {
                "summary": summarize_round(records),
                "bank_audit": audit_bank_after_round(records),
            }
        elif args.until_accuracy:
            if not 0 < args.accuracy_threshold < 1:
                raise VisionInfrastructureError("--accuracy-threshold 必须在 0 和 1 之间")
            if args.max_rounds < 1:
                raise VisionInfrastructureError("--max-rounds 必须至少为 1")
            if args.batch_size < 1:
                raise VisionInfrastructureError("--batch-size 必须至少为 1")
            base = args.round_id or time.strftime("%Y-%m-%d")
            result = None
            use_ocr = args.fresh_ocr and not args.no_fresh_ocr
            for index in range(1, args.max_rounds + 1):
                result = run_gate(
                    per_chapter=args.per_chapter,
                    round_id=f"{base}-r{index}",
                    fresh_ocr=use_ocr,
                    course_keys=set(args.course or []),
                    include_priority=not args.rotation_only,
                    batch_size=args.batch_size,
                )
                summary = result.get("summary", {})
                rate = summary.get("sample_accuracy")
                print(
                    f"[vision] round={index} sample_accuracy={rate} ({summary.get('sample_passed')}/{summary.get('sample_total')})",
                    flush=True,
                )
                timing = summary.get("timing") or {}
                if timing:
                    print(
                        f"[vision] round={index} time setup={timing.get('setup_s')}s crop={timing.get('crop_s')}s "
                        f"api={timing.get('api_s')}s retry_batches={timing.get('retry_batches')} "
                        f"api_calls={timing.get('api_calls')} wall={timing.get('wall_s')}s",
                        flush=True,
                    )
                digest = summarize_round(result.get("records") or [])
                result["error_summary"] = digest
                if rate is not None and rate > args.accuracy_threshold:
                    result["stop_reason"] = "sample_accuracy_above_threshold"
                    result["accuracy_threshold"] = args.accuracy_threshold
                    break
                print("[vision] below threshold; audit full bank before next rotation", flush=True)
                result["bank_audit"] = audit_bank_after_round(result.get("records") or [])
            else:
                result["stop_reason"] = "max_rounds_reached"
                result["accuracy_threshold"] = args.accuracy_threshold
        else:
            uids = load_uids_file(args.uids_file) if args.uids_file else None
            result = run_gate(
                per_chapter=args.per_chapter,
                round_id=args.round_id,
                fresh_ocr=args.fresh_ocr and not args.no_fresh_ocr,
                course_keys=set(args.course or []),
                include_priority=not args.rotation_only,
                batch_size=args.batch_size,
                full=args.full,
                uids=uids,
            )
    except VisionInfrastructureError as exc:
        print(f"[vision-gate] BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.get("summary", result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
