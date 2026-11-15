"""全屏看图的所有关闭路径都必须释放 window 监听器。"""

from __future__ import annotations

import subprocess
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "math-bank" / "app.js"


def test_zoom_close_releases_window_listeners():
    src = APP_JS.read_text(encoding="utf-8")
    zoom = src[src.index("function zoomImage(src)") : src.index("function openHelp")]
    script = r"""
const assert = require('node:assert/strict');
const window = {
  listeners: {},
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
  removeEventListener(name, fn) {
    this.listeners[name] = (this.listeners[name] || []).filter((item) => item !== fn);
  },
};
function makeElement() {
  return {
    listeners: {}, style: {}, children: [], removed: false,
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    appendChild(child) { this.children.push(child); },
    setAttribute() {},
    focus() {},
    remove() { this.removed = true; },
  };
}
function activeModal() { return null; }
const document = {
  body: { appendChild(el) { this.overlay = el; } },
  createElement: makeElement,
  querySelector: () => null,
};
function assertReleased() {
  for (const name of ['mousemove', 'mouseup', 'keydown']) {
    assert.equal((window.listeners[name] || []).length, 0, name + ' leaked');
  }
}
""" + zoom + r"""
zoomImage('first.png');
const first = document.body.overlay;
first.listeners.click[0]({ target: first });
assert.equal(first.removed, true);
assertReleased();
zoomImage('second.png');
const second = document.body.overlay;
window.listeners.keydown[0]({ key: 'Escape', preventDefault() {}, stopImmediatePropagation() {} });
assert.equal(second.removed, true);
assertReleased();
"""
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
