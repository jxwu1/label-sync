import { esc } from "./shared.js";

function initTabs() {
  const tabs = document.querySelectorAll("#spTabs .tabs__tab");
  const panels = document.querySelectorAll('[data-tab-panel]');
  tabs.forEach((t) => {
    t.addEventListener("click", () => {
      const target = t.dataset.tab;
      tabs.forEach((x) => x.classList.toggle("active", x === t));
      panels.forEach((p) => p.classList.toggle("active", p.dataset.tabPanel === target));
    });
  });
}

export function initStockpile() {
  initTabs();

  const spStatus = document.getElementById('spStatus');
  const spInitDrop = document.getElementById('spInitDrop');
  const spInitInput = document.getElementById('spInitInput');
  const spInitBtn = document.getElementById('spInitBtn');
  const spInitMsg = document.getElementById('spInitMsg');
  const spCmpDrop = document.getElementById('spCmpDrop');
  const spCmpInput = document.getElementById('spCmpInput');
  const spCmpBtn = document.getElementById('spCmpBtn');
  const spCmpRes = document.getElementById('spCmpRes');

  spCmpRes.addEventListener('click', e => {
      if (e.target.id === 'spOverwriteBtn') {
          overwriteLocations();
          return;
      }
      const btn = e.target.closest('.sp-edit-btn');
      if (!btn) return;
      const row = btn.closest('.sp-mismatch-row');

      if (btn.classList.contains('sp-saving')) {
          const inp = row.querySelector('input');
          if (inp) { saveLocation(btn, inp); }
          return;
      }

      const span = row.querySelector('.sp-loc-val');
      if (!span) return;

      const barcode = btn.dataset.barcode;
      const curLoc = btn.dataset.local;
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.value = curLoc;
      inp.style.cssText = 'width:80px;padding:2px 4px;font-size:12px;border:1px solid #1976d2;border-radius:3px;margin:0 2px';
      span.replaceWith(inp);
      btn.textContent = '保存';
      btn.classList.add('sp-saving');

      inp.addEventListener('keydown', ev => {
          if (ev.key === 'Enter') saveLocation(btn, inp);
          if (ev.key === 'Escape') {
              const ns = document.createElement('span');
              ns.className = 'sp-loc-val';
              ns.textContent = curLoc;
              inp.replaceWith(ns);
              btn.textContent = '编辑';
              btn.classList.remove('sp-saving');
          }
      });
      inp.focus();
  });

  async function saveLocation(btn, inp) {
      const barcode = btn.dataset.barcode;
      const newLoc = inp.value.trim();
      btn.disabled = true;
      btn.textContent = '保存中...';
      try {
          const res = await fetch('/stockpile/update-location', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ barcode, location: newLoc }),
          });
          const data = await res.json();
          if (data.ok) {
              const newSpan = document.createElement('span');
              newSpan.className = 'sp-loc-val';
              newSpan.textContent = newLoc;
              inp.replaceWith(newSpan);
              btn.textContent = '已保存 ✓';
              btn.className = 'sp-edit-btn saved';
              btn.dataset.local = newLoc;
              setTimeout(() => { btn.textContent = '编辑'; btn.className = 'sp-edit-btn'; btn.disabled = false; }, 2000);
          } else {
              btn.textContent = '失败';
              btn.className = 'sp-edit-btn err';
              setTimeout(() => { btn.textContent = '保存'; btn.className = 'sp-edit-btn sp-saving'; btn.disabled = false; }, 2000);
          }
      } catch (ex) {
          btn.textContent = '网络错误';
          btn.className = 'sp-edit-btn err';
          setTimeout(() => { btn.textContent = '保存'; btn.className = 'sp-edit-btn sp-saving'; btn.disabled = false; }, 2000);
      }
  }

  async function overwriteLocations() {
      if (!cmpMismatches.length) return;
      if (!confirm('确认用导出文件的库位覆盖本地数据库？\n将更新 ' + cmpMismatches.length + ' 条记录。')) return;
      const btn = document.getElementById('spOverwriteBtn');
      btn.disabled = true;
      btn.textContent = '覆盖中...';
      try {
          const entries = cmpMismatches.map(m => ({ barcode: m.barcode, location: m.export_location }));
          const res = await fetch('/stockpile/overwrite-locations', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ entries }),
          });
          const data = await res.json();
          if (data.ok) {
              btn.textContent = '已覆盖 ' + data.updated + ' 条 ✓';
              btn.className = 'sp-edit-btn saved';
              spCmpRes.querySelectorAll('.sp-loc-val').forEach(span => { span.textContent = ''; });
              cmpMismatches = [];
              setTimeout(() => { if (btn) { btn.remove(); } }, 3000);
          } else {
              btn.textContent = '失败';
              btn.className = 'sp-edit-btn err';
              btn.disabled = false;
          }
      } catch (ex) {
          btn.textContent = '网络错误';
          btn.className = 'sp-edit-btn err';
          btn.disabled = false;
      }
  }

  let spInitFile = null;
  let spCmpFile = null;
  let cmpMismatches = [];

  spInitDrop.addEventListener('click', () => spInitInput.click());
  spCmpDrop.addEventListener('click', () => spCmpInput.click());

  spInitDrop.addEventListener('dragover', e => { e.preventDefault(); spInitDrop.classList.add('drag'); });
  spInitDrop.addEventListener('dragleave', () => spInitDrop.classList.remove('drag'));
  spInitDrop.addEventListener('drop', e => {
      e.preventDefault();
      spInitDrop.classList.remove('drag');
      if (e.dataTransfer.files.length) {
          spInitInput.files = e.dataTransfer.files;
          spInitFile = e.dataTransfer.files[0];
          spInitBtn.disabled = false;
          spInitDrop.querySelector('div').textContent = spInitFile.name;
      }
  });

  spCmpDrop.addEventListener('dragover', e => { e.preventDefault(); spCmpDrop.classList.add('drag'); });
  spCmpDrop.addEventListener('dragleave', () => spCmpDrop.classList.remove('drag'));
  spCmpDrop.addEventListener('drop', e => {
      e.preventDefault();
      spCmpDrop.classList.remove('drag');
      if (e.dataTransfer.files.length) {
          spCmpInput.files = e.dataTransfer.files;
          spCmpFile = e.dataTransfer.files[0];
          spCmpBtn.disabled = false;
          spCmpDrop.querySelector('div').textContent = spCmpFile.name;
      }
  });

  spInitInput.addEventListener('change', () => {
      if (spInitInput.files.length) {
          spInitFile = spInitInput.files[0];
          spInitBtn.disabled = false;
          spInitDrop.querySelector('div').textContent = spInitFile.name;
      }
  });

  spCmpInput.addEventListener('change', () => {
      if (spCmpInput.files.length) {
          spCmpFile = spCmpInput.files[0];
          spCmpBtn.disabled = false;
          spCmpDrop.querySelector('div').textContent = spCmpFile.name;
      }
  });

  spInitBtn.addEventListener('click', async () => {
      if (!spInitFile) return;
      spInitBtn.disabled = true;
      spInitBtn.textContent = '导入中...';
      spInitMsg.textContent = '';

      const form = new FormData();
      form.append('files', spInitFile);

      try {
          const res = await fetch('/stockpile/init', { method: 'POST', body: form });
          const data = await res.json();
          if (data.ok) {
              spInitMsg.textContent = '导入成功，共 ' + data.count + ' 条记录';
              spInitMsg.style.color = '#2e7d32';
              refreshSpStatus();
          } else {
              spInitMsg.textContent = '导入失败：' + data.msg;
              spInitMsg.style.color = '#c62828';
          }
      } catch (e) {
          spInitMsg.textContent = '网络错误';
          spInitMsg.style.color = '#c62828';
      }
      spInitBtn.disabled = false;
      spInitBtn.textContent = '初始化';
  });

  spCmpBtn.addEventListener('click', async () => {
      if (!spCmpFile) return;
      spCmpBtn.disabled = true;
      spCmpBtn.textContent = '比对中...';
      spCmpRes.innerHTML = '';

      const form = new FormData();
      form.append('files', spCmpFile);

      try {
          const res = await fetch('/stockpile/compare', { method: 'POST', body: form });
          const data = await res.json();
          if (data.ok) {
              const d = data.diff;
              let html = '<b>比对结果：</b><br>';
              html += '本地记录：' + d.total_local + ' &nbsp; 导出记录：' + d.total_export + ' &nbsp; 一致：' + d.consistent + '<br>';
              if (d.only_in_local.length) html += '<span style="color:#e65100">仅本地有：' + esc(d.only_in_local.join(', ')) + '</span><br>';
              if (d.only_in_export.length) html += '<span style="color:#1565c0">仅导出有：' + esc(d.only_in_export.join(', ')) + '</span><br>';
              if (d.mismatches.length) {
                  cmpMismatches = d.mismatches;
                  html += '<span style="color:#c62828">不一致条数：' + d.mismatches.length;
                  html += ' <button class="sp-edit-btn" id="spOverwriteBtn">一键覆盖全部库位</button></span><br>';
                  let showCount = Math.min(d.mismatches.length, 20);
                  for (let i = 0; i < showCount; i++) {
                      const m = d.mismatches[i];
                      html += '<div class="sp-mismatch-row" data-barcode="' + esc(m.barcode) + '">';
                      html += esc(m.barcode) + ': 型号(' + esc(m.local_model) + '→' + esc(m.export_model) + ')';
                      html += ' 库位(<span class="sp-loc-val">' + esc(m.local_location) + '</span>→' + esc(m.export_location) + ')';
                      html += ' <button class="sp-edit-btn" data-barcode="' + esc(m.barcode) + '" data-local="' + esc(m.local_location) + '">编辑</button>';
                      html += '</div>';
                  }
                  if (d.mismatches.length > 20) html += '<br>...等共' + d.mismatches.length + '条';
              }
              if (!d.only_in_local.length && !d.only_in_export.length && !d.mismatches.length) {
                  html += '<b style="color:#2e7d32">完全一致</b>';
              }
              spCmpRes.innerHTML = html;
          } else {
              spCmpRes.innerHTML = '<span style="color:#c62828">比对失败：' + esc(data.msg || '') + '</span>';
          }
      } catch (e) {
          spCmpRes.innerHTML = '<span style="color:#c62828">网络错误</span>';
      }
      spCmpBtn.disabled = false;
      spCmpBtn.textContent = '比对';
  });

  async function refreshSpStatus() {
      try {
          const res = await fetch('/stockpile/status');
          const data = await res.json();
          if (data.initialized) {
              spStatus.textContent = '状态：已初始化，共 ' + data.count + ' 条记录';
              spStatus.style.color = '#2e7d32';
          } else {
              spStatus.textContent = '状态：未初始化，请先上传系统导出文件';
              spStatus.style.color = '#c62828';
          }
      } catch (e) {
          spStatus.textContent = '状态：检查失败';
          spStatus.style.color = '#999';
      }
  }

  const spSearchInput = document.getElementById('spSearchInput');
  const spSearchRes = document.getElementById('spSearchRes');

  let spSearchTimer = null;

  spSearchInput.addEventListener('input', () => {
      clearTimeout(spSearchTimer);
      const q = spSearchInput.value.trim();
      if (q.length < 2) {
          spSearchRes.innerHTML = '';
          return;
      }
      spSearchTimer = setTimeout(() => doSearch(q), 300);
  });

  async function doSearch(q) {
      spSearchRes.innerHTML = '<span style="color:#999">搜索中...</span>';
      try {
          const res = await fetch('/stockpile/search?q=' + encodeURIComponent(q));
          const data = await res.json();
          if (!data.ok) {
              spSearchRes.innerHTML = '<span style="color:#c62828">' + esc(data.msg) + '</span>';
              return;
          }
          if (!data.records.length) {
              spSearchRes.innerHTML = '<span style="color:#999">无匹配结果</span>';
              return;
          }
          let html = '<b>找到 ' + data.count + ' 条：</b><br>';
          html += data.records.map(r =>
              esc(r.product_barcode) + ' | ' + esc(r.product_model) + ' | ' + esc(r.stockpile_location)
          ).join('<br>');
          spSearchRes.innerHTML = html;
      } catch (e) {
          spSearchRes.innerHTML = '<span style="color:#c62828">网络错误</span>';
      }
  }

  refreshSpStatus();
}
