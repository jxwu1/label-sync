(function () {
  let uploadedFiles = [];
  let recognizedItems = [];

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

  function addFiles(fileList) {
    for (const f of fileList) {
      if (!f.type.startsWith('image/')) continue;
      uploadedFiles.push(f);
    }
    renderThumbs();
    document.getElementById('btnRecognize').disabled = uploadedFiles.length === 0;
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
      el.addEventListener('click', () => { uploadedFiles.splice(+el.dataset.i, 1); renderThumbs(); document.getElementById('btnRecognize').disabled = uploadedFiles.length === 0; });
    });
  }

  async function recognize() {
    const btn = document.getElementById('btnRecognize');
    btn.disabled = true;
    btn.textContent = '识别中…';
    setStatus('');
    const fd = new FormData();
    uploadedFiles.forEach(f => fd.append('files', f));
    try {
      const res = await fetch('/import/recognize', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      recognizedItems = body.items;
      renderTable();
    } catch (e) {
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
    try {
      const res = await fetch('/import/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: recognizedItems }),
      });
      if (!res.ok) { const b = await res.json(); setStatus(b.msg, true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `import_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
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

  // index.js switchPage only handles 'main' and 'dup' via classList.toggle.
  // Calling orig('import') will deactivate both pages (toggle with false) and
  // deactivate both nav items — which is correct before we activate 'import'.
  // We then activate #pageImport and #navImport ourselves.
  document.addEventListener('DOMContentLoaded', function () {
    init();
    const orig = window.switchPage;
    window.switchPage = function (page) {
      // Let the original handle all nav/page switching (main and dup)
      if (typeof orig === 'function') orig(page);
      // If original doesn't handle 'import', handle it here
      if (page === 'import') {
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        const ni = document.getElementById('navImport');
        if (ni) ni.classList.add('active');
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        const pi = document.getElementById('pageImport');
        if (pi) pi.classList.add('active');
      }
    };
  });
})();
