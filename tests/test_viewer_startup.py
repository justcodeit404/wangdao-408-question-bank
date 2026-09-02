"""408 viewer 启动不得阻塞在 11MB quality-ledger.json。"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "math-bank" / "app.js"
HOLD_JSON = ROOT / "math-bank" / "quality-hold.json"


def test_http_quality_gate_fetches_hold_not_full_ledger() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert "quality-hold.json" in js
    assert "fetch('quality-ledger.json'" not in js
    assert 'fetch("quality-ledger.json"' not in js
    assert "ledgerFromHoldList" in js


def test_hold_file_stays_tiny() -> None:
    assert HOLD_JSON.is_file()
    assert HOLD_JSON.stat().st_size < 200_000


def test_ledger_from_hold_list_marks_only_hold_uids() -> None:
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("function ledgerFromHoldList")
    end = src.index("\nasync function loadQualityLedger")
    hold = {
        "source_uids": [
            "408:cs408-ds::树与二叉树 · 选择题::X01",
            "408:cs408-os::进程与线程 · 选择题::X02",
        ]
    }
    script = (
        src[start:end]
        + "\n"
        + textwrap.dedent(
            f"""
            const hold = {json.dumps(hold, ensure_ascii=False)};
            const ledger = ledgerFromHoldList(hold);
            process.stdout.write(JSON.stringify({{
              holdX01: ledger.items['408:cs408-ds::树与二叉树 · 选择题::X01'],
              missing: ledger.items['408:cs408-ds::树与二叉树 · 选择题::X99'] || null,
              n: Object.keys(ledger.items).length,
            }}));
            """
        )
    )
    tmp = Path(__import__("tempfile").gettempdir()) / "bank408-hold-ledger-runner.js"
    tmp.write_text(script, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(tmp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            check=False,
        )
    finally:
        tmp.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"node failed ({proc.returncode}):\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        )
    out = json.loads(proc.stdout)
    assert out["holdX01"]["overall"] == "hold"
    assert out["missing"] is None
    assert out["n"] == 2
