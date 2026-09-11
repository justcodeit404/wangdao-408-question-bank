#!/usr/bin/env python3
"""随机抽样 certified 选择题，供对照原书 OCR 验收。

用法：
  python scripts/sample_choice_audit.py 20270117 20
  python scripts/sample_choice_audit.py --seed 20270117 --n 20 --json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "math-bank"
LEDGER_PATH = BANK / "quality-ledger.json"
COURSES = ("ds", "coa", "net", "os")


def load_pool() -> list[tuple[str, str, dict]]:
    if not LEDGER_PATH.exists():
        return []
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    items = ledger.get("items") or {}
    pool: list[tuple[str, str, dict]] = []
    for course in COURSES:
        path = BANK / f"data-{course}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for ch in data.get("chapters") or []:
            for q in ch.get("questions") or []:
                if q.get("type") != "选择题":
                    continue
                uid = f"408:cs408-{course}::{ch['name']}::{q['id']}"
                item = items.get(uid)
                if item and item.get("overall") == "certified":
                    pool.append((course, ch["name"], q))
    return pool


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("seed", nargs="?", type=int, default=20260912)
    p.add_argument("n", nargs="?", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--exclude-audited",
        action="store_true",
        help="排除 data/quality/random-audit-ledger.json 里已抽检过的题（跨模型去重）",
    )
    args = p.parse_args()

    pool = load_pool()
    if not pool:
        print("无 certified 选择题池")
        sys.exit(1)

    if args.exclude_audited:
        ledger_path = ROOT / "data" / "quality" / "random-audit-ledger.json"
        audited = set()
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            audited = {
                (e.get("course"), e.get("chapter"), e.get("qid"))
                for e in ledger.get("entries") or []
            }
        before = len(pool)
        pool = [(c, ch, q) for c, ch, q in pool if (c, ch, q.get("id")) not in audited]
        print(f"exclude-audited: {before - len(pool)}/{before} 已检题被排除")

    rng = random.Random(args.seed)
    picks = rng.sample(pool, min(args.n, len(pool)))

    if args.json:
        out = [
            {
                "course": c,
                "chapter": ch,
                "qid": q.get("id"),
                "page": q.get("page"),
                "content": q.get("content"),
                "options": q.get("options"),
                "choice": (q.get("answer") or {}).get("choice"),
            }
            for c, ch, q in picks
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print(f"SEED={args.seed} N={len(picks)} pool={len(pool)}")
    for course, chapter, q in picks:
        print("=" * 72)
        print(f"{course}|{chapter}|{q['id']}|p{q.get('page')}")
        print("C:", (q.get("content") or "").replace("\n", " / "))
        opts = q.get("options") or {}
        if opts:
            print("O:", opts)
        print("A:", (q.get("answer") or {}).get("choice"))


if __name__ == "__main__":
    main()
