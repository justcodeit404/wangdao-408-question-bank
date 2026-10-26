"""408 viewer 启动不得阻塞在 11MB quality-ledger.json。

HTTP(S) quality-hold.json 拉取失败 → fail-closed（qualityVisible 全 false）。
file:// 保持空 items → 全部可见（本地预览）。
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "math-bank" / "app.js"
HOLD_JSON = ROOT / "math-bank" / "quality-hold.json"


def _extract_hold_helpers(src: str) -> str:
    """ledgerFromHoldList … qualityVisible（不含 badge）。"""
    start = src.index("function ledgerFromHoldList")
    end = src.index("\nfunction qualityBadgeHtml")
    return src[start:end]


def _extract_hold_helpers_with_badge(src: str) -> str:
    """ledgerFromHoldList … qualityBadgeHtml（含 badge，用于验证「未校验」角标）。"""
    start = src.index("function ledgerFromHoldList")
    end = src.index("\n// 上一趟还在加载时")
    return src[start:end]


def _run_node(script: str) -> dict:
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
    return json.loads(proc.stdout)


def test_http_quality_gate_fetches_hold_not_full_ledger() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert "quality-hold.json" in js
    assert "fetch('quality-ledger.json'" not in js
    assert 'fetch("quality-ledger.json"' not in js
    assert "ledgerFromHoldList" in js


def test_hold_file_stays_tiny() -> None:
    assert HOLD_JSON.is_file()
    assert HOLD_JSON.stat().st_size < 200_000


def test_no_keeping_progressive_view_on_http_hold_failure() -> None:
    """HTTP 失败不得再 'keeping progressive view'（放行刷题）。"""
    js = APP_JS.read_text(encoding="utf-8")
    assert "keeping progressive view" not in js


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
    out = _run_node(script)
    assert out["holdX01"]["overall"] == "hold"
    assert out["missing"] is None
    assert out["n"] == 2


def test_file_protocol_empty_hold_shows_all_questions() -> None:
    """file://：空 items，qualityVisible 为 true（本地预览放行）。"""
    src = APP_JS.read_text(encoding="utf-8")
    helpers = _extract_hold_helpers(src)
    script = (
        helpers
        + "\n"
        + textwrap.dedent(
            """
            let qualityLedger = null;
            const window = { location: { protocol: 'file:' }, __QUALITY_LEDGER__: undefined };
            function platformSourceUid(q) { return q.uid; }
            // stub fetch unused on file:
            globalThis.fetch = async () => { throw new Error('no fetch on file'); };

            (async () => {
              await loadQualityLedger();
              const q = { uid: '408:cs408-ds::any::X01' };
              process.stdout.write(JSON.stringify({
                ledgerNull: qualityLedger === null,
                hasFailClosed: !!(qualityLedger && qualityLedger.failClosed),
                itemsEmpty: qualityLedger && Object.keys(qualityLedger.items || {}).length === 0,
                visible: qualityVisible(q),
              }));
            })().catch((e) => {
              console.error(e);
              process.exit(1);
            });
            """
        )
    )
    out = _run_node(script)
    assert out["ledgerNull"] is False
    assert out["hasFailClosed"] is False
    assert out["itemsEmpty"] is True
    assert out["visible"] is True


def test_http_hold_fetch_failure_fail_closed_hides_all() -> None:
    """HTTP(S)：fetch 非 ok 或抛错 → fail-closed，qualityVisible 全 false。

    不得留下 qualityLedger=null 使 qualityVisible 默认真。
    """
    src = APP_JS.read_text(encoding="utf-8")
    helpers = _extract_hold_helpers(src)
    script = (
        helpers
        + "\n"
        + textwrap.dedent(
            """
            async function runCase(label, fetchImpl) {
              let qualityLedger = null;
              const window = { location: { protocol: 'http:' }, __QUALITY_LEDGER__: undefined };
              function platformSourceUid(q) { return q.uid; }
              globalThis.fetch = fetchImpl;
              // re-bind load path: qualityLedger is closed over — redefine helpers scope
              // The extracted functions close over outer `qualityLedger` / `window`.
              // We inject via eval of the same names in this scope by wrapping.
              return { label, note: 'see wrapper below' };
            }

            // Extracted functions reference free vars qualityLedger, window, platformSourceUid.
            // Provide them in this module scope:
            let qualityLedger = null;
            const window = { location: { protocol: 'http:' }, __QUALITY_LEDGER__: undefined };
            function platformSourceUid(q) { return q.uid; }

            async function scenario(fetchImpl) {
              qualityLedger = null;
              globalThis.fetch = fetchImpl;
              const ledger = await loadQualityLedger();
              const q = { uid: '408:cs408-ds::any::X99' };
              return {
                ledgerIsNull: ledger === null || qualityLedger === null,
                failClosed: !!(qualityLedger && qualityLedger.failClosed),
                visible: qualityVisible(q),
              };
            }

            (async () => {
              const notOk = await scenario(async () => ({ ok: false, status: 500 }));
              const threw = await scenario(async () => { throw new Error('network'); });
              // success empty hold still shows all (digested)
              qualityLedger = null;
              const emptyOk = await scenario(async () => ({
                ok: true,
                json: async () => ({ source_uids: [] }),
              }));
              process.stdout.write(JSON.stringify({ notOk, threw, emptyOk }));
            })().catch((e) => {
              console.error(e);
              process.exit(1);
            });
            """
        )
    )
    out = _run_node(script)
    for key in ("notOk", "threw"):
        case = out[key]
        assert case["ledgerIsNull"] is False, f"{key}: ledger must not stay null"
        assert case["failClosed"] is True, f"{key}: must set failClosed"
        assert case["visible"] is False, f"{key}: qualityVisible must be false"
    assert out["emptyOk"]["ledgerIsNull"] is False
    assert out["emptyOk"]["failClosed"] is False
    assert out["emptyOk"]["visible"] is True


def test_hold_questions_stay_visible_with_unverified_badge() -> None:
    """hold 题走原页兜底：不再隐藏，改打「未校验」角标（质量隔离角标已废弃）。"""
    src = APP_JS.read_text(encoding="utf-8")
    helpers = _extract_hold_helpers_with_badge(src)
    script = (
        helpers
        + "\n"
        + textwrap.dedent(
            """
            let qualityLedger = ledgerFromHoldList({
              source_uids: ['408:cs408-ds::树与二叉树 · 选择题::X01'],
            });
            const window = { location: { protocol: 'file:' }, __QUALITY_LEDGER__: undefined };
            function platformSourceUid(q) { return q.uid; }
            const held = { uid: '408:cs408-ds::树与二叉树 · 选择题::X01' };
            const clean = { uid: '408:cs408-ds::树与二叉树 · 选择题::X02' };
            process.stdout.write(JSON.stringify({
              heldVisible: qualityVisible(held),
              cleanVisible: qualityVisible(clean),
              heldBadge: qualityBadgeHtml(held),
              cleanBadge: qualityBadgeHtml(clean),
            }));
            """
        )
    )
    out = _run_node(script)
    assert out["heldVisible"] is True
    assert out["cleanVisible"] is True
    assert "未校验" in out["heldBadge"]
    assert "质量隔离" not in out["heldBadge"]
    assert out["cleanBadge"] == ""
