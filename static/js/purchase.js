import { esc as escapeHtml, escapeAttr, copyToClip, setupDropZone } from "./shared.js";

(function () {
  let storedSupplierFile = null;
  let rows = [];
  let systemBarcodes = new Set();
  let inactiveBarcodes = new Set();
  let newEntries = [];
  let savedNewEntries = [];
  const supplierInfo = { id: '', name: '' };

  function init() {
    const page = document.getElementById('pagePurchase');
    if (!page) return;
    page.innerHTML = `
      <!-- 上传 zone：水平 flex（设计 §3.6） -->
      <div class="pur-drop" id="purDrop">
        <input type="file" id="purInput" accept=".xlsx,.xls,.csv" multiple>
        <div class="pur-drop-icon">⊞</div>
        <div class="pur-drop-text">
          <div class="pur-drop-title">拖入或点击选择 · 供应商 Excel</div>
          <div class="pur-drop-sub">COL[1] 条码/型号 · COL[3] 价格 · COL[6] 数量 · .xls / .xlsx / .csv</div>
        </div>
        <div class="pur-drop-schema">SCHEMA · v2</div>
        <button class="pur-cta pur-cta--primary" type="button" id="purBrowseBtn">↑ 浏览文件</button>
      </div>

      <!-- 解析结果 panel -->
      <section class="pur-panel" id="purResultsPanel">
        <header class="pur-panel-hd">
          <span class="pur-panel-code">RES-04</span>
          <span class="pur-panel-title">解析结果</span>
          <span class="pur-panel-sub" id="purPanelSub">等待文件</span>
          <span class="pur-panel-spacer"></span>
          <span class="pur-pill pur-pill--ghost" id="purStatePill">未解析</span>
          <span class="pur-pill pur-pill--ghost pur-filename" id="purFilename" hidden></span>
        </header>
        <div class="pur-results-wrap" id="purResultsWrap">
          <div class="pur-results" id="purResults"><div class="pur-empty">上传文件后显示结果</div></div>
        </div>
        <footer class="pur-panel-ft">
          <span class="pur-foot-stat" id="purFooter">SUM · 0 ROWS · 0 UNITS</span>
          <span class="pur-status" id="purStatus"></span>
          <span class="pur-panel-spacer"></span>
          <button class="pur-cta pur-cta--ghost" id="purCopy" disabled>⎘ 一键复制</button>
          <button class="pur-cta pur-cta--ghost" id="purImport" disabled>↪ 一键入库</button>
          <button class="pur-cta pur-cta--primary" id="purDl" disabled>↓ 下载全部</button>
        </footer>
      </section>

      <!-- 新条码处理 panel -->
      <section class="pur-panel pur-newbox pur-hidden" id="purNewBox">
        <header class="pur-panel-hd">
          <span class="pur-panel-code">NEW-04</span>
          <span class="pur-panel-title">新条码处理</span>
          <span class="pur-panel-spacer"></span>
          <button class="pur-cta pur-cta--ghost" id="purNewCopyAll">⎘ 复制全部条码</button>
        </header>
        <div class="pur-supplier">
          <label class="pur-field"><span>供应商 ID</span><input class="pur-inp" id="purSupId" placeholder="必填"></label>
          <label class="pur-field"><span>供应商名称</span><input class="pur-inp" id="purSupName" placeholder="必填"></label>
        </div>
        <div id="purNewList" class="pur-newlist"></div>
      </section>

      <!-- HISTORY · 月度总结 strip -->
      <div class="pur-history" id="purSummarySection">
        <span class="pur-history-code">HISTORY · 月份</span>
        <select class="pur-inp pur-inp--mono" id="purSumMonth"></select>
        <span class="pur-history-stat" id="purSumCount">— 条记录</span>
        <span class="pur-panel-spacer"></span>
        <button class="pur-cta pur-cta--ghost" id="purSumAdd">+ 补录</button>
        <button class="pur-cta pur-cta--ghost" id="purSumManage">⌗ 管理</button>
        <button class="pur-cta pur-cta--primary" id="purSumDl">⌖ 下载 PDF</button>
      </div>

      <!-- Modals （样式 token 化但 DOM 结构不变） -->
      <div class="pur-modal-overlay pur-hidden" id="purModalOverlay">
        <div class="pur-modal">
          <div class="pur-modal-title">记录到月度总结</div>
          <label>供应商名称<input class="pur-inp" id="purMsSupplier" placeholder="必填"></label>
          <label>总价 (€)<input class="pur-inp" id="purMsTotal" type="number" step="0.01"></label>
          <label>税金 (€)<input class="pur-inp" id="purMsTax" type="number" step="0.01" placeholder="必填"></label>
          <label>特殊税 (€)<input class="pur-inp" id="purMsSpecialTax" type="number" step="0.01" placeholder="可选（如环保税）"></label>
          <label>加税总价 (€)<input class="pur-inp" id="purMsTotalTax" disabled></label>
          <label>开票日期<input class="pur-inp" id="purMsDate" type="date"></label>
          <label>目标月份<input class="pur-inp" id="purMsMonth" type="month"></label>
          <div class="pur-modal-actions">
            <button class="pur-cta pur-cta--primary" id="purMsConfirm">确认并导出</button>
            <button class="pur-cta pur-cta--ghost" id="purMsSkip">跳过，直接导出</button>
            <button class="pur-cta pur-cta--ghost" id="purMsCancel">取消</button>
          </div>
        </div>
      </div>
      <div class="pur-modal-overlay pur-hidden" id="purMgrOverlay">
        <div class="pur-modal">
          <div class="pur-modal-hd">月度记录管理 <span id="purMgrMonth"></span></div>
          <input class="pur-inp" id="purMgrSearch" placeholder="搜索供应商/日期/金额">
          <div id="purMgrList" class="pur-mgr-list"></div>
          <div class="pur-modal-actions">
            <button class="pur-cta pur-cta--ghost" id="purMgrClose">关闭</button>
          </div>
        </div>
      </div>`;
    // 浏览按钮的点击靠 setupDropZone 的 parent click 冒泡触发 inputEl.click()，
    // 这里不再单独绑 handler 以避免 inputEl.click() 被调两次（部分浏览器会忽略第二次或闪退 dialog）
    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    setupDropZone(drop, input, (files) => handleFiles(files));
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purImport').addEventListener('click', importToStockpile);
    document.getElementById('purNewCopyAll').addEventListener('click', copyNewBarcodes);
    document.getElementById('purDl').addEventListener('click', downloadZip);
    document.getElementById('purSupId').addEventListener('input', (e) => { supplierInfo.id = e.target.value.trim(); updateButtons(); });
    document.getElementById('purSupName').addEventListener('input', (e) => { supplierInfo.name = e.target.value.trim(); updateButtons(); });
    document.getElementById('purMsTax').addEventListener('input', updateTotalTax);
    document.getElementById('purMsSpecialTax').addEventListener('input', updateTotalTax);
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
    if (files.length < 1) { setStatus('请上传供应商 Excel 文件', true); return; }
    storedSupplierFile = files[0];
    setStatus('解析中...');
    const fd = new FormData();
    fd.append('files', storedSupplierFile);
    try {
      const res = await fetch('/purchase/process', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      rows = body.rows;
      systemBarcodes = new Set(body.system_barcodes);
      inactiveBarcodes = new Set(body.inactive_barcodes || []);
      newEntries = body.new_barcodes.map(bc => ({ barcode: bc, name: '', invoice_name: '' }));
      savedNewEntries = [];
      // 主导供应商预填（每张采购单只一家供应商，多数决即可；
      // 既写入"新条码处理"的 purSupId/purSupName，也供下载模态框 purMsSupplier 用）
      const sug = body.suggested_supplier;
      if (sug && sug.supplier_id && sug.supplier_name) {
        supplierInfo.id = sug.supplier_id;
        supplierInfo.name = sug.supplier_name;
        const idInp = document.getElementById('purSupId');
        const nameInp = document.getElementById('purSupName');
        if (idInp) idInp.value = sug.supplier_id;
        if (nameInp) nameInp.value = sug.supplier_name;
      } else {
        supplierInfo.id = '';
        supplierInfo.name = '';
      }
      // 文件名 pill
      const fileEl = document.getElementById('purFilename');
      if (fileEl) {
        fileEl.textContent = storedSupplierFile.name;
        fileEl.hidden = false;
      }
      renderResults();
      renderNewBox();
      setStatus(`解析完成`);
    } catch (e) {
      setStatus('解析失败：' + e.message, true);
    }
  }

  function rowStatus(r) {
    if (r.price_flagged) return { key: 'check', label: 'CHECK' };
    if (!systemBarcodes.has(r.barcode)) return { key: 'new', label: 'NEW' };
    if (inactiveBarcodes.has(r.barcode)) return { key: 'off', label: 'OFF' };
    return { key: 'match', label: 'MATCH' };
  }

  function renderResults() {
    const container = document.getElementById('purResults');
    if (!rows.length) {
      container.innerHTML = '<div class="pur-empty">未解析到数据</div>';
      updateButtons();
      renderFooter();
      updatePanelMeta();
      return;
    }
    const trs = rows.map((r, i) => {
      const st = rowStatus(r);
      const pill = `<span class="pur-pill pur-pill--${st.key}">${st.label}</span>`;
      const idx = String(i + 1).padStart(2, '0');
      const priceCell = r.price_flagged
        ? `<input class="pur-price-input" data-i="${i}" value="${r.price}" title="价格小数超2位，请修改">`
        : Number(r.price).toFixed(2);
      return `<tr class="pur-row${r.price_flagged ? ' flagged' : ''}" data-i="${i}">
        <td class="pur-td-num pur-td-idx">${idx}</td>
        <td class="pur-td-bc">${escapeHtml(r.barcode)}</td>
        <td class="pur-td-num pur-td-price">${priceCell}</td>
        <td class="pur-td-num">${r.quantity}</td>
        <td class="pur-td-state">${pill}</td>
      </tr>`;
    }).join('');
    container.innerHTML = `
      <table class="pur-table">
        <thead><tr>
          <th class="pur-th-num">#</th>
          <th>条码</th>
          <th class="pur-th-num">单价</th>
          <th class="pur-th-num">数量</th>
          <th>状态</th>
        </tr></thead>
        <tbody>${trs}</tbody>
      </table>
    `;
    container.querySelectorAll('.pur-price-input').forEach(el => {
      el.addEventListener('input', onPriceEdit);
      el.addEventListener('change', onPriceEdit);
    });
    updateButtons();
    renderFooter();
    updatePanelMeta();
  }

  function updatePanelMeta() {
    const sub = document.getElementById('purPanelSub');
    const pill = document.getElementById('purStatePill');
    if (!rows.length) {
      if (sub) sub.textContent = '等待文件';
      if (pill) {
        pill.textContent = '未解析';
        pill.className = 'pur-pill pur-pill--ghost';
      }
      return;
    }
    const units = rows.reduce((s, r) => s + (Number(r.quantity) || 0), 0);
    if (sub) sub.textContent = `${rows.length} 行 · ${units} 件`;
    if (pill) {
      const flagN = rows.filter(r => r.price_flagged).length;
      if (flagN) {
        pill.textContent = `待校 ${flagN}`;
        pill.className = 'pur-pill pur-pill--warn';
      } else {
        pill.textContent = '已解析';
        pill.className = 'pur-pill pur-pill--accent';
      }
    }
  }

  function renderFooter() {
    const el = document.getElementById('purFooter');
    if (!el) return;
    if (!rows.length) {
      el.textContent = 'SUM · 0 ROWS · 0 UNITS';
      return;
    }
    const units = rows.reduce((s, r) => s + (Number(r.quantity) || 0), 0);
    const sum = rows.reduce(
      (s, r) => s + (Number(r.price) || 0) * (Number(r.quantity) || 0),
      0,
    );
    const flagN = rows.filter(r => r.price_flagged).length;
    const newN = rows.filter(r => !systemBarcodes.has(r.barcode)).length;
    const offN = rows.filter(r => systemBarcodes.has(r.barcode) && inactiveBarcodes.has(r.barcode)).length;
    let txt = `SUM · €${sum.toFixed(2)} · ${rows.length} ROWS · ${units.toLocaleString()} UNITS`;
    if (newN) txt += ` · NEW ${newN}`;
    if (offN) txt += ` · OFF ${offN}`;
    if (flagN) txt += ` · CHECK ${flagN}`;
    el.textContent = txt;
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
    if (!newEntries.length) { box.classList.add('pur-hidden'); updateButtons(); return; }
    box.classList.remove('pur-hidden');
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
    // 价格变化后：当前行 pill 文本/颜色就地刷新，不重渲染避免 input 失焦
    const rowEl = e.target.closest('.pur-row');
    const pillEl = rowEl?.querySelector('.pur-pill');
    if (pillEl) {
      const st = rowStatus(rows[i]);
      pillEl.className = `pur-pill pur-pill--${st.key}`;
      pillEl.textContent = st.label;
    }
    rowEl?.classList.toggle('flagged', !valid);
    updateButtons();
    renderFooter();
    updatePanelMeta();
  }

  function updateButtons() {
    const anyFlagged = rows.some(r => r.price_flagged);
    const hasRows = rows.length > 0;
    const hasNew = newEntries.length > 0;
    const newOk = hasNew &&
      (supplierInfo.id && supplierInfo.name && newEntries.every(e => e.name && e.invoice_name));
    document.getElementById('purCopy').disabled = anyFlagged || !hasRows;
    document.getElementById('purImport').disabled = anyFlagged || !hasNew;
    document.getElementById('purDl').disabled = anyFlagged || !hasRows || (hasNew && !newOk);
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

  async function importToStockpile() {
    if (!newEntries.length) return;
    const btn = document.getElementById('purImport');
    btn.disabled = true;
    btn.textContent = '入库中...';
    try {
      const res = await fetch('/purchase/import-to-stockpile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries: newEntries }),
      });
      const body = await res.json();
      if (!body.ok) { setStatus('入库失败：' + body.msg, true); return; }
      setStatus(`入库成功，${body.count} 条新条码已写入本地数据库`);
      savedNewEntries = newEntries.map(e => ({ ...e }));
      newEntries.forEach(e => systemBarcodes.add(e.barcode));
      newEntries = [];
      renderNewBox();
      updateButtons();
      btn.textContent = '已入库 ✓';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = '一键入库';
        btn.classList.remove('copied');
        btn.disabled = true;
      }, 2000);
    } catch (e) {
      setStatus('入库失败：' + e.message, true);
      btn.disabled = false;
      btn.textContent = '一键入库';
    }
  }

  async function downloadZip() {
    if (!storedSupplierFile) return;
    const totalPrice = rows.reduce((sum, r) => sum + r.price * r.quantity, 0);
    const rounded = Math.round(totalPrice * 100) / 100;
    document.getElementById('purMsTotal').value = rounded.toFixed(2);
    document.getElementById('purMsTax').value = '';
    document.getElementById('purMsSpecialTax').value = '';
    document.getElementById('purMsTotalTax').value = '';
    document.getElementById('purMsDate').value = new Date().toISOString().slice(0, 10);
    document.getElementById('purMsMonth').value = new Date().toISOString().slice(0, 7);
    // 自动填入数据库里推断出的供应商名（仍可编辑）
    document.getElementById('purMsSupplier').value = supplierInfo.name || '';
    document.getElementById('purMsSkip').style.display = '';
    document.getElementById('purMsConfirm').onclick = () => confirmWithSummary();
    document.getElementById('purModalOverlay').style.display = 'flex';
  }

  function updateTotalTax() {
    const total = parseFloat(document.getElementById('purMsTotal').value) || 0;
    const tax = parseFloat(document.getElementById('purMsTax').value) || 0;
    const specialTax = parseFloat(document.getElementById('purMsSpecialTax').value) || 0;
    document.getElementById('purMsTotalTax').value = (total + tax + specialTax).toFixed(2);
  }

  async function confirmWithSummary() {
    const supplier = document.getElementById('purMsSupplier').value.trim();
    const total = parseFloat(document.getElementById('purMsTotal').value);
    const tax = parseFloat(document.getElementById('purMsTax').value);
    const specialTax = parseFloat(document.getElementById('purMsSpecialTax').value) || 0;
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
          special_tax: specialTax,
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
    const sourceEntries = newEntries.length ? newEntries : savedNewEntries;
    const entriesForExport = sourceEntries.map(e => ({
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
      const ymd = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const supTag = cleanSupplierForFilename(supplierInfo.name);
      a.download = supTag ? `${ymd}${supTag}.zip` : `采购订单${ymd}.zip`;
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
      const recs = body.records || [];
      const total = recs.reduce((s, r) => s + (Number(r.total_with_tax) || 0), 0);
      const el = document.getElementById('purSumCount');
      if (!el) return;
      const count = body.count || 0;
      el.innerHTML = `<span class="pur-num--ok">${count}</span> 条记录 · 累计 <span class="pur-num--accent">€${total.toFixed(2)}</span>`;
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
    document.getElementById('purMsSpecialTax').value = '';
    document.getElementById('purMsTotalTax').value = '';
    document.getElementById('purMsDate').value = '';
    document.getElementById('purMsMonth').value = month;
    document.getElementById('purMsSupplier').value = '';
    document.getElementById('purMsSkip').style.display = 'none';
    document.getElementById('purMsConfirm').onclick = async () => {
      const supplier = document.getElementById('purMsSupplier').value.trim();
      const total = parseFloat(document.getElementById('purMsTotal').value);
      const tax = parseFloat(document.getElementById('purMsTax').value);
      const specialTax = parseFloat(document.getElementById('purMsSpecialTax').value) || 0;
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
            special_tax: specialTax,
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
    list.innerHTML = filtered.map(({ rec, idx }) => {
      const specialTaxCell = Number(rec.special_tax) > 0
        ? `<div class="pur-mgr-cell">特 €${Number(rec.special_tax).toFixed(2)}</div>`
        : '';
      return `
      <div class="pur-mgr-row">
        <div class="pur-mgr-cell"><b>${escapeHtml(rec.supplier_name)}</b></div>
        <div class="pur-mgr-cell">${escapeHtml(rec.invoice_date)}</div>
        <div class="pur-mgr-cell">总 €${Number(rec.total_price).toFixed(2)}</div>
        <div class="pur-mgr-cell">税 €${Number(rec.tax).toFixed(2)}</div>
        ${specialTaxCell}
        <div class="pur-mgr-cell">含税 €${Number(rec.total_with_tax).toFixed(2)}</div>
        <button class="pur-btn-copy pur-mgr-del" data-idx="${idx}">删除</button>
      </div>
      `;
    }).join('');
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

  // 把供应商名压成文件名 tag：
  // 1) 去括号备注 (...) / （...）
  // 2) 去是纯数字的 token（典型是电话号码）
  // 3) 剩余 token 拼起来（去空格）
  // 4) 移除文件系统非法字符
  // 例：'HOMEPLAST 6972888853 (希腊本地供应商)' → 'HOMEPLAST'
  //     'et plast' → 'etplast'
  //     'NEW NORTON' → 'NEWNORTON'
  function cleanSupplierForFilename(name) {
    if (!name) return '';
    let s = String(name).replace(/[(（][^)）]*[)）]/g, '');
    s = s.split(/\s+/).filter(t => t && !/^\d+$/.test(t)).join('');
    // eslint-disable-next-line no-control-regex
    return s.replace(/[<>:"/\\|?*\x00-\x1f]/g, '').slice(0, 40).toUpperCase();
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
  });
})();