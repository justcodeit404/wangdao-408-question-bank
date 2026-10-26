/**
 * Shared A4 workbook print preview for the independent question banks.
 * Hosts keep their own stem/KaTeX/image renderers; this module only owns the
 * print document, pagination, resource readiness and print interaction.
 */
(function (global) {
  'use strict';

  var LARGE_BATCH_THRESHOLD = 100;
  var RENDER_CHUNK_SIZE = 20;
  var RESOURCE_TIMEOUT_MS = 15000;

  var PRINT_CSS = `
@page { size: A4; margin: 14mm 15mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #e5e7eb; }
body.viewer-pdf-body {
  color: #111827;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
.viewer-pdf-toolbar {
  position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px; padding: 12px 18px; color: #111827; background: #fff;
  border-bottom: 1px solid #d1d5db; box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
  font: 14px/1.5 "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
}
.viewer-pdf-toolbar-title { font-weight: 700; }
.viewer-pdf-toolbar-status { color: #4b5563; }
.viewer-pdf-toolbar-status.is-error { color: #b91c1c; font-weight: 700; }
.viewer-pdf-toolbar button {
  appearance: none; padding: 7px 12px; border: 1px solid #9ca3af; border-radius: 6px;
  color: #111827; background: #fff; cursor: pointer; font: inherit;
}
.viewer-pdf-toolbar button.viewer-pdf-print-button { color: #fff; background: #1f2937; border-color: #1f2937; }
.viewer-pdf-toolbar button:disabled { opacity: .45; cursor: wait; }
.viewer-pdf-toolbar-hint { flex-basis: 100%; color: #6b7280; font-size: 12px; }
.viewer-pdf-items { padding: 24px 12px 60px; }
.viewer-pdf-item {
  width: 210mm; min-height: 297mm; margin: 0 auto 24px; padding: 14mm 15mm;
  color: #111827; background: #fff; box-shadow: 0 2px 14px rgb(0 0 0 / 14%);
  font-size: 11pt; line-height: 1.65;
}
.viewer-pdf-qhead {
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  margin-bottom: 6mm; padding-bottom: 2mm; border-bottom: 1px solid #d1d5db;
  color: #4b5563; font-size: 9pt; line-height: 1.4; break-after: avoid; page-break-after: avoid;
}
.viewer-pdf-qhead-title { min-width: 0; overflow-wrap: anywhere; }
.viewer-pdf-qhead-count { flex: none; white-space: nowrap; }
.viewer-pdf-question { color: #111827; overflow-wrap: break-word; }
.viewer-pdf-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-bottom: 4mm; color: #4b5563; font-size: 9pt; }
.viewer-pdf-options { margin-top: 4mm; }
.viewer-pdf-option { display: flex; align-items: flex-start; gap: 6px; margin: 2mm 0; break-inside: avoid; page-break-inside: avoid; }
.viewer-pdf-option strong { flex: none; }
.viewer-pdf-question img { max-width: 100% !important; max-height: 190mm; height: auto; object-fit: contain; }
.viewer-pdf-question .q-image img,
.viewer-pdf-question figure img { display: block; margin: 4mm auto; }
.viewer-pdf-question .q-image,
.viewer-pdf-question figure,
.viewer-pdf-question .option-item,
.viewer-pdf-question .opt,
.viewer-pdf-question tr { break-inside: avoid; page-break-inside: avoid; }
.viewer-pdf-question pre {
  max-width: 100% !important; white-space: pre-wrap !important;
  overflow-wrap: anywhere; word-break: break-word; overflow: visible !important;
}
.viewer-pdf-question table { max-width: 100%; border-collapse: collapse; }
.viewer-pdf-question .stem-table { overflow: visible !important; }
.viewer-pdf-question .q-image-zoom,
.viewer-pdf-question .zoom-overlay { display: none !important; }
@media print {
  html, body, body.viewer-pdf-body { background: #fff !important; }
  .viewer-pdf-toolbar { display: none !important; }
  .viewer-pdf-items { padding: 0; }
  .viewer-pdf-item {
    width: auto; min-height: 0; margin: 0; padding: 0; border: 0; box-shadow: none;
    break-after: page; page-break-after: always;
  }
  .viewer-pdf-item:last-child { break-after: auto; page-break-after: auto; }
  .viewer-pdf-question a { color: inherit; text-decoration: none; }
}
`;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function alertHost(message) {
    if (typeof global.alert === 'function') global.alert(message);
  }

  function confirmHost(message) {
    return typeof global.confirm === 'function' ? global.confirm(message) : true;
  }

  function yieldToBrowser() {
    return new Promise(function (resolve) { global.setTimeout(resolve, 0); });
  }

  function sourceStylesHtml() {
    if (!global.document || !global.document.querySelectorAll) return '';
    var nodes = global.document.querySelectorAll('link[rel="stylesheet"], style');
    var html = '';
    for (var i = 0; i < nodes.length; i++) html += nodes[i].outerHTML + '\n';
    return html;
  }

  function documentShell(title, count) {
    var sourceDoc = global.document || {};
    var baseURI = sourceDoc.baseURI || (global.location && global.location.href) || '';
    return '<!doctype html><html lang="zh-CN" data-theme="light"><head>' +
      '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
      (baseURI ? '<base href="' + escapeHtml(baseURI) + '">' : '') +
      '<title>' + escapeHtml(title) + '</title>' + sourceStylesHtml() +
      '<style>' + PRINT_CSS + '</style></head><body class="viewer-pdf-body">' +
      '<div class="viewer-pdf-toolbar" role="region" aria-label="做题本打印工具栏">' +
      '<span class="viewer-pdf-toolbar-title">' + escapeHtml(title) + '</span>' +
      '<span class="viewer-pdf-toolbar-status" id="viewerPdfStatus">正在准备 ' + count + ' 道题…</span>' +
      '<button type="button" class="viewer-pdf-print-button" id="viewerPdfPrint" disabled>打印 / 保存 PDF</button>' +
      '<button type="button" id="viewerPdfClose">关闭</button>' +
      '<span class="viewer-pdf-toolbar-hint">A4 · 每题一页 · 不含答案。打印目标请选择“另存为 PDF”；超长题会自动续页。</span>' +
      '</div><main class="viewer-pdf-items" id="viewerPdfItems"></main></body></html>';
  }

  function questionShell(title, html, index, total) {
    return '<section class="viewer-pdf-item">' +
      '<header class="viewer-pdf-qhead"><span class="viewer-pdf-qhead-title">' + escapeHtml(title) + '</span>' +
      '<span class="viewer-pdf-qhead-count">第 ' + (index + 1) + ' / ' + total + ' 题</span></header>' +
      '<div class="viewer-pdf-question">' + String(html || '') + '</div></section>';
  }

  function prepareImages(printDoc) {
    if (!printDoc.querySelectorAll) return [];
    var nodes = printDoc.querySelectorAll('.viewer-pdf-question img');
    var images = [];
    for (var i = 0; i < nodes.length; i++) {
      var img = nodes[i];
      img.setAttribute('loading', 'eager');
      img.removeAttribute('onclick');
      if (img.getAttribute('src')) images.push(img);
    }
    return images;
  }

  async function waitForResources(printDoc, images) {
    var fontReady = printDoc.fonts && printDoc.fonts.ready
      ? Promise.resolve(printDoc.fonts.ready).catch(function () {})
      : Promise.resolve();
    var imageReady = Promise.all(images.map(function (img) {
      if (img.complete) return Promise.resolve();
      return new Promise(function (resolve) {
        img.addEventListener('load', resolve, { once: true });
        img.addEventListener('error', resolve, { once: true });
      });
    }));
    var timer = null;
    var timeout = new Promise(function (resolve) {
      timer = global.setTimeout(resolve, RESOURCE_TIMEOUT_MS);
    });
    await Promise.race([Promise.all([fontReady, imageReady]), timeout]);
    global.clearTimeout(timer);
    return images.filter(function (img) { return !img.complete || img.naturalWidth === 0; }).length;
  }

  /**
   * Open a printable workbook. The popup is created before the first await so
   * browsers still treat it as part of the user's click gesture.
   */
  async function open(options) {
    options = options || {};
    var questions = Array.isArray(options.questions) ? options.questions.slice() : [];
    var title = String(options.title || '题库做题本');
    if (!questions.length) {
      alertHost('当前没有可导出的题目，请先调整筛选条件。');
      return false;
    }
    if (typeof options.renderQuestion !== 'function') {
      alertHost('导出组件缺少题目渲染器。');
      return false;
    }
    var threshold = Number(options.confirmAbove) > 0 ? Number(options.confirmAbove) : LARGE_BATCH_THRESHOLD;
    if (questions.length > threshold && !confirmHost(
      '当前共 ' + questions.length + ' 道题，预计至少生成 ' + questions.length + ' 页 PDF（超长题会续页）。继续吗？'
    )) return false;

    var printWindow = global.open('', '_blank');
    if (!printWindow) {
      alertHost('浏览器拦截了打印窗口。请允许本站打开弹窗后重试。');
      return false;
    }

    var status = null;
    try {
      var printDoc = printWindow.document;
      printDoc.open();
      printDoc.write(documentShell(title, questions.length));
      printDoc.close();
      printDoc.title = title;

      var items = printDoc.getElementById('viewerPdfItems');
      status = printDoc.getElementById('viewerPdfStatus');
      var printButton = printDoc.getElementById('viewerPdfPrint');
      var closeButton = printDoc.getElementById('viewerPdfClose');
      printButton.onclick = function () { printWindow.focus(); printWindow.print(); };
      closeButton.onclick = function () { printWindow.close(); };

      var html = [];
      for (var i = 0; i < questions.length; i++) {
        if (printWindow.closed) return false;
        var rendered = options.renderQuestion(questions[i], i);
        html.push(questionShell(title, rendered, i, questions.length));
        if ((i + 1) % RENDER_CHUNK_SIZE === 0 || i === questions.length - 1) {
          status.textContent = '正在排版 ' + (i + 1) + ' / ' + questions.length + ' 题…';
          await yieldToBrowser();
        }
      }
      items.innerHTML = html.join('');
      var images = prepareImages(printDoc);
      status.textContent = images.length ? '正在等待字体与 ' + images.length + ' 张题图加载…' : '正在等待字体加载…';
      var failedImages = await waitForResources(printDoc, images);
      printButton.disabled = false;
      if (printWindow.closed) return false;
      if (failedImages) {
        status.textContent = failedImages + ' 张题图未加载成功。请检查预览，勿直接导出缺图 PDF。';
        status.classList.add('is-error');
        alertHost('有 ' + failedImages + ' 张题图未加载成功，已暂停自动打印。请检查网络或刷新打印窗口后重试。');
        return false;
      }

      status.textContent = '已准备好 ' + questions.length + ' 道题，可选择“另存为 PDF”。';
      if (options.autoPrint === false) return true;
      await yieldToBrowser();
      printWindow.focus();
      printWindow.print();
      return true;
    } catch (error) {
      if (status) {
        status.textContent = '排版失败：' + (error && error.message ? error.message : String(error));
        status.classList.add('is-error');
      }
      alertHost('生成做题本失败：' + (error && error.message ? error.message : String(error)));
      return false;
    }
  }

  global.ViewerPdfExport = { open: open };
})(typeof window !== 'undefined' ? window : globalThis);
