const KEY = 'pda_outbox';
const MIN_ROWS = 18;            // 预渲染空表格行数：一打开就像 Excel，降低学习成本
let sessionId = null;
let rows = [];                  // 当前会话已显示的行（乐观 UI，flush 后用服务端对账）
let outbox = JSON.parse(localStorage.getItem(KEY) || '[]');
let scanBuf = '';               // 扫描枪逐字符累积缓冲
let scanTimer = null;

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function kindOf(raw) { return /[A-Za-z]/.test((raw || '')[0] || '') ? 'location' : 'barcode'; }
function rowHtml(seq, raw, kind) {
  // raw 是扫描值（不可信）→ 必须转义，避免 XSS
  return `<tr class="${kind === 'location' ? 'loc' : 'bc'}"><td class="num">${seq}</td><td>${esc(raw)}</td></tr>`;
}
function emptyRowHtml(seq) {
  return `<tr class="empty"><td class="num">${seq}</td><td></td></tr>`;
}

async function init() {
  const ops = (await (await fetch('/pda/operators')).json()).operators;
  const sel = document.getElementById('opSelect');
  sel.innerHTML = '<option value="">选择操作员…</option>' +
    ops.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('');
  sel.onchange = startSession;
  // 整页捕获扫描枪输入（capture 阶段）。扫描枪 = 键盘 wedge，逐字符按键 + 末尾 Enter。
  // 不再依赖隐藏输入框焦点——手机浏览器常拒绝给不可见输入自动聚焦，导致扫了没地方落。
  document.addEventListener('keydown', onScanKey, true);
  document.getElementById('undoBtn').onclick = undo;
  document.getElementById('saveBtn').onclick = save;
  document.getElementById('exitBtn').onclick = exitPda;
  paint();                       // 先画出空表格（即便还没选操作员）
  setInterval(flush, 4000);
}

async function startSession() {
  const id = document.getElementById('opSelect').value;
  if (!id) return;
  const r = await (await fetch('/pda/session/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operator_employee_id: id }) })).json();
  if (r.ok === false) { alert(r.msg); return; }
  sessionId = r.session_id; rows = r.rows || []; paint(); updateSave(rows.length);
}

// 扫描枪逐字符喂入：会话开始后才拦截，避免影响选操作员前的下拉等交互。
function onScanKey(e) {
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  if (!sessionId) return;
  if (e.key === 'Enter') {
    e.preventDefault();
    const raw = scanBuf.trim(); scanBuf = '';
    if (raw) enqueue(raw);
    return;
  }
  if (e.key && e.key.length === 1) {
    e.preventDefault();          // 防止字符泄漏进操作员下拉等
    scanBuf += e.key;
    clearTimeout(scanTimer);
    scanTimer = setTimeout(() => { scanBuf = ''; }, 300);  // 零散手动按键超时丢弃
  }
}

function enqueue(raw) {
  rows = rows.concat([{ seq: rows.length + 1, raw, kind: kindOf(raw) }]);  // 乐观显示
  paint(); updateSave(rows.length);
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
      setNet(true); rows = r.rows || []; paint(); updateSave(r.item_count);
    } catch (_) { setNet(false); break; }
  }
  updatePend();
}

async function undo() {
  if (!sessionId) return;
  const r = await (await fetch(`/pda/session/${sessionId}/undo`, { method: 'POST' })).json();
  rows = r.rows || []; paint(); updateSave(r.item_count);
}

async function save() {
  await flush();
  if (outbox.length) { alert('还有未同步的扫描，请等网络恢复'); return; }
  const r = await (await fetch(`/pda/session/${sessionId}/finalize`, { method: 'POST' })).json();
  if (r.ok === false) { alert(r.msg); return; }
  alert(`已提交，共 ${r.item_count} 件`);
  sessionId = null; rows = []; paint();
  document.getElementById('opSelect').value = ''; updateSave(0);
}

function exitPda() {
  if (outbox.length && !confirm(`还有 ${outbox.length} 条扫描未同步，退出会丢失，确定退出？`)) return;
  if (!confirm('退出扫描端并登出？需要管理员重新登录。')) return;
  location.href = '/logout';
}

function paint() {
  const tb = document.getElementById('rows');
  let html = rows.map(r => rowHtml(r.seq, r.raw, r.kind)).join('');
  for (let i = rows.length; i < MIN_ROWS; i++) html += emptyRowHtml(i + 1);
  tb.innerHTML = html;
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
init();
