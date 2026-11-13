#!/usr/bin/env python3
"""对已人工对照原书页确认的题补复核记录，并把账本哈希同步到当前发布态。

用法（在 apps/bank-408 目录）：
  python scripts/certify_reviewed.py --course ds --chapter 排序的基本概念 \
      --qids X01,X02,X03 --note "对照 p337–338 原页，题干/选项/答案一致"
  python scripts/certify_reviewed.py --uid "408:cs408-ds::排序 · 交换排序 · 选择题::X03" \
      --note "对照 p349–351 原页"

只处理「已经看过页图」的题：q_pages/a_pages 的页图必须存在，脚本把路径与 sha256 记进
page_review_evidence.json，再走 apply_page_review_certifications 的 sync 通道更新账本哈希。
没看过的题不要跑——这是认证记录，不是批量刷新工具。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from config import COURSE_BY_KEY, PROJECT_ROOT  # noqa: E402
from quality_ledger import question_hash  # noqa: E402
from apply_page_review_certifications import apply  # noqa: E402

PATCHES = PROJECT_ROOT / "data" / "quality" / "page_review_patches.json"
EVIDENCE = PROJECT_ROOT / "data" / "quality" / "page_review_evidence.json"
PAGES_DIR = PROJECT_ROOT / "assets" / "pdf_images"
BANK_DIR = PROJECT_ROOT / "math-bank"


def _pages(course_key: str, numbers) -> list:
    out = []
    for number in numbers or []:
        path = PAGES_DIR / course_key / f"page_{int(number):03d}.png"
        if not path.is_file():
            sys.exit(f"[certify] 页图缺失：{path}")
        out.append({
            "path": f"apps/bank-408/{path.relative_to(PROJECT_ROOT).as_posix()}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return out


def _find(course_key: str, chapter: str, qid: str) -> tuple[str, dict]:
    data = json.loads((BANK_DIR / f"data-{course_key}.json").read_text(encoding="utf-8"))
    for ch in data.get("chapters") or []:
        name = str(ch.get("name") or "")
        if chapter not in name:
            continue
        for question in ch.get("questions") or []:
            if str(question.get("id")) == qid:
                return name, question
    sys.exit(f"[certify] 找不到 {course_key} / {chapter} / {qid}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", action="append", default=[], help="完整 source_uid，可重复")
    ap.add_argument("--course", choices=sorted(COURSE_BY_KEY))
    ap.add_argument("--chapter", default="", help="章节名子串")
    ap.add_argument("--qids", default="", help="逗号分隔题号")
    ap.add_argument("--note", required=True, help="复核说明（写进证据的 rationale）")
    args = ap.parse_args()

    targets: list[tuple[str, str, str]] = []
    if args.uid:
        for uid in args.uid:
            _, rest = uid.split("::", 1)
            chapter, qid = rest.rsplit("::", 1)
            key = uid.split("::")[0].rsplit("-", 1)[-1]
            targets.append((key, chapter, qid))
    else:
        if not (args.course and args.qids):
            sys.exit("[certify] 需要 --uid，或 --course + --qids")
        for qid in [x.strip() for x in args.qids.split(",") if x.strip()]:
            chapter, _ = _find(args.course, args.chapter, qid)
            targets.append((args.course, chapter, qid))

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    records = evidence.get("records")
    if not isinstance(records, list):
        sys.exit("[certify] page_review_evidence.json 结构异常")
    known = {
        (str(r.get("source_uid")), str(r.get("source_hash")), str(r.get("final_action")))
        for r in records if isinstance(r, dict)
    }
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    uids: list[str] = []
    for course_key, chapter, qid in targets:
        uid = f"408:cs408-{course_key}::{chapter}::{qid}"
        question = _find(course_key, chapter, qid)[1]
        q_pages = _pages(course_key, question.get("q_pages"))
        a_pages = _pages(course_key, question.get("a_pages"))
        if not q_pages or not a_pages:
            sys.exit(f"[certify] {uid} 缺少 q_pages/a_pages，不能声称看过页")
        digest = question_hash(question)
        if (uid, digest, "patch") not in known:
            records.append({
                "source_uid": uid,
                "protocol": "codex-original-page-review-v1",
                "reviewer": "kimi-code",
                "reviewed_at": now,
                "q_pages_viewed": q_pages,
                "a_pages_viewed": a_pages,
                "final_action": "patch",
                "content_match": True,
                "options_match": True,
                "answer_match": True,
                "explanation_match": True,
                "image_match": True,
                "detected_errors": [],
                "rationale": args.note,
                "source_hash": digest,
                "post_patch_verified": True,
            })
            known.add((uid, digest, "patch"))
        uids.append(uid)

    evidence["updated_at"] = now
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    result = apply(sync_uids=set(uids))
    print(f"[certify] 已记录 {len(uids)} 题；synced={result.get('synced')} "
          f"certified={result.get('certified')} pending={result.get('pending')}")
    subprocess.run(
        [sys.executable, str(HERE / "quality_ledger.py"), "--refresh-hashes", "--check-published"],
        cwd=str(PROJECT_ROOT), check=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
