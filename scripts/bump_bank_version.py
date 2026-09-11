#!/usr/bin/env python3
"""根据 math-bank/data-*.json 内容 hash 自动 bump 缓存版本戳。

data.js 只是加载器，真正变化的是 data-{ds,coa,net,os}.json。
若任一课程数据 SHA256 相对上次记录有变化，则 bump：
  - index.html: __BANK_DATA_VER__ 与所有 ?v=N
  - sw.js: CACHE_NAME 与 ?v=N
  - app.js: sw.js?v=N

记录写入 data/quality/data_js_hash.txt（四行 key=hash）。
若未变化则不 bump 并退出 0。

用法：
  python scripts/bump_bank_version.py          # 按需 bump
  python scripts/bump_bank_version.py --force  # 强制 +1
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "math-bank"
HASH_FILE = ROOT / "data" / "quality" / "data_js_hash.txt"
COURSE_KEYS = ("ds", "coa", "net", "os")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def content_hashes() -> dict[str, str]:
    out: dict[str, str] = {}
    for key in COURSE_KEYS:
        p = BANK / f"data-{key}.json"
        if p.exists():
            out[key] = sha256(p)
    return out


def read_old_hashes() -> dict[str, str]:
    if not HASH_FILE.exists():
        return {}
    old: dict[str, str] = {}
    text = HASH_FILE.read_text(encoding="utf-8").strip()
    # 兼容旧格式：单行纯 hash（曾只哈希 data.js）
    if text and "=" not in text and "\n" not in text:
        old["data.js"] = text
        return old
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        old[k.strip()] = v.strip()
    return old


def main() -> None:
    new_hashes = content_hashes()
    if not new_hashes:
        print("data-*.json 均不存在")
        sys.exit(1)

    old_hashes = read_old_hashes()
    force = "--force" in sys.argv
    changed = force or any(old_hashes.get(k) != v for k, v in new_hashes.items())

    if not changed:
        print("data-*.json 未变化，跳过 bump")
        return

    html = (BANK / "index.html").read_text(encoding="utf-8")
    m = re.search(r"__BANK_DATA_VER__='(\d+)'", html)
    if not m:
        print("找不到 __BANK_DATA_VER__")
        sys.exit(1)
    old_v = int(m.group(1))
    new_v = old_v + 1

    html = re.sub(r"__BANK_DATA_VER__='\d+'", f"__BANK_DATA_VER__='{new_v}'", html)
    html = re.sub(r"\?v=\d+", f"?v={new_v}", html)
    (BANK / "index.html").write_text(html, encoding="utf-8")

    sw = (BANK / "sw.js").read_text(encoding="utf-8")
    sw = re.sub(r"wd408-ui-v\d+", f"wd408-ui-v{new_v}", sw)
    sw = re.sub(r"\?v=\d+", f"?v={new_v}", sw)
    (BANK / "sw.js").write_text(sw, encoding="utf-8")

    app = (BANK / "app.js").read_text(encoding="utf-8")
    app = re.sub(r"sw\.js\?v=\d+", f"sw.js?v={new_v}", app)
    (BANK / "app.js").write_text(app, encoding="utf-8")

    HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(
        "".join(f"{k}={new_hashes[k]}\n" for k in sorted(new_hashes)),
        encoding="utf-8",
    )
    print(f"缓存戳 {old_v} → {new_v}")


if __name__ == "__main__":
    main()
