(function () {
  let storedFile = null;
  let rows = [];

  function init() {
    const page = document.getElementById('pagePurchase');
    if (!page) return;
    page.innerHTML = `
      <div class="pur-drop" id="purDrop">
        <input type="file" id="purInput" accept=".xlsx,.xls">
        <div>拖入或点击选择供应商 Excel 文件</div>
        <div class="hint">第1列条码 · 第3列价格 · 第6列数量</div>
      </div>
      <div class="pur-results" id="purResults"><div class="empty">上传文件后显示结果</div></div>
      <div class="pur-actions">
        <div class="pur-status" id="purStatus"></div>
        <button class="pur-btn-copy" id="purCopy" disabled>一键复制</button>
        <button class="pur-btn-dl" id="purDl" disabled>下载采购订单</button>
      </div>`;

    const drop = document.getElementById('purDrop');
    const input = document.getElementById('purInput');
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); handleFile(e.dataTransfer.files[0]); });
    input.addEventListener('change', () => { handleFile(input.files[0]); input.value = ''; });
    document.getElementById('purCopy').addEventListener('click', copyAll);
    document.getElementById('purDl').addEventListener('click', downloadExcel);
  }

  async function handleFile(file) {
    if (!file) return;
    storedFile = file;
    setStatus('解析中...');
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/purchase/process', { method: 'POST', body: fd });
      const body = await res.json();
      if (!body.ok) { setStatus(body.msg, true); return; }
      rows = body.rows;
      renderResults();
      const flagCount = rows.filter(r => r.price_flagged).length;
      setStatus(`共 ${rows.length} 条${flagCount ? `，${flagCount} 条需修改价格` : ''}`);
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
    document.getElementById('purCopy').disabled = anyFlagged || !hasRows;
    document.getElementById('purDl').disabled = anyFlagged || !hasRows;
  }

  async function copyAll() {
    const text = rows.map(r => r.formatted).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      const btn = document.getElementById('purCopy');
      btn.textContent = '已复制 ✓';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '一键复制'; btn.classList.remove('copied'); }, 2000);
    } catch (e) {
      setStatus('复制失败：' + e.message, true);
    }
  }

  async function downloadExcel() {
    if (!storedFile) return;
    const btn = document.getElementById('purDl');
    btn.disabled = true;
    const fd = new FormData();
    fd.append('file', storedFile);
    fd.append('rows', JSON.stringify(rows));
    try {
      const res = await fetch('/purchase/export', { method: 'POST', body: fd });
      if (!res.ok) { const b = await res.json(); setStatus(b.msg, true); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `采购订单${new Date().toISOString().slice(0,10).replace(/-/g,'')}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatus('下载失败：' + e.message, true);
    } finally {
      updateButtons();
    }
  }

  function setStatus(msg, isError = false) {
    const el = document.getElementById('purStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'pur-status' + (isError ? ' error' : '');
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
