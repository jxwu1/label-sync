import { esc as escapeHtml, escapeAttr, copyToClip, setupDropZone } from "./shared.js";

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
      </div>
      <div class="pur-modal-overlay" id="purModalOverlay" style="display:none">
        <div class="pur-modal">
          <div class="pur-modal-title">记录到月度总结</div>
          <label>供应商名称<input class="pur-inp" id="purMsSupplier" placeholder="必填"></label>
          <label>总价 (€)<input class="pur-inp" id="purMsTotal" type="number" step="0.01"></label>
          <label>税金 (€)<input class="pur-inp" id="purMsTax" type="number" step="0.01" placeholder="必填"></label>
          <label>加税总价 (€)<input class="pur-inp" id="purMsTotalTax" disabled></label>
          <label>开票日期<input class="pur-inp" id="purMsDate" type="date"></label>
          <label>目标月份<input class="pur-inp" id="purMsMonth" type="month"></label>
          <div class="pur-modal-actions">
            <button class="pur-btn-dl" id="purMsConfirm">确认并导出</button>
            <button class="pur-btn-copy" id="purMsSkip">跳过，直接导出</button>
            <button class="pur-btn-copy" id="purMsCancel">取消</button>
          </div>
        </div>
      </div>
      <div class="pur-summary-section" id="purSummarySection">
        <div class="pur-summary-hd">月度总结</div>
        <div class="pur-summary-controls">
          <select class="pur-inp" id="purSumMonth"></select>
          <span id="purSumCount"></span>
          <button class="pur-btn-copy" id="purSumAdd">补录</button>
          <button class="pur-btn-copy" id="purSumManage">管理</button>
          <button class="pur-btn-dl" id="purSumDl">下载 PDF</button>
        </div>
      </div>
      <div class="pur-modal-overlay" id="purMgrOverlay" style="display:none;">
        <div class="pur-modal">
          <div class="pur-modal-hd">月度记录管理 <span id="purMgrMonth"></span></div>
          <input class="pur-inp" id="purMgrSearch" placeholder="搜索供应商/日期/金额">
          <div id="purMgrList" class="pur-mgr-list"></div>
          <div class="pur-modal-actions">
            <button class="pur-btn-copy" id="purMgrClose">关闭</button>
          </div>
        </div>
      </div>`;
    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    setupDropZone(drop, input, (files) => handleFiles(files));
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purNewCopyAll').addEventListener('click', copyNewBarcodes);
    document.getElementById('purDl').addEventListener('click', downloadZip);
    document.getElementById('purSupId').addEventListener('input', (e) => { supplierInfo.id = e.target.value.trim(); updateButtons(); });
    document.getElementById('purSupName').addEventListener('input', (e) => { supplierInfo.name = e.target.value.trim(); updateButtons(); });
    document.getElementById('purMsTax').addEventListener('input', updateTotalTax);
    document.getElementById('purMsTotal').addEventListener('input', updateTotalTax);
    document.getElementById('purMsSkip').addEventListener('click', skipAndExport);
    document.getElementById('purMsCancel').addEventListener('click', () => {
      document.getElementById('purModalOverlay').style.display = 'none';
    });
    document.getElementById('purSumMonth').addEventListener('change', loadSummaryCount);
    document.getElementById('purSumDl').addEventListener('click', downloadSummaryPdf);
    document.getElementById('purSumAdd').addEventListener('click', openAddRecord);
    document.getElementById('purSumManage').addEventListener('click', openManageRecords);
    document.getElementById('purMgrClose').addEventListener('click', () => {
      document.getElementById('purMgrOverlay').style.display = 'none';
    });
    document.getElementById('purMgrSearch').addEventListener('input', renderManageList);
    loadSummaryMonths();
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
      await copyToClip(text);
      done();
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
        <button class="pur-new-del" data-i="${i}">修正</button>
        <button class="pur-new-remove" data-i="${i}">删除</button>
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
    list.querySelectorAll('.pur-new-remove').forEach(el => {
      el.addEventListener('click', ev => removeNewEntry(+ev.target.dataset.i));
    });
    updateButtons();
  }

  function removeNewEntry(i) {
    const entry = newEntries[i];
    if (!entry) return;
    if (!confirm(`确认彻底删除条码 ${entry.barcode}？该条目将不会出现在导出中。`)) return;
    const bc = entry.barcode;
    rows = rows.filter(r => r.barcode !== bc);
    newEntries.splice(i, 1);
    renderResults();
    renderNewBox();
    setStatus(`已删除条码 ${bc}`);
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
    const valid = !isNaN(price) && isFinite(price);
    e.target.classList.toggle('valid', valid);
    if (valid) {
      const rounded = Math.round(price * 10000) / 10000;
      rows[i].price = rounded;
      rows[i].price_flagged = false;
      rows[i].formatted = `${rows[i].barcode},${rounded.toFixed(4)},,${rows[i].quantity}`;
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
      await copyToClip(text);
      done();
    } catch (e) { setStatus('复制失败：' + e.message, true); }
  }

  async function downloadZip() {
    if (!storedSupplierFile) return;
    const totalPrice = rows.reduce((sum, r) => sum + r.price * r.quantity, 0);
    const rounded = Math.round(totalPrice * 100) / 100;
    document.getElementById('purMsTotal').value = rounded.toFixed(2);
    document.getElementById('purMsTax').value = '';
    document.getElementById('purMsTotalTax').value = '';
    document.getElementById('purMsDate').value = new Date().toISOString().slice(0, 10);
    document.getElementById('purMsMonth').value = new Date().toISOString().slice(0, 7);
    document.getElementById('purMsSupplier').value = '';
    document.getElementById('purMsSkip').style.display = '';
    document.getElementById('purMsConfirm').onclick = () => confirmWithSummary();
    document.getElementById('purModalOverlay').style.display = 'flex';
  }

  function updateTotalTax() {
    const total = parseFloat(document.getElementById('purMsTotal').value) || 0;
    const tax = parseFloat(document.getElementById('purMsTax').value) || 0;
    document.getElementById('purMsTotalTax').value = (total + tax).toFixed(2);
  }

  async function confirmWithSummary() {
    const supplier = document.getElementById('purMsSupplier').value.trim();
    const total = parseFloat(document.getElementById('purMsTotal').value);
    const tax = parseFloat(document.getElementById('purMsTax').value);
    const invoiceDate = document.getElementById('purMsDate').value;
    const month = document.getElementById('purMsMonth').value;
    if (!supplier || isNaN(total) || isNaN(tax) || !invoiceDate || !month) {
      setStatus('请填写所有必填字段', true);
      return;
    }
    try {
      const res = await fetch('/monthly-summary/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          supplier_name: supplier,
          total_price: total,
          tax: tax,
          invoice_date: invoiceDate,
          month: month,
        }),
      });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
    } catch (e) {
      setStatus('保存月度记录失败：' + e.message, true);
      return;
    }
    document.getElementById('purModalOverlay').style.display = 'none';
    await loadSummaryCount();
    await doExport();
  }

  function skipAndExport() {
    document.getElementById('purModalOverlay').style.display = 'none';
    doExport();
  }

  async function doExport() {
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

  async function loadSummaryMonths() {
    try {
      const res = await fetch('/monthly-summary/months');
      const body = await res.json();
      const sel = document.getElementById('purSumMonth');
      if (!sel) return;
      const current = new Date().toISOString().slice(0, 7);
      const months = body.months || [];
      if (!months.includes(current)) months.unshift(current);
      sel.innerHTML = months.map(m => `<option value="${m}">${m}</option>`).join('');
      await loadSummaryCount();
    } catch (e) { /* silent */ }
  }

  async function loadSummaryCount() {
    const month = document.getElementById('purSumMonth')?.value;
    if (!month) return;
    try {
      const res = await fetch(`/monthly-summary/records/${month}`);
      const body = await res.json();
      const el = document.getElementById('purSumCount');
      if (el) el.textContent = `${body.count || 0} 条记录`;
    } catch (e) { /* silent */ }
  }

  async function downloadSummaryPdf() {
    const month = document.getElementById('purSumMonth')?.value;
    if (!month) return;
    try {
      const res = await fetch(`/monthly-summary/pdf/${month}`);
      if (!res.ok) { setStatus('下载 PDF 失败', true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `月度采购总结_${month}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setStatus('下载 PDF 失败：' + e.message, true); }
  }

  function openAddRecord() {
    const month = document.getElementById('purSumMonth')?.value || new Date().toISOString().slice(0, 7);
    document.getElementById('purMsTotal').value = '';
    document.getElementById('purMsTax').value = '';
    document.getElementById('purMsTotalTax').value = '';
    document.getElementById('purMsDate').value = '';
    document.getElementById('purMsMonth').value = month;
    document.getElementById('purMsSupplier').value = '';
    document.getElementById('purMsSkip').style.display = 'none';
    document.getElementById('purMsConfirm').onclick = async () => {
      const supplier = document.getElementById('purMsSupplier').value.trim();
      const total = parseFloat(document.getElementById('purMsTotal').value);
      const tax = parseFloat(document.getElementById('purMsTax').value);
      const invoiceDate = document.getElementById('purMsDate').value;
      const targetMonth = document.getElementById('purMsMonth').value;
      if (!supplier || isNaN(total) || isNaN(tax) || !invoiceDate || !targetMonth) {
        setStatus('请填写所有必填字段', true);
        return;
      }
      try {
        const res = await fetch('/monthly-summary/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            supplier_name: supplier,
            total_price: total,
            tax: tax,
            invoice_date: invoiceDate,
            month: targetMonth,
          }),
        });
        const body = await res.json();
        if (!body.ok) { setStatus(body.msg, true); return; }
        setStatus('补录成功');
      } catch (e) {
        setStatus('保存失败：' + e.message, true);
        return;
      }
      document.getElementById('purModalOverlay').style.display = 'none';
      await loadSummaryMonths();
    };
    document.getElementById('purModalOverlay').style.display = 'flex';
  }

  let manageRecords = [];
  let manageMonth = '';

  async function openManageRecords() {
    const month = document.getElementById('purSumMonth')?.value;
    if (!month) { setStatus('请先选择月份', true); return; }
    manageMonth = month;
    document.getElementById('purMgrMonth').textContent = month;
    document.getElementById('purMgrSearch').value = '';
    await reloadManageRecords();
    document.getElementById('purMgrOverlay').style.display = 'flex';
  }

  async function reloadManageRecords() {
    try {
      const res = await fetch(`/monthly-summary/records/${manageMonth}`);
      const body = await res.json();
      manageRecords = body.records || [];
    } catch (e) {
      manageRecords = [];
      setStatus('加载记录失败：' + e.message, true);
    }
    renderManageList();
  }

  function renderManageList() {
    const kw = document.getElementById('purMgrSearch').value.trim().toLowerCase();
    const list = document.getElementById('purMgrList');
    const filtered = manageRecords
      .map((rec, idx) => ({ rec, idx }))
      .sort((a, b) => (a.rec.invoice_date || '').localeCompare(b.rec.invoice_date || ''))
      .filter(({ rec }) => {
        if (!kw) return true;
        const hay = [
          rec.supplier_name,
          rec.invoice_date,
          String(rec.total_price),
          String(rec.tax),
          String(rec.total_with_tax),
        ].join(' ').toLowerCase();
        return hay.includes(kw);
      });
    if (!filtered.length) {
      list.innerHTML = '<div class="empty">无匹配记录</div>';
      return;
    }
    list.innerHTML = filtered.map(({ rec, idx }) => `
      <div class="pur-mgr-row">
        <div class="pur-mgr-cell"><b>${escapeHtml(rec.supplier_name)}</b></div>
        <div class="pur-mgr-cell">${escapeHtml(rec.invoice_date)}</div>
        <div class="pur-mgr-cell">总 €${Number(rec.total_price).toFixed(2)}</div>
        <div class="pur-mgr-cell">税 €${Number(rec.tax).toFixed(2)}</div>
        <div class="pur-mgr-cell">含税 €${Number(rec.total_with_tax).toFixed(2)}</div>
        <button class="pur-btn-copy pur-mgr-del" data-idx="${idx}">删除</button>
      </div>
    `).join('');
    list.querySelectorAll('.pur-mgr-del').forEach(btn => {
      btn.addEventListener('click', () => deleteManageRecord(parseInt(btn.dataset.idx, 10)));
    });
  }

  async function deleteManageRecord(idx) {
    const rec = manageRecords[idx];
    if (!rec) return;
    if (!confirm(`确认删除 ${rec.supplier_name} ${rec.invoice_date} 这条记录？`)) return;
    try {
      const res = await fetch(`/monthly-summary/delete/${manageMonth}/${idx}`, { method: 'POST' });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
    } catch (e) {
      setStatus('删除失败：' + e.message, true);
      return;
    }
    await reloadManageRecords();
    await loadSummaryMonths();
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function setStatus(msg, isError = false) {
    const el = document.getElementById('purStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'pur-status' + (isError ? ' error' : '');
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
  });
})();