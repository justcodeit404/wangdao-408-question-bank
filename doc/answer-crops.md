# 答案区原书截图（answer_crops）

> 2026-09-12 试点数据结构，同日四科（ds/coa/net/os）全部铺开：2858 题 / 3221 张 / 96.5MB。

## 是什么

答案/解析区默认展示**原书 PDF 截图**（书版排版，无 OCR 错字、公式/代码/表格保真），
现有 OCR 文字解析保留在图下方。数据上只在每题 `answer.explanation` 开头插入一行：

```
答案图片：answer_crops/ds/page_009_X01_ans.jpg
```

三端渲染协议早已存在，均无需改渲染层：
- bank-408 SPA：`fillExplanation()`（app.js）按行拆分并内联渲染，点击放大
- platform-v2：导入服务原样拷贝 explanation，`AnswerExplanation` 渲染「答案图片」块（在文字上方）
- 小程序：`parseExplanationAssets` 同协议，随平台数据生效（无需发版）

## 生成管线

```bash
python scripts/gen_answer_crops.py --course ds --write-expl   # 全量：裁图 + 回写 explanation
python scripts/gen_answer_crops.py --course ds --dry-run      # 只看统计
python scripts/gen_answer_crops.py --course ds --qids X01,A03 # 单题调试
```

- 输入：`data/ocr/<key>/page_NNN.json`（OCR 块坐标 = 整页 PNG 像素坐标）+
  `output/questions_<key>.json`（小节 a_pages / 题号）+ `assets/pdf_images/<key>/page_NNN.png`
- 分段：小节答案页流式扫描，按答案头（`01. C` / `01.【解答】`）切分，跨页续行归属当前答案
  （比旧逐页解析更完整）；裁剪 x 取页内容列全宽（保插图/表格），y 按行并集 + padding，
  并对相邻答案段收口 padding、对文字下方的插图墨迹延展下边界（PIL 灰度 <185 视为墨迹）
- **TOC 节界封顶（重要）**：qa_pairs 的 a_pages 止于「下一节试题精选」，中间夹着下一节/下一章
  的知识点正文；旧逐页文字管线按页丢弃这些行，连续流却会把它们吞进最后一个答案（试点 ds
  曾因此裁出整页正文）。现在答案页流延伸到下一节首页为止（上一节答案常续到该页顶部，
  不能按整页砍），分段遇到 TOC 精确节号的标题行（如 `2.3 栈与队列`）即停，章首页另作硬封顶
- 输出：`math-bank/answer_crops/<key>/page_NNN_<QID>_ans[_pN].jpg`（JPEG q80，宽 ≤1000px）
- 抽查：`math-bank/answer-crop-review.html`（本地打开，点图 160% 放大）
- 幂等：重跑安全——旧 `answer_crops` 图片行整行替换，题目图片行不动

ds 试点结果：791/797 题出图（TOC 封顶修复后 919 张 / 29.8MB）；6 题无答案段回退文字
（2.2.3 A09、5.1.4 A04、6.2.6 A09、7.2.4 A06、8.4.3 A04、8.6.3 A04，
多为书内本就缺答案头或答案头 OCR 损坏）。

四科最终：ds 791/919 图、coa 672/740、net 636/716、os 759/846，共 2858 题 / 96.5MB；
coa 6.2.3 有 4 个重复答案头（书内两轮答案），与文字管线同为取最后一次，图文一致。

## 质量台账配合（重要）

- `question_hash` / `_record_matches_current`（quality_ledger.py）已改为剥离
  `answer_crops` 图片行（`stable_explanation`）——截图行不影响逐题验证状态。
- **不要随手全量重跑 `quality_ledger.py`**：纯文本管线无法复现增量累积的
  vision/page_review 状态（实测 v215 台账 2448 certified 重算只剩 1386）。
  改了 data-*.json 后用 `quality_ledger.py --refresh-hashes` 只刷
  `published_hashes` 并重派生 quality-hold / quality-verification，
  否则平台导入会报「质量隔离清单无效或已过期」。
- `build_all.py` 末尾已接入 `gen_answer_crops --write-expl` + ledger `--refresh-hashes`
  （必须在 cross_validate 之后——它对 explanation 做全等比对）。

## 平台侧

- `platform-v2/frontend` 与小程序 `lib/helpers.ts` 的 `bankAssetUrl` 已支持
  `answer_crops/<科目>/...` → `/banks/408/answer_crops/...`；`BANK_IMAGE_VERSION`
  与小程序版本号已同步递增。
- 平台/云端数据更新：重新执行题库导入（`POST /api/catalog/banks/408-cs408-<key>/import`，
  admin）或服务器上直接调 `import_bank(db, '408-cs408-ds', None)`；导入为
  source_uid upsert，做题进度不受影响（本机实测 234 条记录原样保留）。

## 已知局限

- 右栏插图比本段文字高、且底部越过下一段答案起点时，插图底部会被截断
  （如 5.1.4 X04 树状图最底一层）；竖版整宽裁剪无法两全，个案可用人工框覆盖扩展。
- 5.1.4 这类「答案头被 OCR 打坏」的小节，被坏的答案其截图缺失（文字解析可能
  并入了上一题，属既有数据问题，与本管线无关）。

## 铺开其余三科

2026-09-12 已全部铺开（四科同批 v217 上云）。若日后需重出（如管线改进后）：

```bash
python scripts/gen_answer_crops.py --course coa --write-expl   # net/os 同理
python scripts/quality_ledger.py --refresh-hashes
python scripts/bump_bank_version.py
# 重新导入对应平台题库 + pack/apply 上云
```
