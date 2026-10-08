import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='node 不在 PATH（工具链要求 Node 24）')
def test_stem_table_reflow_preserves_pipe_rows():
    """OCR 软换行重排不得破坏 markdown 管道表（2026-10-08 X13 表格丢行回归）。"""
    r = subprocess.run(
        [NODE, str(ROOT / 'tests' / 'test_stem_table_reflow.mjs')],
        cwd=ROOT, capture_output=True, encoding='utf-8', errors='replace',
    )
    assert r.returncode == 0, r.stdout + r.stderr
