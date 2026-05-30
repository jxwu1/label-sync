function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function load() {
  const el = document.getElementById('pdaPendingList');
  if (!el) return;
  el.innerHTML = '<div style="color:#888">加载中…</div>';
  let data;
  try {
    const res = await fetch('/pda/pending');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    data = (await res.json()).pending || [];
  } catch (e) {
    // 不再静默卡在"加载中"：给出可点重试（旧 bug：首次失败 → 永远加载中）
    el.innerHTML =
      '<div style="color:#c0392b">加载失败，<a href="#" onclick="reloadPending();return false">点此重试</a></div>';
    return;
  }
  if (!data.length) { el.innerHTML = '<div style="color:#888">暂无待处理批次</div>'; return; }
  el.innerHTML = data.map(b => `
    <div class="pda-pend-row" style="display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--bg-2)">
      <b>${esc(b.operator_name)}</b><span>${b.item_count} 件</span>
      <span style="color:#888">${esc(b.finalized_at || '')}</span>
      <span style="flex:1"></span>
      <button class="btn-s" onclick="proc(${b.id})">处理</button>
      <button class="btn-s is-warn" onclick="discard(${b.id})">作废</button>
    </div>`).join('');
}

async function proc(id) {
  const r = await (await fetch(`/pda/pending/${id}/process`, { method: 'POST' })).json();
  if (r.ok === false) { alert(r.msg); return; }
  Alpine.store('nav').switch('main');                          // 跳标签处理页
  if (window.pickupExternalTask) window.pickupExternalTask();  // 让主页接管刚启动的任务并轮询进度
}
async function discard(id) {
  await fetch(`/pda/pending/${id}/discard`, { method: 'POST' });
  load();
}

// 每次「PDA 待处理」页变为可见就重新拉队列（PDA 端随时会保存新批次）。
// 监听页面 active class（Alpine 按 nav.current 切换）——不用 nav 的一次性 onFirstActivate，
// 那个首次失败就永远卡住、且切走再回不刷新。
function watchActivate() {
  const page = document.getElementById('pagePdaPending');
  if (!page) return;
  let wasActive = page.classList.contains('active');
  if (wasActive) load();
  new MutationObserver(() => {
    const active = page.classList.contains('active');
    if (active && !wasActive) load();
    wasActive = active;
  }).observe(page, { attributes: true, attributeFilter: ['class'] });
}
watchActivate();

window.proc = proc; window.discard = discard; window.reloadPending = load;
