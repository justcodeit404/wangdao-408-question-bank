"""Shared utilities used across 408 bank scripts."""
import gzip
import json
import os
import tempfile
from pathlib import Path


def write_json_atomic(path, data, indent=2, ensure_ascii=False):
    """Write JSON atomically: temp file + os.replace.

    Prevents data corruption if the process is interrupted mid-write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f'{path.name}.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


def write_text_atomic(path, text, encoding='utf-8'):
    """Write text atomically: temp file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f'{path.name}.tmp')
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


def write_json_with_gz_atomic(path, data, ensure_ascii=False):
    """Write compact JSON atomically and pre-compress a .gz sibling."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    compact = json.dumps(data, ensure_ascii=ensure_ascii, separators=(',', ':'))
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f'{path.name}.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(compact)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise
    gz_dst = Path(str(path) + '.gz')
    gz_tmp = Path(str(gz_dst) + '.tmp')
    try:
        gz_tmp.write_bytes(gzip.compress(compact.encode('utf-8'), compresslevel=9))
        os.replace(gz_tmp, gz_dst)
    except Exception:
        try:
            gz_tmp.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        raise
    return compact
