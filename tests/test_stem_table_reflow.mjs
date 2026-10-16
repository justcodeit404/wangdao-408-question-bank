// 回归：OCR 软换行重排（reflowOcrSoftWraps）不得把 markdown 管道表行与相邻行拼接，
// 导致渲染时表格丢行。事故：2026-10-08 coa 虚拟存储器 X13 TLB 表最后一行被拼进正文。
// 运行：node tests/test_stem_table_reflow.mjs（由 tests/test_stem_table_reflow.py 包装进 pytest）
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const appSrc = readFileSync(join(root, 'math-bank', 'app.js'), 'utf8');

// ---- 从 app.js 抽取被测函数（自包含集群，不依赖 DOM/window）----
function extractFunction(src, name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('function not found in app.js: ' + name);
  const braceStart = src.indexOf('{', start);
  let depth = 0;
  for (let i = braceStart; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error('unbalanced braces: ' + name);
}
function extractConstLine(src, name) {
  const m = src.match(new RegExp('^const ' + name + ' = .*;$', 'm'));
  if (!m) throw new Error('const not found in app.js: ' + name);
  return m[0];
}

const FN = ['looksLikeOcrCodeLine', 'isOcrStructuralBreak', 'joinOcrWrappedLines',
  'reflowOcrSoftWraps', 'splitRomanItems', 'normalizeDisplayText',
  'escapeHtml', 'isPipeRow', 'splitPipeRow', 'isSepRow', 'stemTableHtml'];
const CONST = ['OCR_CODE_LINE_RE', 'ASM_MNEMONIC', 'ASM_INSN_RE', 'ASM_CONT_RE', 'OCR_STRUCTURAL_START_RE', 'OCR_ASSET_CAPTION_RE', 'OCR_TABLE_HINT_RE'];
const bundle = CONST.map((c) => extractConstLine(appSrc, c)).join('\n') + '\n'
  + FN.map((n) => extractFunction(appSrc, n)).join('\n');
const { normalizeDisplayText, isPipeRow, splitPipeRow, isSepRow, stemTableHtml } = new Function(
  bundle + '\nreturn { normalizeDisplayText, isPipeRow, splitPipeRow, isSepRow, stemTableHtml };'
)();

// ---- 断言工具 ----
let failures = 0;
function assert(cond, msg) {
  if (!cond) { failures++; console.error('FAIL: ' + msg); }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const pipeRows = (text) => String(text || '').split('\n').filter(isPipeRow).map(splitPipeRow);

// 对一段题面文本跑全链路不变量：
// 1) 重排前后「管道行序列（含单元格）」完全一致；
// 2) 重排后不允许出现「以 | 开头却不成行」的拼接残骸（事故特征签名）。
function checkText(label, text) {
  if (!text || !text.includes('\n|')) return 0;
  const norm = normalizeDisplayText(text);
  assert(eq(pipeRows(text), pipeRows(norm)), label + '：重排改变了管道表行');
  for (const line of norm.split('\n')) {
    if (line.trimStart().startsWith('|') && !isPipeRow(line)) {
      assert(false, label + '：出现拼接残骸行 -> ' + line.slice(0, 80));
    }
  }
  return 1;
}

// ---- 固定事故样例（与 data 解耦，钉住 bug 本身）----
const X13 = '【2013统考真题】某计算机主存地址空间大小为256MB，按字节编址。虚拟地址空间大小为4GB，采用页式存储管理，页面大小为4KB，TLB（快表）采用全相联映射，有4个页表项，内容如下表所示。\n| 有效位 | 标记 | 页框号 | … |\n| --- | --- | --- | --- |\n| 0 | FF180H | 0002H | … |\n| 1 | 3FFF1H | 0035H | … |\n| 0 | 02FF3H | 0351H | … |\n| 1 | 03FFFH | 0153H | … |\n则对虚拟地址03FFF180H进行虚实地址变换的结果是（）。';
checkText('fixture X13', X13);
const fenced = '题干如下：\n```\n进程P1\t进程P2\ny:=1;\tx:=1\n```\n问（）。';
const fencedOut = normalizeDisplayText(fenced);
assert(fencedOut.includes('进程P1\t进程P2\ny:=1;\tx:=1'), '代码围栏内的换行和分栏不得被重排吸掉');
// 渲染侧：整块管道行应渲染出 表头 + 4 数据行
const block = X13.split('\n').filter(isPipeRow);
const html = stemTableHtml(block);
assert((html.match(/<tr>/g) || []).length === 5, 'fixture X13：stemTableHtml 应渲染 1 表头 + 4 数据行');

// ---- 全库扫描：四科 content / explanation / sub_questions ----
let tabled = 0;
for (const key of ['ds', 'coa', 'os', 'net']) {
  const data = JSON.parse(readFileSync(join(root, 'math-bank', `data-${key}.json`), 'utf8'));
  for (const ch of data.chapters) {
    for (const q of ch.questions) {
      const label = `${key} ${ch.name} ${q.id}`;
      tabled += checkText(label, q.content);
      if (q.sub_questions) q.sub_questions.forEach((s, i) => { tabled += checkText(label + ' sub' + i, s); });
      if (q.answer && q.answer.explanation) tabled += checkText(label + ' 解析', q.answer.explanation);
    }
  }
}
assert(tabled >= 10, `全库含表题面过少（${tabled}），扫描可能失真`);

if (failures) { console.error(`${failures} 处失败`); process.exit(1); }
console.log(`OK: 固定样例 + 全库 ${tabled} 段含表文本通过重排不变量`);
