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
      <!-- 01-A 完整投递区（空态） -->
      <section class="pnl" id="purDropFull">
        <div class="pnl-hd">
          <span class="pnl-code">01</span>
          <span class="pnl-title">文件投递</span>
          <span class="pnl-sub">供应商 Excel</span>
          <span class="pnl-spacer"></span>
          <span class="pnl-pill">.xlsx</span>
          <span class="pnl-pill">.xls</span>
          <span class="pnl-pill">.csv</span>
        </div>
        <div class="pnl-bd">
          <div class="drop-zone" id="purDrop">
            <input type="file" id="purInput" accept=".xlsx,.xls,.csv" multiple style="display:none;">
            <div class="drop-icon">⊞</div>
            <div class="drop-text">
              <div class="drop-main">拖入或点击 · 供应商 Excel</div>
              <div class="drop-hint">列映射：<code>COL[1]</code> 条码 · <code>COL[3]</code> 单价 · <code>COL[6]</code> 数量 · 上传后自动匹配 stockpile</div>
            </div>
            <button class="btn btn--primary" type="button" id="purBrowseBtn">↑ 浏览文件</button>
          </div>
        </div>
      </section>

      <!-- 01-B 紧凑 strip（已解析态） -->
      <div class="drop-strip" id="purDropStrip" style="display:none;">
        <div class="drop-strip-icon">⊞</div>
        <div class="drop-strip-text">拖入新文件替换 · 当前：<b id="purStripName">—</b></div>
        <span class="drop-strip-file" id="purStripSize"></span>
        <span class="pnl-spacer"></span>
        <span id="purStripSupplier" style="font-size:var(--fs-sm);font-weight:600;color:var(--accent);"></span>
        <span class="pill pill--accent pill--xs" id="purStripCount"></span>
      </div>

      <!-- 02 解析结果 -->
      <section class="pnl" id="purResultsPanel">
        <div class="pnl-hd">
          <span class="pnl-code">02</span>
          <span class="pnl-title">解析结果</span>
          <span class="pnl-sub" id="purPanelSub">等待文件</span>
          <span class="pnl-spacer"></span>
          <span class="pill pill--off pill--xs" id="purStatePill">未解析</span>
        </div>
        <div id="purResultsWrap" style="overflow:auto;max-height:340px;">
          <div id="purResults"><div class="pnl-empty">上传供应商 Excel 后自动解析</div></div>
        </div>
        <div class="pnl-ft">
          <span class="pnl-ft-stat" id="purFooter">SUM · 0 ROWS · 0 UNITS</span>
          <span class="pur-status" id="purStatus"></span>
          <span class="pnl-spacer"></span>
          <button class="btn btn--ghost" id="purCopy" disabled>⎘ 一键复制</button>
          <button class="btn btn--ghost" id="purImport" disabled>↪ 一键入库</button>
          <button class="btn btn--primary" id="purDl" disabled>↓ 下载全部</button>
        </div>
      </section>

      <!-- 03 新条码处理 -->
      <section class="pnl" id="purNewBox" style="display:none;">
        <div class="pnl-hd">
          <span class="pnl-code">03</span>
          <span class="pnl-title">新条码</span>
          <span class="pnl-sub" id="purNewSub">需填写品名后导出</span>
          <span class="pnl-spacer"></span>
          <button class="btn btn--ghost" id="purNewCopyAll" style="font-size:var(--fs-xs);">⎘ 复制条码</button>
        </div>
        <div class="new-hd">
          <span class="new-sup-label">供应商</span>
          <input class="new-inp" id="purSupId" placeholder="供应商 ID（必填）" style="max-width:140px;">
          <input class="new-inp" id="purSupName" placeholder="供应商名称（必填）" style="max-width:220px;">
          <span class="new-sup-val" id="purSupAuto" style="display:none;">✓ 自动识别</span>
        </div>
        <table class="new-tbl">
          <thead><tr>
            <th style="width:140px;">条码</th>
            <th>品名（第 4 列）</th>
            <th>发票品名（第 5 列）</th>
            <th style="width:120px;"></th>
          </tr></thead>
          <tbody id="purNewList"></tbody>
        </table>
      </section>

      <!-- 04 HISTORY · 月度总结 -->
      <div class="ms" id="purSummarySection">
        <span class="ms-code">HISTORY · 月度总结</span>
        <select class="ms-sel" id="purSumMonth"></select>
        <span class="ms-stat" id="purSumCount">— 条记录</span>
        <span class="pnl-spacer"></span>
        <button class="btn btn--ghost" id="purSumAdd">+ 补录</button>
        <button class="btn btn--ghost" id="purSumManage">⌗ 管理</button>
        <button class="btn btn--primary" id="purSumDl">⌖ 下载 PDF</button>
      </div>

      <!-- 记录模态框 -->
      <div class="modal-overlay" id="purModalOverlay" style="display:none;">
        <div class="modal">
          <div class="modal-hd">记录到月度总结</div>
          <div class="modal-bd">
            <div class="mf"><span class="mf-label">供应商名称</span><input class="mf-inp" id="purMsSupplier" placeholder="必填"></div>
            <div class="modal-grid2">
              <div class="mf"><span class="mf-label">总价 (€)</span><input class="mf-inp" id="purMsTotal" type="number" step="0.01"></div>
              <div class="mf"><span class="mf-label">税金 (€)</span><input class="mf-inp" id="purMsTax" type="number" step="0.01" placeholder="必填"></div>
            </div>
            <div class="modal-grid2">
              <div class="mf"><span class="mf-label">特殊税 (€)</span><input class="mf-inp" id="purMsSpecialTax" type="number" step="0.01" placeholder="可选（如环保税）"></div>
              <div class="mf"><span class="mf-label">加税总价 (€)</span><input class="mf-inp" id="purMsTotalTax" disabled></div>
            </div>
            <div class="modal-grid2">
              <div class="mf"><span class="mf-label">开票日期</span><input class="mf-inp" id="purMsDate" type="date"></div>
              <div class="mf"><span class="mf-label">目标月份</span><input class="mf-inp" id="purMsMonth" type="month"></div>
            </div>
          </div>
          <div class="modal-ft">
            <button class="btn btn--ghost" id="purMsCancel">取消</button>
            <button class="btn btn--ghost" id="purMsSkip">跳过，直接导出</button>
            <button class="btn btn--primary" id="purMsConfirm">确认并导出</button>
          </div>
        </div>
      </div>

      <!-- 月度记录管理模态框 -->
      <div class="modal-overlay" id="purMgrOverlay" style="display:none;">
        <div class="modal modal--wide">
          <div class="modal-hd">月度记录管理 <span id="purMgrMonth"></span></div>
          <div class="modal-bd">
            <input class="mf-inp" id="purMgrSearch" placeholder="搜索供应商 / 日期 / 金额">
            <div id="purMgrList"></div>
          </div>
          <div class="modal-ft">
            <button class="btn btn--ghost" id="purMgrClose">关闭</button>
          </div>
        </div>
      </div>`;
    // 浏览按钮的点击靠 setupDropZone 的 parent click 冒泡触发 inputEl.click()，
    // 这里不再单独绑 handler 以避免 inputEl.click() 被调两次（部分浏览器会忽略第二次或闪退 dialog）
    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    setupDropZone(drop, input, (files) => handleFiles(files));
    // strip：复用同一 input（不再调 setupDropZone 以免重复绑 change → 双上传）
    const strip = document.getElementById('purDropStrip');
    strip.addEventListener('click', () => input.click());
    strip.addEventListener('dragover', (e) => { e.preventDefault(); strip.classList.add('drag-over'); });
    strip.addEventListener('dragleave', () => strip.classList.remove('drag-over'));
    strip.addEventListener('drop', (e) => { e.preventDefault(); strip.classList.remove('drag-over'); handleFiles(e.dataTransfer.files); });
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purImport').addEventListener('click', importToStockpile);
    document.getElementById('purNewCopyAll').addEventListener('click', copyNewBarcodes);
    document.getElementById('purDl').addEventListener('click', downloadZip);
    document.getElementById('purSupId').addEventListener('input', (e) => { supplierInfo.id = e.target.value.trim(); updateButtons(); });
    document.getElementById('purSupName').addEventListener('input', (e) => { supplierInfo.name = e.target.value.trim(); updateButtons(); updateStrip(); });
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

  function setParsedView(parsed) {
    const full = document.getElementById('purDropFull');
    const strip = document.getElementById('purDropStrip');
    if (full) full.style.display = parsed ? 'none' : 'flex';
    if (strip) strip.style.display = parsed ? 'flex' : 'none';
  }

  function humanSize(bytes) {
    if (bytes == null) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function updateStrip() {
    const nameEl = document.getElementById('purStripName');
    const sizeEl = document.getElementById('purStripSize');
    const supEl = document.getElementById('purStripSupplier');
    const cntEl = document.getElementById('purStripCount');
    if (nameEl && storedSupplierFile) nameEl.textContent = storedSupplierFile.name;
    if (sizeEl && storedSupplierFile) sizeEl.textContent = humanSize(storedSupplierFile.size);
    if (supEl) supEl.textContent = supplierInfo.name || '';
    if (cntEl) {
      const units = rows.reduce((s, r) => s + (Number(r.quantity) || 0), 0);
      cntEl.textContent = `${rows.length} 行 · ${units} 件`;
    }
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
      const autoEl = document.getElementById('purSupAuto');
      if (sug && sug.supplier_id && sug.supplier_name) {
        supplierInfo.id = sug.supplier_id;
        supplierInfo.name = sug.supplier_name;
        const idInp = document.getElementById('purSupId');
        const nameInp = document.getElementById('purSupName');
        if (idInp) idInp.value = sug.supplier_id;
        if (nameInp) nameInp.value = sug.supplier_name;
        if (autoEl) autoEl.style.display = '';
      } else {
        supplierInfo.id = '';
        supplierInfo.name = '';
        if (autoEl) autoEl.style.display = 'none';
      }
      setParsedView(true);
      renderResults();
      renderNewBox();
      updateStrip();
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
      container.innerHTML = '<div class="pnl-empty">未解析到数据</div>';
      setParsedView(false);
      updateButtons();
      renderFooter();
      updatePanelMeta();
      return;
    }
    const trs = rows.map((r, i) => {
      const st = rowStatus(r);
      const pill = `<span class="pill pill--${st.key}">${st.label}</span>`;
      const idx = String(i + 1).padStart(2, '0');
      const priceCell = r.price_flagged
        ? `<input class="price-inp" data-i="${i}" value="${r.price}" title="价格小数超2位，请修改">`
        : Number(r.price).toFixed(2);
      return `<tr class="pur-row${r.price_flagged ? ' flagged' : ''}" data-i="${i}">
        <td class="idx">${idx}</td>
        <td><span class="bc">${escapeHtml(r.barcode)}</span></td>
        <td class="r">${priceCell}</td>
        <td class="r">${r.quantity}</td>
        <td>${pill}</td>
      </tr>`;
    }).join('');
    container.innerHTML = `
      <table class="tbl">
        <thead><tr>
          <th class="idx">#</th>
          <th>条码</th>
          <th class="r">单价</th>
          <th class="r">数量</th>
          <th>状态</th>
        </tr></thead>
        <tbody>${trs}</tbody>
      </table>
    `;
    container.querySelectorAll('.price-inp').forEach(el => {
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
        pill.className = 'pill pill--off pill--xs';
      }
      return;
    }
    const units = rows.reduce((s, r) => s + (Number(r.quantity) || 0), 0);
    if (sub) sub.textContent = `${rows.length} 行 · ${units} 件`;
    if (pill) {
      const flagN = rows.filter(r => r.price_flagged).length;
      if (flagN) {
        pill.textContent = `待校 ${flagN}`;
        pill.className = 'pill pill--check pill--xs';
      } else {
        pill.textContent = '已解析';
        pill.className = 'pill pill--accent pill--xs';
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
      setTimeout(() => { btn.textContent = '⎘ 复制条码'; btn.classList.remove('copied'); }, 2000);
    };
    try {
      await copyToClip(text);
      done();
    } catch (e) { setStatus('复制失败：' + e.message, true); }
  }

  function renderNewBox() {
    const box = document.getElementById('purNewBox');
    const list = document.getElementById('purNewList');
    const sub = document.getElementById('purNewSub');
    if (!newEntries.length) { box.style.display = 'none'; updateButtons(); return; }
    box.style.display = 'flex';
    if (sub) sub.textContent = `${newEntries.length} 条 · 需填写品名后导出`;
    list.innerHTML = newEntries.map((e, i) => `
      <tr class="pur-new-row" data-i="${i}">
        <td><span class="bc v-info">${escapeHtml(e.barcode)}</span></td>
        <td><input class="new-inp pur-new-name" data-i="${i}" data-field="name" value="${escapeAttr(e.name)}" placeholder="例：保温杯 500ml"></td>
        <td><input class="new-inp pur-new-name" data-i="${i}" data-field="invoice_name" value="${escapeAttr(e.invoice_name)}" placeholder="例：ΘΕΡΜΟΣ 500ML"></td>
        <td><div class="new-acts">
          <button class="na na--fix pur-new-mod" data-i="${i}">保存</button>
          <button class="na na--fix pur-new-del" data-i="${i}">改码</button>
          <button class="na na--del pur-new-remove" data-i="${i}">删</button>
        </div></td>
      </tr>`).join('');
    list.querySelectorAll('.pur-new-name').forEach(el => {
      el.addEventListener('input', ev => {
        const t = ev.target;
        newEntries[+t.dataset.i][t.dataset.field] = t.value.trim();
        updateButtons();
      });
    });
    list.querySelectorAll('.pur-new-mod').forEach(el => {
      el.addEventListener('click', ev => {
        const btn = ev.currentTarget;
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
        btn.textContent = '已保存 ✓';
        btn.classList.add('saved');
        rowEl && rowEl.classList.add('saved-flash');
        setTimeout(() => {
          btn.textContent = '保存';
          btn.classList.remove('saved');
          rowEl && rowEl.classList.remove('saved-flash');
        }, 1500);
      });
    });
    list.querySelectorAll('.pur-new-del').forEach(el => {
      el.addEventListener('click', ev => startDelete(+ev.currentTarget.dataset.i));
    });
    list.querySelectorAll('.pur-new-remove').forEach(el => {
      el.addEventListener('click', ev => removeNewEntry(+ev.currentTarget.dataset.i));
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
    updateStrip();
    setStatus(`已删除条码 ${bc}`);
  }

  function startDelete(i) {
    const list = document.getElementById('purNewList');
    const rowEl = list.querySelector(`.pur-new-row[data-i="${i}"]`);
    if (!rowEl) return;
    const oldBc = newEntries[i].barcode;
    rowEl.innerHTML = `<td colspan="4"><input class="new-inp pur-new-correct" placeholder="输入修正后的条码，回车确认 / Esc 取消"></td>`;
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
    const rowEl = e.target.closest('tr');
    const pillEl = rowEl?.querySelector('.pill');
    if (pillEl) {
      const st = rowStatus(rows[i]);
      pillEl.className = `pill pill--${st.key}`;
      pillEl.textContent = st.label;
    }
    rowEl?.classList.toggle('flagged', !valid);
    updateButtons();
    renderFooter();
    updatePanelMeta();
    updateStrip();
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
      setTimeout(() => { btn.textContent = '⎘ 一键复制'; btn.classList.remove('copied'); }, 2000);
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
        btn.textContent = '↪ 一键入库';
        btn.classList.remove('copied');
        btn.disabled = true;
      }, 2000);
    } catch (e) {
      setStatus('入库失败：' + e.message, true);
      btn.disabled = false;
      btn.textContent = '↪ 一键入库';
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
      el.innerHTML = `<b>${count}</b> 条记录 · 累计 <b class="v-accent">€${total.toFixed(2)}</b>`;
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
      list.innerHTML = '<div class="pnl-empty">无匹配记录</div>';
      return;
    }
    const trs = filtered.map(({ rec, idx }) => {
      const special = Number(rec.special_tax) > 0
        ? ` <span class="v-warn">特 €${Number(rec.special_tax).toFixed(2)}</span>` : '';
      return `<tr>
        <td><b>${escapeHtml(rec.supplier_name)}</b></td>
        <td class="bc">${escapeHtml(rec.invoice_date)}</td>
        <td class="r">€${Number(rec.total_price).toFixed(2)}</td>
        <td class="r">€${Number(rec.tax).toFixed(2)}${special}</td>
        <td class="r v-accent">€${Number(rec.total_with_tax).toFixed(2)}</td>
        <td class="r"><button class="na na--del pur-mgr-del" data-idx="${idx}">删除</button></td>
      </tr>`;
    }).join('');
    list.innerHTML = `
      <table class="tbl">
        <thead><tr>
          <th>供应商</th><th>开票日期</th>
          <th class="r">总价</th><th class="r">税</th><th class="r">含税</th><th class="r"></th>
        </tr></thead>
        <tbody>${trs}</tbody>
      </table>`;
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
