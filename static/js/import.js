(function () {
  let uploadedFiles = [];
  let recognizedItems = [];
  let timerInterval = null;
  let timerEl = null;

  function init() {
    const page = document.getElementById('pageImport');
    if (!page) return;
    page.innerHTML = `
      <div class="import-left">
        <div class="img-drop" id="imgDrop">
          <input type="file" id="imgInput" multiple accept="image/*">
          <div>拖入图片或点击选择</div>
          <div class="hint">支持 JPG / PNG / WEBP</div>
        </div>
        <div class="thumb-list" id="thumbList"></div>
        <button class="btn r" id="btnRecognize" disabled>开始识别</button>
        <div class="import-log" id="importLog"><span class="il-dim">等待上传图片...\n</span></div>
      </div>
      <div class="import-right">
        <div class="tbl-wrap" id="tblWrap"><div class="empty">上传图片后点击"开始识别"</div></div>
        <div class="import-actions">
          <div class="status" id="importStatus"></div>
          <button class="btn d" id="btnExport" style="width:auto;padding:10px 24px;margin:0" disabled>导出 Excel</button>
        </div>
      </div>`;

    const drop = document.getElementById('imgDrop');
    const input = document.getElementById('imgInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); addFiles(e.dataTransfer.files); });
    input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });
    document.getElementById('btnRecognize').addEventListener('click', recognize);
    document.getElementById('btnExport').addEventListener('click', exportExcel);
  }

  function appendLog(msg, cls) {
    const log = document.getElementById('importLog');
    if (!log) return null;
    const span = document.createElement('span');
    span.textContent = msg + '\n';
    if (cls) span.className = cls;
    log.appendChild(span);
    log.scrollTop = log.scrollHeight;
    return span;
  }

  function clearLog() {
    const log = document.getElementById('importLog');
    if (log) log.innerHTML = '';
  }

  function startTimer() {
    let s = 0;
    timerEl = appendLog('Gemini 识别中... 0s', 'il-dim');
    timerInterval = setInterval(() => {
      s++;
      if (timerEl) timerEl.textContent = `Gemini 识别中... ${s}s\n`;
    }, 1000);
  }

  function stopTimer() {
    clearInterval(timerInterval);
    timerInterval = null;
    timerEl = null;
  }

  function addFiles(fileList) {
    for (const f of fileList) {
      if (!f.type.startsWith('image/')) continue;
      uploadedFiles.push(f);
    }
    renderThumbs();
    const btn = document.getElementById('btnRecognize');
    if (btn) btn.disabled = uploadedFiles.length === 0;
    if (uploadedFiles.length > 0) {
      clearLog();
      appendLog(`已选择 ${uploadedFiles.length} 张图片，点击"开始识别"`, 'il-dim');
    }
  }

  function renderThumbs() {
    const list = document.getElementById('thumbList');
    list.innerHTML = uploadedFiles.map((f, i) => `
      <div class="thumb-item">
        <img src="${URL.createObjectURL(f)}">
        <span class="thumb-name">${f.name}</span>
        <span class="thumb-rm" data-i="${i}">✕</span>
      </div>`).join('');
    list.querySelectorAll('.thumb-rm').forEach(el => {
      el.addEventListener('click', () => {
        uploadedFiles.splice(+el.dataset.i, 1);
        renderThumbs();
        const btn = document.getElementById('btnRecognize');
        if (btn) btn.disabled = uploadedFiles.length === 0;
      });
    });
  }

  async function recognize() {
    const btn = document.getElementById('btnRecognize');
    btn.disabled = true;
    btn.textContent = '识别中…';
    clearLog();
    appendLog(`上传 ${uploadedFiles.length} 张图片...`);

    const fd = new FormData();
    uploadedFiles.forEach(f => fd.append('files', f));

    startTimer();
    try {
      const res = await fetch('/import/recognize', { method: 'POST', body: fd });
      stopTimer();
      const body = await res.json();
      if (!body.ok) {
        appendLog('识别失败：' + body.msg, 'il-err');
        setStatus(body.msg, true);
        return;
      }
      recognizedItems = body.items;
      const nullCount = recognizedItems.filter(it => it.flagged).length;
      const suspectCount = recognizedItems.filter(it => it.barcode_suspect).length;
      appendLog(`识别完成，共 ${recognizedItems.length} 条`, 'il-ok');
      if (nullCount) appendLog(`  ${nullCount} 条有空值（红色）需补填`, 'il-warn');
      if (suspectCount) appendLog(`  ${suspectCount} 条条码格式可疑（黄色）`, 'il-warn');
      renderTable();
    } catch (e) {
      stopTimer();
      appendLog('网络错误：' + e.message, 'il-err');
      setStatus('网络错误：' + e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = '开始识别';
    }
  }

  function renderTable() {
    const wrap = document.getElementById('tblWrap');
    if (!recognizedItems.length) { wrap.innerHTML = '<div class="empty">未识别到任何条目</div>'; updateExportBtn(); return; }
    wrap.innerHTML = `<table class="import-tbl">
      <thead><tr><th>Barcode</th><th>数量</th><th>单价(€)</th><th>总价(€)</th></tr></thead>
      <tbody>${recognizedItems.map((it, i) => `
        <tr>
          <td class="${it.barcode == null ? 'cell-null' : it.barcode_suspect ? 'cell-suspect' : ''}"><input data-i="${i}" data-f="barcode" value="${it.barcode ?? ''}"></td>
          <td class="${it.quantity == null ? 'cell-null' : ''}"><input data-i="${i}" data-f="quantity" type="number" value="${it.quantity ?? ''}"></td>
          <td><input data-i="${i}" data-f="unit_price" type="number" readonly tabindex="-1" value="${it.unit_price != null ? it.unit_price.toFixed(2) : ''}"></td>
          <td class="${it.total_price == null ? 'cell-null' : ''}"><input data-i="${i}" data-f="total_price" type="number" value="${it.total_price != null ? it.total_price.toFixed(2) : ''}"></td>
        </tr>`).join('')}
      </tbody></table>`;
    wrap.querySelectorAll('input[data-f]:not([readonly])').forEach(el => el.addEventListener('change', onCellChange));
    updateExportBtn();
  }

  function onCellChange(e) {
    const i = +e.target.dataset.i;
    const f = e.target.dataset.f;
    const val = e.target.value.trim();
    if (f === 'barcode') recognizedItems[i].barcode = val || null;
    else if (f === 'quantity') recognizedItems[i].quantity = val ? +val : null;
    else if (f === 'total_price') recognizedItems[i].total_price = val ? +val : null;
    const it = recognizedItems[i];
    it.flagged = it.barcode == null || it.quantity == null || it.total_price == null;
    it.unit_price = (it.quantity && it.total_price != null) ? +(it.total_price / it.quantity).toFixed(4) : null;
    it.barcode_suspect = it.barcode != null && !/^\d{8}$|^\d{13}$/.test(it.barcode);
    renderTable();
  }

  async function exportExcel() {
    const btn = document.getElementById('btnExport');
    btn.disabled = true;
    appendLog('正在导出 Excel...', 'il-dim');
    try {
      const res = await fetch('/import/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: recognizedItems }),
      });
      if (!res.ok) { const b = await res.json(); appendLog('导出失败：' + b.msg, 'il-err'); setStatus(b.msg, true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `import_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      appendLog('Excel 已下载', 'il-ok');
    } catch (e) {
      appendLog('导出失败：' + e.message, 'il-err');
      setStatus('导出失败：' + e.message, true);
    } finally {
      updateExportBtn();
    }
  }

  function updateExportBtn() {
    const anyFlagged = recognizedItems.some(it => it.flagged);
    const btn = document.getElementById('btnExport');
    if (btn) btn.disabled = anyFlagged || recognizedItems.length === 0;
  }

  function setStatus(msg, isError = false) {
    const el = document.getElementById('importStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'status' + (isError ? ' error' : '');
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
    const orig = window.switchPage;
    window.switchPage = function (pg) {
      if (typeof orig === 'function') orig(pg);
      if (pg === 'import') {
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.getElementById('navImport')?.classList.add('active');
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        document.getElementById('pageImport')?.classList.add('active');
      }
    };
  });
})();
