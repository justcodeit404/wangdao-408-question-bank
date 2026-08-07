# scripts/oneoff/

**ARCHIVE — 默认勿跑。** 一次性数据补全 / 调试脚本，历史使命已完成。
再跑 `python scripts/build_all.py` 会覆盖其结果。

若确需参考其中 OCR 逻辑：本 monorepo **禁止** `RapidOCR()` 裸调用。
统一 `tools/ocr_gpu.py` → `create_rapid_ocr()`（见根 `AGENTS.md` §9.9）。
下列脚本里若仍有裸 `RapidOCR()`，仅作归档参考，**不要直接执行**。

## 归档清单

| 脚本 | 用途 | 备注 |
| --- | --- | --- |
| `apply_option_patches.py` | 应用选择题选项补丁 | |
| `apply_os_bookmarks.py` | 给 OS 课程补充书签 | |
| `build_standalone.py` | 构建单文件离线 HTML | |
| `crop_missing_options.py` | 手动裁剪缺失选项图片 | |
| `debug_parser.py` | 单页解析调试 | |
| `extract_missing_answers.py` | 从答案区抽取缺失答案 | |
| `extract_missing_app_answers.py` | 抽取综合应用题答案 | |
| `fix_missing_options.py` | 补全选择题缺失选项 | |
| `fix_ocr_numerals.py` | 修正 OCR 数字误识别 | |
| `fix_x23_net.py` | 拆分计算机网络 X23 复合题 | 仅适用 27 王道《计算机网络》第 29 页 |
| `generate_correction_list.py` | 生成纠错清单 | |
| `generate_missing_options_review.py` | 生成待补选项清单 | |
| `regenerate_qa_pairs.py` | 从 TOC 重生成 qa_pairs | 已被 `parse_toc.py` 取代 |

## 何时再次执行

**默认情况下不要重新执行这些脚本**。如果 PDF 源文件 / OCR 输出有变更并需要完整重建，请走标准流程：

```bash
python scripts/run_ocr.py ...
python scripts/parse_toc.py ...
python scripts/build_all.py
```

只有当你确认上述流程在某道题上有遗漏时，才参考这些脚本作为参考实现，按需移植逻辑到 `fix_questions.py` 主流程里。