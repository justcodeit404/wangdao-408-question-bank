import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='node not installed')
def test_option_groups_render_and_answer():
    result = subprocess.run(
        [NODE, str(ROOT / 'tests' / 'test_option_groups.mjs')],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'test_option_groups: ok' in result.stdout
