"""练习视图的掌握度按钮：点当前状态只算确认，不清除原标记（源码级守门）。

真实故障：每日十题只抽「已掌握」的题，答题后弹出的「已掌握/不熟/不会」按钮既不
高亮当前状态，又直接走 setMastery 的「同值即取消」分支，点一下「已掌握」就把原
标记清掉，还写下墓碑让平台旧值不再回填。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "math-bank" / "app.js"


def _src() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _func_body(name: str) -> str:
    src = _src()
    start = src.index("function %s(" % name)
    end = src.index("\n}\n", start)
    return src[start:end]


def test_same_status_is_confirm_only():
    body = _func_body("applyPracticeMastery")
    guard = "getMastery(container._q) !== status"
    set_at = body.index("setMastery(container._q, status)")
    assert guard in body
    assert body.index(guard) < set_at


def test_practice_buttons_use_confirm_helper():
    body = _func_body("showPracticeMastery")
    assert "applyPracticeMastery(container, btn.dataset.mastery)" in body
    assert "setMastery(" not in body
    assert "btn.dataset.mastery === current" in body


def test_keyboard_shortcuts_use_confirm_helper():
    src = _src()
    start = src.index("if (e.key === '1' || e.key === '2' || e.key === '3')")
    block = src[start:start + 400]
    assert "applyPracticeMastery(container, map[e.key])" in block
    assert "setMastery(container._q, map[e.key])" not in block
