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
      inp.className = 'sp-edit-input';
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
  let cmpMismatches = [];        // 向后兼容：覆盖按钮的入参（cosmetic 子集）
  let cmpCosmeticAll = [];       // 完整 cosmetic 列表（覆盖按钮用）

  function renderMismatchRow(m, klass) {
      return `<div class="sp-mismatch-row ${klass}" data-barcode="${esc(m.barcode)}">`
          + esc(m.barcode) + ': 型号(' + esc(m.local_model) + '→' + esc(m.export_model) + ')'
          + ' 库位(<span class="sp-loc-val">' + esc(m.local_location) + '</span>→' + esc(m.export_location) + ')'
          + ' <button class="sp-edit-btn" data-barcode="' + esc(m.barcode) + '" data-local="' + esc(m.local_location) + '">编辑</button>'
          + '</div>';
  }

  function renderMismatchSection(title, list, klass, opts) {
      const max = opts.max || 20;
      const shown = list.slice(0, max);
      let html = `<div class="sp-cmp-section sp-cmp-${klass}">`;
      html += `<div class="sp-cmp-section-hd">${title}<span class="sp-cmp-count"> · ${list.length}</span>`;
      if (opts.button) {
          html += ' ' + opts.button;
      }
      html += '</div>';
      html += shown.map(m => renderMismatchRow(m, klass)).join('');
      if (list.length > max) html += `<div class="sp-cmp-more">...等共 ${list.length} 条</div>`;
      html += '</div>';
      return html;
  }

  function renderCompareResult(d) {
      const cosmetic = d.cosmetic_mismatches || [];
      const substantive = d.substantive_mismatches || [];
      cmpCosmeticAll = cosmetic;
      // 覆盖按钮的入参（仅 cosmetic 视为安全可批量覆盖）
      cmpMismatches = cosmetic;

      let html = '<b>比对结果：</b><br>';
      html += '本地记录：' + d.total_local + ' &nbsp; 导出记录：' + d.total_export + ' &nbsp; 一致：' + d.consistent + '<br>';
      if (d.only_in_local.length) html += '<span class="text-only-local">仅本地有：' + esc(d.only_in_local.join(', ')) + '</span><br>';
      if (d.only_in_export.length) html += '<span class="text-only-export">仅导出有：' + esc(d.only_in_export.join(', ')) + '</span><br>';

      if (substantive.length === 0 && cosmetic.length === 0 && !d.only_in_local.length && !d.only_in_export.length) {
          html += '<b class="text-success-bright">完全一致</b>';
          return html;
      }

      if (substantive.length > 0) {
          if (d.alert) {
              html += `<div class="sp-cmp-alert">⚠️ 实质不一致 ${substantive.length} 条 (≥${3}) — 必须人工核查每一条，可能是真实库位变化、也可能是 bug</div>`;
          }
          html += renderMismatchSection(
              '实质不一致（normalize 后仍不同 / 型号变更）',
              substantive,
              'substantive',
              { max: 50 }
          );
      }

      if (cosmetic.length > 0) {
          const overwriteBtn = '<button class="sp-edit-btn" id="spOverwriteBtn">一键覆盖 cosmetic 全部</button>';
          html += renderMismatchSection(
              '空白/格式差异（normalize 后相同，老系统正在清理时常见）',
              cosmetic,
              'cosmetic',
              { max: 20, button: overwriteBtn }
          );
      }
      return html;
  }

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
              spInitMsg.classList.remove('is-error'); spInitMsg.classList.add('is-success');
              refreshSpStatus();
          } else {
              spInitMsg.textContent = '导入失败：' + data.msg;
              spInitMsg.classList.remove('is-success'); spInitMsg.classList.add('is-error');
          }
      } catch (e) {
          spInitMsg.textContent = '网络错误';
          spInitMsg.classList.remove('is-success'); spInitMsg.classList.add('is-error');
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
              spCmpRes.innerHTML = renderCompareResult(data.diff);
          } else {
              spCmpRes.innerHTML = '<span class="text-danger-bright">比对失败：' + esc(data.msg || '') + '</span>';
          }
      } catch (e) {
          spCmpRes.innerHTML = '<span class="text-danger-bright">网络错误</span>';
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
              spStatus.classList.remove('is-error', 'text-muted-faint'); spStatus.classList.add('is-success');
          } else {
              spStatus.textContent = '状态：未初始化，请先上传系统导出文件';
              spStatus.classList.remove('is-success', 'text-muted-faint'); spStatus.classList.add('is-error');
          }
      } catch (e) {
          spStatus.textContent = '状态：检查失败';
          spStatus.classList.remove('is-success', 'is-error'); spStatus.classList.add('text-muted-faint');
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
      spSearchRes.innerHTML = '<span class="text-muted-faint">搜索中...</span>';
      try {
          const res = await fetch('/stockpile/search?q=' + encodeURIComponent(q));
          const data = await res.json();
          if (!data.ok) {
              spSearchRes.innerHTML = '<span class="text-danger-bright">' + esc(data.msg) + '</span>';
              return;
          }
          if (!data.records.length) {
              spSearchRes.innerHTML = '<span class="text-muted-faint">无匹配结果</span>';
              return;
          }
          let html = '<b>找到 ' + data.count + ' 条：</b><br>';
          html += data.records.map(r =>
              esc(r.product_barcode) + ' | ' + esc(r.product_model) + ' | ' + esc(r.stockpile_location)
          ).join('<br>');
          spSearchRes.innerHTML = html;
      } catch (e) {
          spSearchRes.innerHTML = '<span class="text-danger-bright">网络错误</span>';
      }
  }

  refreshSpStatus();
}
