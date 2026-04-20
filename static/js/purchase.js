(function () {
  let storedSupplierFile = null;
  let rows = [];
  let systemBarcodes = new Set();
  let newEntries = [];
  let supplierInfo = { id: '', name: '' };

  function init() {
    const page = document.getElementById('pagePurchase');
    if (!page) return;
    page.innerHTML = `
      <div class="pur-drop" id="purDrop">
        <input type="file" id="purInput" accept=".xlsx,.xls,.csv" multiple>
        <div>拖入或点击选择：供应商 Excel + 系统 stockpile CSV</div>
        <div class="hint">供应商：第1列条码 · 第3列价格 · 第6列数量　|　系统：文件名以 stockpile 开头</div>
      </div>
      <div class="pur-results" id="purResults"><div class="empty">上传文件后显示结果</div></div>
      <div class="pur-newbox" id="purNewBox" style="display:none">
        <div class="pur-newbox-hd">新条码处理 <button class="pur-new-copy-all" id="purNewCopyAll">复制全部条码</button></div>
        <div class="pur-supplier">
          供应商 ID: <input class="pur-inp" id="purSupId" placeholder="必填">
          供应商名称: <input class="pur-inp" id="purSupName" placeholder="必填">
        </div>
        <div id="purNewList"></div>
      </div>
      <div class="pur-actions">
        <div class="pur-status" id="purStatus"></div>
        <button class="pur-btn-copy" id="purCopy" disabled>一键复制</button>
        <button class="pur-btn-dl" id="purDl" disabled>下载全部</button>
      </div>`;
    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); handleFiles(e.dataTransfer.files); });
    input.addEventListener('change', () => { handleFiles(input.files); input.value = ''; });
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purNewCopyAll').addEventListener('click', copyNewBarcodes);
    document.getElementById('purDl').addEventListener('click', downloadZip);
    document.getElementById('purSupId').addEventListener('input', e => { supplierInfo.id = e.target.value.trim(); updateButtons(); });
    document.getElementById('purSupName').addEventListener('input', e => { supplierInfo.name = e.target.value.trim(); updateButtons(); });
  }

  async function handleFiles(files) {
    files = Array.from(files || []);
    if (files.length < 2) { setStatus('需要 2 个文件：供应商 Excel + stockpile CSV', true); return; }
    let supplier = null, stockpile = null;
    for (const f of files) {
      if (f.name.toLowerCase().startsWith('stockpile')) stockpile = f;
      else supplier = f;
    }
    if (!supplier || !stockpile) { setStatus('未能识别：需要 1 个 stockpile 开头的 csv + 1 个供应商文件', true); return; }
    storedSupplierFile = supplier;
    setStatus('解析中...');
    const fd = new FormData();
    fd.append('files', supplier);
    fd.append('files', stockpile);
    try {
      const res = await fetch('/purchase/process', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      rows = body.rows;
      systemBarcodes = new Set(body.system_barcodes);
      newEntries = body.new_barcodes.map(bc => ({ barcode: bc, name: '', invoice_name: '' }));
      renderResults();
      renderNewBox();
      const flagCount = rows.filter(r => r.price_flagged).length;
      setStatus(`共 ${rows.length} 条，${newEntries.length} 个新条码${flagCount ? `，${flagCount} 条需改价` : ''}`);
    } catch (e) {
      setStatus('解析失败：' + e.message, true);
    }
  }

  function renderResults() {
    const container = document.getElementById('purResults');
    if (!rows.length) { container.innerHTML = '<div class="empty">未解析到数据</div>'; updateButtons(); return; }
    container.innerHTML = rows.map((r, i) => {
      if (r.price_flagged) {
        const parts = r.formatted.split(',');
        return `<div class="pur-row flagged" data-i="${i}">
          <span class="pur-text">${parts[0]},</span>
          <input class="pur-price-input" data-i="${i}" value="${parts[1]}" title="价格小数超2位，请修改">
          <span class="pur-text">,,${parts[3]}</span>
        </div>`;
      }
      return `<div class="pur-row" data-i="${i}"><span class="pur-text">${r.formatted}</span></div>`;
    }).join('');
    container.querySelectorAll('.pur-price-input').forEach(el => {
      el.addEventListener('input', onPriceEdit);
      el.addEventListener('change', onPriceEdit);
    });
    updateButtons();
  }

  async function copyNewBarcodes() {
    const text = newEntries.map(e => e.barcode).join('\n');
    const btn = document.getElementById('purNewCopyAll');
    const done = () => {
      btn.textContent = '已复制 ✓'; btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '复制全部条码'; btn.classList.remove('copied'); }, 2000);
    };
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text); done(); return;
      }
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
      document.body.appendChild(ta); ta.select();
      if (document.execCommand('copy')) done();
      document.body.removeChild(ta);
    } catch (e) { setStatus('复制失败：' + e.message, true); }
  }

  function renderNewBox() {
    const box = document.getElementById('purNewBox');
    const list = document.getElementById('purNewList');
    if (!newEntries.length) { box.style.display = 'none'; updateButtons(); return; }
    box.style.display = '';
    list.innerHTML = newEntries.map((e, i) => `
      <div class="pur-new-row" data-i="${i}">
        <span class="pur-new-bc">${escapeHtml(e.barcode)}</span>
        品名: <input class="pur-inp pur-new-name" data-i="${i}" data-field="name" value="${escapeAttr(e.name)}" placeholder="第4列">
        发票品名: <input class="pur-inp pur-new-name" data-i="${i}" data-field="invoice_name" value="${escapeAttr(e.invoice_name)}" placeholder="第5列">
        <button class="pur-new-mod" data-i="${i}">修改</button>
        <button class="pur-new-del" data-i="${i}">删除</button>
      </div>`).join('');
    list.querySelectorAll('.pur-new-name').forEach(el => {
      el.addEventListener('input', ev => {
        const t = ev.target;
        newEntries[+t.dataset.i][t.dataset.field] = t.value.trim();
        updateButtons();
      });
    });
    list.querySelectorAll('.pur-new-mod').forEach(el => {
      el.addEventListener('click', ev => {
        const btn = ev.target;
        const i = +btn.dataset.i;
        const nameInp = list.querySelector(`.pur-new-name[data-i="${i}"][data-field="name"]`);
        const invInp = list.querySelector(`.pur-new-name[data-i="${i}"][data-field="invoice_name"]`);
        const rowEl = list.querySelector(`.pur-new-row[data-i="${i}"]`);
        const name = nameInp ? nameInp.value.trim() : '';
        const invoice = invInp ? invInp.value.trim() : '';
        if (!name) { nameInp && nameInp.focus(); return; }
        if (!invoice) { invInp && invInp.focus(); return; }
        newEntries[i].name = name;
        newEntries[i].invoice_name = invoice;
        updateButtons();
        btn.textContent = '已修改 ✓';
        btn.classList.add('saved');
        rowEl && rowEl.classList.add('saved-flash');
        setTimeout(() => {
          btn.textContent = '修改';
          btn.classList.remove('saved');
          rowEl && rowEl.classList.remove('saved-flash');
        }, 1500);
      });
    });
    list.querySelectorAll('.pur-new-del').forEach(el => {
      el.addEventListener('click', ev => startDelete(+ev.target.dataset.i));
    });
    updateButtons();
  }

  function startDelete(i) {
    const list = document.getElementById('purNewList');
    const rowEl = list.querySelector(`.pur-new-row[data-i="${i}"]`);
    if (!rowEl) return;
    const oldBc = newEntries[i].barcode;
    rowEl.innerHTML = `<input class="pur-inp pur-new-correct" placeholder="输入修正后的条码，回车确认 / Esc 取消">`;
    const inp = rowEl.querySelector('.pur-new-correct');
    inp.focus();
    let settled = false;
    const finish = (commit) => {
      if (settled) return; settled = true;
      const val = inp.value.trim();
      if (!commit || !val) { renderNewBox(); return; }
      applyCorrection(oldBc, val);
    };
    inp.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') finish(true);
      else if (ev.key === 'Escape') finish(false);
    });
    inp.addEventListener('blur', () => finish(true));
  }

  function applyCorrection(oldBc, newBc) {
    rows.forEach(r => {
      if (r.barcode === oldBc) {
        r.barcode = newBc;
        const parts = r.formatted.split(',');
        r.formatted = `${newBc},${parts[1]},,${parts[3]}`;
      }
    });
    newEntries = newEntries.filter(e => e.barcode !== oldBc);
    if (!systemBarcodes.has(newBc) && !newEntries.some(e => e.barcode === newBc)) {
      newEntries.push({ barcode: newBc, name: '' });
    }
    renderResults();
    renderNewBox();
  }

  function onPriceEdit(e) {
    const i = +e.target.dataset.i;
    const val = e.target.value.trim();
    const price = parseFloat(val);
    const decimals = val.includes('.') ? val.split('.')[1].replace(/0+$/, '').length : 0;
    const valid = !isNaN(price) && decimals <= 2;
    e.target.classList.toggle('valid', valid);
    if (valid) {
      rows[i].price = price;
      rows[i].price_flagged = false;
      rows[i].formatted = `${rows[i].barcode},${price.toFixed(2)},,${rows[i].quantity}`;
    } else {
      rows[i].price_flagged = true;
    }
    updateButtons();
  }

  function updateButtons() {
    const anyFlagged = rows.some(r => r.price_flagged);
    const hasRows = rows.length > 0;
    const newOk = newEntries.length === 0 ||
      (supplierInfo.id && supplierInfo.name && newEntries.every(e => e.name && e.invoice_name));
    document.getElementById('purCopy').disabled = anyFlagged || !hasRows;
    document.getElementById('purDl').disabled = anyFlagged || !hasRows || !newOk;
  }

  async function copyAll() {
    const text = rows.map(r => r.formatted).join('\n');
    const done = () => {
      const btn = document.getElementById('purCopy');
      btn.textContent = '已复制 ✓'; btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '一键复制'; btn.classList.remove('copied'); }, 2000);
    };
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text); done(); return;
      }
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand('copy'); document.body.removeChild(ta);
      if (ok) done(); else setStatus('复制失败：浏览器不允许', true);
    } catch (e) { setStatus('复制失败：' + e.message, true); }
  }

  async function downloadZip() {
    if (!storedSupplierFile) return;
    const btn = document.getElementById('purDl');
    btn.disabled = true;
    const fd = new FormData();
    fd.append('file', storedSupplierFile);
    fd.append('rows', JSON.stringify(rows));
    const entriesForExport = newEntries.map(e => ({
      barcode: e.barcode, name: e.name, invoice_name: e.invoice_name,
      supplier_id: supplierInfo.id, supplier_name: supplierInfo.name,
    }));
    fd.append('new_entries', JSON.stringify(entriesForExport));
    try {
      const res = await fetch('/purchase/export', { method: 'POST', body: fd });
      if (!res.ok) { const b = await res.json(); setStatus(b.msg, true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `采购订单${new Date().toISOString().slice(0,10).replace(/-/g,'')}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setStatus('下载失败：' + e.message, true); }
    finally { updateButtons(); }
  }

  function setStatus(msg, isError = false) {
    const el = document.getElementById('purStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'pur-status' + (isError ? ' error' : '');
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
  }
  function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
    const orig = window.switchPage;
    window.switchPage = function (pg) {
      if (typeof orig === 'function') orig(pg);
      if (pg === 'purchase') {
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.getElementById('navPurchase')?.classList.add('active');
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        document.getElementById('pagePurchase')?.classList.add('active');
      }
    };
  });
})();
