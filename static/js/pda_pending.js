function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
document.addEventListener('alpine:init', () => {
  Alpine.store('nav').onFirstActivate('pda_pending', load);
});
async function load() {
  const data = (await (await fetch('/pda/pending')).json()).pending || [];
  const el = document.getElementById('pdaPendingList');
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
  Alpine.store('nav').switch('main');  // 跳标签处理页看进度
}
async function discard(id) {
  await fetch(`/pda/pending/${id}/discard`, { method: 'POST' });
  load();
}
window.proc = proc; window.discard = discard;
