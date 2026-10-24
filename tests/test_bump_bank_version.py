"""缓存戳：只改壳（styles.css）也要 bump，且 app.js 里的 sw.js?v=N 不能自激。"""

from __future__ import annotations

import bump_bank_version as b


def test_shell_change_alone_changes_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "BANK", tmp_path)
    (tmp_path / "styles.css").write_text("a{}", encoding="utf-8")
    before = b.content_hashes()["shell"]

    (tmp_path / "styles.css").write_text("b{}", encoding="utf-8")
    assert b.content_hashes()["shell"] != before


def test_shell_digest_ignores_version_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "BANK", tmp_path)
    (tmp_path / "styles.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "app.js").write_text("sw.js?v=1", encoding="utf-8")
    first = b.shell_digest()

    (tmp_path / "app.js").write_text("sw.js?v=2", encoding="utf-8")
    assert b.shell_digest() == first


def test_viewer_common_change_alone_changes_hash(tmp_path, monkeypatch):
    """index.html 给 /banks/common/* 打的同一个 ?v= 戳也要跟着共享脚本走。"""
    monkeypatch.setattr(b, "BANK", tmp_path)
    (tmp_path / "app.js").write_text("x", encoding="utf-8")
    vendor = tmp_path / "vendor" / "viewer-common"
    vendor.mkdir(parents=True)
    (vendor / "question-notes.js").write_text("v1", encoding="utf-8")
    before = b.content_hashes()["shell"]

    (vendor / "question-notes.js").write_text("v2", encoding="utf-8")
    assert b.content_hashes()["shell"] != before
