"""旧弹层的对话框语义、焦点约束与关闭恢复。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "math-bank" / "app.js"
INDEX_HTML = ROOT / "math-bank" / "index.html"


def test_all_modals_have_connected_titles():
    html = INDEX_HTML.read_text(encoding="utf-8")
    modals = re.findall(r'<div class="modal-overlay"[^>]*>', html)
    assert len(modals) == 6
    for modal in modals:
        assert 'role="dialog"' in modal
        assert 'aria-modal="true"' in modal
        labelledby = re.search(r'aria-labelledby="([^"]+)"', modal)
        assert labelledby
        assert re.search(rf'id="{re.escape(labelledby.group(1))}"', html)


def test_zoom_shortcuts_do_not_close_the_underlying_modal():
    src = APP_JS.read_text(encoding="utf-8")
    assert "if (document.querySelector('.zoom-overlay')) return;" in src


def test_modal_focus_is_contained_and_restored():
    src = APP_JS.read_text(encoding="utf-8")
    logic = src[
        src.index("const modalFocusReturns = new Map()") : src.index("function getAvailableCourses")
    ]
    script = r"""
const assert = require('node:assert/strict');
function button(name) {
  return {
    name, isConnected: true,
    focus() { document.activeElement = this; },
    getClientRects() { return [{}]; },
  };
}
function modal(name) {
  const close = button(name + '-close');
  const next = button(name + '-next');
  const classes = new Set();
  return {
    close, next, classes,
    classList: {
      add: (value) => classes.add(value),
      remove: (value) => classes.delete(value),
      contains: (value) => classes.has(value),
    },
    querySelector: (selector) => selector === '.modal-close' ? close : null,
    querySelectorAll: () => [close, next],
    contains: (el) => el === close || el === next,
  };
}
const detail = modal('detail');
const trigger = button('trigger');
const app = { inert: false };
const document = {
  activeElement: trigger,
  body: { style: {} },
  getElementById: () => detail,
  querySelector: (selector) => selector === '.app' ? app : null,
  querySelectorAll: () => detail.classes.has('active') ? [detail] : [],
};
""" + logic + r"""
openModal('detailModal');
assert.equal(app.inert, true);
assert.equal(document.activeElement, detail.close);
trapModalTab({ key: 'Tab', shiftKey: true, preventDefault() {} });
assert.equal(document.activeElement, detail.next, 'Shift+Tab wraps to last control');
closeModalById('detailModal');
assert.equal(app.inert, false);
assert.equal(document.activeElement, trigger);
"""
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
