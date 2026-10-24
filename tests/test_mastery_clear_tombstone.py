"""408 掌握度「取消」后不被平台旧值回填（源码级守门）。

真实故障：手动点掉掌握度后，打开题库的自动 pull（prefer_weaker/fill）会把平台里
同一个旧值又填回来，用户感觉「清不掉」。修法是清空时记墓碑，回填遇到同一个值就跳过。
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


def test_clear_records_tombstone_before_writing_empty_mastery():
    body = _func_body("setMastery")
    assert "masteryClearedMap[key] = prev" in body
    assert body.index("masteryClearedMap[key] = prev") < body.index("entry.mastery = clearing ? '' : status")


def test_tombstone_persisted_and_loaded():
    src = _src()
    assert "const MASTERY_CLEARED_KEY = 'wd408_mastery_cleared'" in src
    assert "loadMasteryCleared();" in src
    assert "saveMasteryCleared();" in src


def test_pull_skips_same_value_but_respects_changed_value():
    body = _func_body("pullMasteryFromPlatform")
    skip_at = body.index("if (cleared === remote)")
    # 跳过分支必须在写入 statusMap 之前
    assert skip_at < body.index("entry.mastery = remote")
    assert "delete masteryClearedMap[itemKey]" in body
    # 撤墓碑后要把变化落盘
    assert "if (clearedDirty) saveMasteryCleared();" in body


def test_pull_has_no_duplicate_key_declaration():
    body = _func_body("pullMasteryFromPlatform")
    assert body.count("const key = questionKey(q)") == 0
