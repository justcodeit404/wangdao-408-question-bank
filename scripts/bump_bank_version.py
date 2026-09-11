#!/usr/bin/env python3
"""根据 math-bank/data.js 内容 hash 自动 bump 缓存版本戳。

若 data.js 的 SHA256 相对上次记录有变化，则 bump：
  - index.html: __BANK_DATA_VER__ 与所有 ?v=N
  - sw.js: CACHE_NAME 与 ?v=N
  - app.js: sw.js?v=N

记录写入 data/quality/data_js_hash.txt。
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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    data_js = BANK / "data.js"
    if not data_js.exists():
        print("data.js 不存在")
        sys.exit(1)

    new_hash = sha256(data_js)
    old_hash = HASH_FILE.read_text(encoding="utf-8").strip() if HASH_FILE.exists() else ""
    force = "--force" in sys.argv

    if not force and new_hash == old_hash:
        print("data.js 未变化，跳过 bump")
        return

    # 读当前版本
    html = (BANK / "index.html").read_text(encoding="utf-8")
    m = re.search(r"__BANK_DATA_VER__='(\d+)'", html)
    if not m:
        print("找不到 __BANK_DATA_VER__")
        sys.exit(1)
    old_v = int(m.group(1))
    new_v = old_v + 1

    # index.html
    html = re.sub(r"__BANK_DATA_VER__='\d+'", f"__BANK_DATA_VER__='{new_v}'", html)
    html = re.sub(r"\?v=\d+", f"?v={new_v}", html)
    (BANK / "index.html").write_text(html, encoding="utf-8")

    # sw.js
    sw = (BANK / "sw.js").read_text(encoding="utf-8")
    sw = re.sub(r"wd408-ui-v\d+", f"wd408-ui-v{new_v}", sw)
    sw = re.sub(r"\?v=\d+", f"?v={new_v}", sw)
    (BANK / "sw.js").write_text(sw, encoding="utf-8")

    # app.js
    app = (BANK / "app.js").read_text(encoding="utf-8")
    app = re.sub(r"sw\.js\?v=\d+", f"sw.js?v={new_v}", app)
    (BANK / "app.js").write_text(app, encoding="utf-8")

    HASH_FILE.write_text(new_hash + "\n", encoding="utf-8")
    print(f"缓存戳 {old_v} → {new_v}")


if __name__ == "__main__":
    main()
