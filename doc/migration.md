# 迁移说明

## v2026-07-12：ds 课程数据路径统一

### 背景

`scripts/config.py` 中 ds 课程的历史命名与其它三门不一致：

| 项 | 旧（ds） | 旧（其它三门） | 新（统一） |
| --- | --- | --- | --- |
| `qa_json` | `data/qa/qa_pairs.json` | `data/qa/{key}_qa_pairs.json` | `data/qa/{key}_qa_pairs.json` |
| `toc_json` | `data/toc/toc.json` | `data/toc/toc_{key}.json` | `data/toc/toc_{key}.json` |

### 迁移步骤

如果你本地已有 `data/qa/qa_pairs.json` 或 `data/toc/toc.json`（即 ds 的旧路径），按下面重命名即可，其它三门不受影响：

```bash
mv data/qa/qa_pairs.json data/qa/ds_qa_pairs.json
mv data/toc/toc.json      data/toc/toc_ds.json
```

`data/` 目录整体在 `.gitignore` 中被排除，不在仓库版本控制内，因此无需 commit，仅本机操作。

### 重新生成（如尚未准备 ds 数据）

也可以直接按 `README.md` 流程重新跑：

```bash
python scripts/parse_toc.py "27王道《数据结构》高清带书签.pdf" data/qa/ds_qa_pairs.json
python scripts/regenerate_qa_pairs.py \
    --toc-json data/toc/toc_ds.json \
    --total-pages 397 \
    --output data/qa/ds_qa_pairs.json
```

### 影响范围

- `scripts/build_all.py`：从 `config.COURSES` 读取路径，自动跟随新路径，**无需改动**。
- 一次性脚本 `scripts/parse_toc.py`、`scripts/regenerate_qa_pairs.py`：默认输出路径已与新命名一致，**无需改动**。
- `tests/`：使用 `tmp_path` 合成 fixture，**不受影响**。