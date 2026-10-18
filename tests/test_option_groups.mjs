// 回归：多空多组选项题（option_groups）必须按空分组渲染、答案按空标注，
// 而不是把选项文本混在题干里只显示一组选项。
// 运行：node tests/test_option_groups.mjs（由 tests/test_option_groups.py 包装进 pytest）
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const appSrc = readFileSync(join(root, 'math-bank', 'app.js'), 'utf8');

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

const FN = ['sortedOptionEntries', 'optionGroupsOf', 'flatOptionEntries', 'optionLines',
  'answerChoiceText', 'orderedCorrect', 'renderOptionsHtml', 'escapeHtml'];
const bundle = FN.map((n) => extractFunction(appSrc, n)).join('\n');
const api = new Function(bundle + '\nreturn {' + FN.join(',') + '};')();

const grouped = {
  content: '各条指令的地址编号起始一般定为（①），称为（②）地址。',
  options: { A: '1', B: '0', C: 'IP', D: 'CS' },
  option_groups: [
    { label: '①', options: { A: '1', B: '0', C: 'IP', D: 'CS' } },
    { label: '②', options: { A: '绝对', B: '名义', C: '逻辑', D: '实' } },
  ],
  answer: { choice: 'BC' },
};
const plain = {
  content: '判空条件是（）。',
  options: { A: 'head->next==NULL', B: 'head==NULL' },
  answer: { choice: 'A' },
};

assert(api.optionGroupsOf(plain) === null, '单组题不应走分组渲染');
assert(api.optionGroupsOf(grouped).length === 2, '分组题应返回两组');
assert(api.flatOptionEntries(grouped).length === 8, '扁平选项应是两组之和');
assert(api.flatOptionEntries(grouped)[5][0] === 'B', '第二组应从 B 继续（DOM 顺序）');
assert(api.answerChoiceText(grouped) === '①B ②C', '答案应按空标注: ' + api.answerChoiceText(grouped));
assert(api.answerChoiceText(plain) === 'A', '单组答案保持原样');

const html = api.renderOptionsHtml(grouped);
assert(html.includes('q-options-groups'), '应渲染分组容器');
assert((html.match(/data-key="[A-E]" data-group="0"/g) || []).length === 4, '第一组应有 4 个选项');
assert((html.match(/data-key="[A-E]" data-group="1"/g) || []).length === 4, '第二组应有 4 个选项');
assert(html.includes('第①空') && html.includes('第②空'), '应有空序标签');

const plainHtml = api.renderOptionsHtml(plain);
assert(!plainHtml.includes('q-options-groups'), '单组题渲染不得变化');
assert(plainHtml.includes('data-key="A"') && plainHtml.includes('data-key="B"'));

const lines = api.optionLines(grouped);
assert(lines.includes('①') && lines.includes('  C. 逻辑'), '复制文本应含分组选项');
assert(api.optionLines(grouped, 'md').includes('  - **C**. 逻辑'), 'markdown 分组格式');

console.log('test_option_groups: ok');

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL: ' + msg);
    process.exit(1);
  }
}
