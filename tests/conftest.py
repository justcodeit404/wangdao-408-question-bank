import sys
from pathlib import Path

# 让测试能找到 scripts/ 目录下的模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

# 避免 pytest 把 fixtures 里的 .txt/.json 当成测试文件收集
collect_ignore = [
    'fixtures/test_raw_sample.txt',
    'fixtures/test_raw_sample.json',
    'fixtures/test_raw.json',
    'fixtures/ds_test.json',
]
