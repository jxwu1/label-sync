const KEY = 'pda_outbox';
let sessionId = null;
let outbox = JSON.parse(localStorage.getItem(KEY) || '[]');

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function rowHtml(seq, raw, kind) {
  // raw 是扫描值（不可信）→ 必须转义，避免 XSS
  return `<tr class="${kind === 'location' ? 'loc' : 'bc'}"><td class="num">${seq}</td><td>${esc(raw)}</td></tr>`;
}

async function init() {
  const ops = (await (await fetch('/pda/operators')).json()).operators;
  const sel = document.getElementById('opSelect');
  sel.innerHTML = '<option value="">选择操作员…</option>' +
    ops.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('');
  sel.onchange = startSession;
  document.getElementById('scanInput').addEventListener('keydown', onScanKey);
  document.getElementById('undoBtn').onclick = undo;
  document.getElementById('saveBtn').onclick = save;
  document.getElementById('exitBtn').onclick = exitPda;
  setInterval(flush, 4000);
}
async function startSession() {
  const id = document.getElementById('opSelect').value;
  if (!id) return;
  const r = await (await fetch('/pda/session/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operator_employee_id: id }) })).json();
  if (r.ok === false) { alert(r.msg); return; }
  sessionId = r.session_id; render(r.rows); updateSave(r.item_count); refocus();
}
function onScanKey(e) {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const raw = e.target.value.trim(); e.target.value = '';
  if (raw && sessionId) enqueue(raw);
  refocus();
}
function enqueue(raw) {
  appendRowUI(raw);
  outbox.push(raw); localStorage.setItem(KEY, JSON.stringify(outbox));
  flush();
}
async function flush() {
  if (!sessionId) return;
  while (outbox.length) {
    const raw = outbox[0];
    try {
      const r = await (await fetch(`/pda/session/${sessionId}/scan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw }) })).json();
      outbox.shift(); localStorage.setItem(KEY, JSON.stringify(outbox));
      setNet(true); render(r.rows); updateSave(r.item_count);
    } catch (_) { setNet(false); break; }
  }
  updatePend();
}
async function undo() {
  if (!sessionId) return;
  const r = await (await fetch(`/pda/session/${sessionId}/undo`, { method: 'POST' })).json();
  render(r.rows); updateSave(r.item_count); refocus();
}
async function save() {
  await flush();
  if (outbox.length) { alert('还有未同步的扫描，请等网络恢复'); return; }
  const r = await (await fetch(`/pda/session/${sessionId}/finalize`, { method: 'POST' })).json();
  if (r.ok === false) { alert(r.msg); return; }
  alert(`已提交，共 ${r.item_count} 件`);
  sessionId = null; document.getElementById('rows').innerHTML = '';
  document.getElementById('opSelect').value = ''; updateSave(0);
}
function exitPda() {
  if (outbox.length && !confirm(`还有 ${outbox.length} 条扫描未同步，退出会丢失，确定退出？`)) return;
  if (!confirm('退出扫描端并登出？需要管理员重新登录。')) return;
  location.href = '/logout';
}
function appendRowUI(raw) {
  const tb = document.getElementById('rows');
  const kind = /[A-Za-z]/.test((raw || '')[0] || '') ? 'location' : 'barcode';
  tb.insertAdjacentHTML('beforeend', rowHtml(tb.children.length + 1, raw, kind));
  document.getElementById('grid').scrollTop = 1e9;
}
function render(rows) {
  const tb = document.getElementById('rows'); tb.innerHTML = '';
  (rows || []).forEach(r => tb.insertAdjacentHTML('beforeend', rowHtml(r.seq, r.raw, r.kind)));
  document.getElementById('grid').scrollTop = 1e9;
}
function updateSave(n) { document.getElementById('saveBtn').disabled = !(sessionId && n > 0); }
function setNet(on) {
  const d = document.getElementById('netDot');
  d.classList.toggle('pda-dot--on', on); d.classList.toggle('pda-dot--off', !on);
}
function updatePend() {
  const b = document.getElementById('pendBadge');
  if (outbox.length) { b.hidden = false; b.textContent = `待同步 ${outbox.length}`; }
  else b.hidden = true;
}
function refocus() { setTimeout(() => document.getElementById('scanInput').focus(), 0); }
init();
