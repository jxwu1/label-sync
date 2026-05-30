const KEY = 'pda_outbox';
const MIN_ROWS = 18;            // 预渲染空表格行数：一打开就像 Excel，降低学习成本
let sessionId = null;
let rows = [];                  // 当前会话已显示的行（乐观 UI，flush 后用服务端对账）
let outbox = JSON.parse(localStorage.getItem(KEY) || '[]');

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
  // 扫描枪 = 键盘 wedge：把字符注入「当前聚焦的可编辑输入框」+ 末尾 Enter。
  // 所以必须有一个可见、可聚焦、带光标的输入框接住扫码（手机不给隐藏框聚焦/注入）。
  document.getElementById('scanInput').addEventListener('keydown', onScanKey);
  // 点表格任意处 → 聚焦扫描框（像点 Excel 格子那样唤出光标），保证扫描枪有处可落。
  document.getElementById('grid').addEventListener('click', focusScan);
  document.getElementById('undoBtn').onclick = undo;
  document.getElementById('saveBtn').onclick = save;
  document.getElementById('exitBtn').onclick = exitPda;
  paint();
  setInterval(flush, 4000);
}

function focusScan() {
  const el = document.getElementById('scanInput');
  if (el && sessionId) el.focus();
}

async function startSession() {
  const id = document.getElementById('opSelect').value;
  if (!id) return;
  const r = await (await fetch('/pda/session/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operator_employee_id: id }) })).json();
  if (r.ok === false) { alert(r.msg); return; }
  sessionId = r.session_id; rows = r.rows || []; paint(); updateSave(rows.length);
  focusScan();
}

function onScanKey(e) {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const raw = e.target.value.trim(); e.target.value = '';
  if (raw && sessionId) enqueue(raw);
  focusScan();                   // 扫完保持聚焦，连续扫不用每次再点
}

function enqueue(raw) {
  rows = rows.concat([{ seq: rows.length + 1, raw, kind: kindOf(raw) }]);  // 乐观显示
  paint(); updateSave(rows.length);
  outbox.push(raw); localStorage.setItem(KEY, JSON.stringify(outbox));
  flush();
}

let flushing = false;
async function flush() {
  // 防重入：扫描调用 + 4s 定时器若并发，会把 outbox[0] 重复 POST，服务端 item_count
  // 并发自增 → 序号重复（1,2,3,4,5,5,7）。同一时刻只允许一个 flush 循环。
  if (!sessionId || flushing) return;
  flushing = true;
  try {
    while (outbox.length) {
      const raw = outbox[0];
      const r = await (await fetch(`/pda/session/${sessionId}/scan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw }) })).json();
      outbox.shift(); localStorage.setItem(KEY, JSON.stringify(outbox));
      setNet(true);
      if (typeof r.item_count === 'number') updateSave(r.item_count);
      // 只在排空（服务端已追平所有乐观行）时用服务端 rows 对账一次。
      // 中途对账会把尚未同步的乐观行抹掉再冒出来（快速扫描"突然消失又跳出来"）。
      if (outbox.length === 0 && r.rows) { rows = r.rows; paint(); }
    }
  } catch (_) {
    setNet(false);
  } finally {
    flushing = false;
    updatePend();
  }
}

async function undo() {
  if (!sessionId) return;
  const r = await (await fetch(`/pda/session/${sessionId}/undo`, { method: 'POST' })).json();
  rows = r.rows || []; paint(); updateSave(r.item_count); focusScan();
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

let _sig = '';
function paint() {
  const sig = rows.length + '#' + rows.map(r => r.seq + ':' + r.raw).join('|');
  if (sig === _sig) return;            // 内容没变不重绘：消除每次扫描整表重画两遍的闪烁
  _sig = sig;
  const tb = document.getElementById('rows');
  let html = rows.map(r => rowHtml(r.seq, r.raw, r.kind)).join('');
  for (let i = rows.length; i < MIN_ROWS; i++) html += emptyRowHtml(i + 1);
  tb.innerHTML = html;
  // 只把最后一条真实行带进视野（block:nearest）——不要滚到空占位行底部，
  // 否则扫第 1 行视图就跳到第 18 行附近（用户反馈的"滑到下面去"）。
  const real = tb.querySelectorAll('tr.loc, tr.bc');
  if (real.length) real[real.length - 1].scrollIntoView({ block: 'nearest' });
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
