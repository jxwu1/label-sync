(function () {
  let employees = [];
  let currentEmployeeId = '';
  let currentMonth = '';
  let currentSummary = null;

  function init() {
    const page = document.getElementById('pageAttendance');
    if (!page) return;
    page.innerHTML = `
      <div class="attn-wrap">
        <div class="attn-top">
          <label>月份 <input class="attn-inp" id="attnMonth" type="month"></label>
          <label>员工 <select class="attn-inp" id="attnEmployee"></select></label>
          <button class="attn-btn" id="attnEmpNew">+ 新建</button>
          <button class="attn-btn attn-btn-danger" id="attnEmpDel">删除员工</button>
          <button class="attn-btn" id="attnHolidays">节假日</button>
          <button class="attn-btn" id="attnSpecial">特殊日</button>
          <button class="attn-btn attn-btn-dl" id="attnPdf">下载 PDF</button>
          <button class="attn-btn attn-btn-dl" id="attnCsv">下载 CSV</button>
        </div>
        <div class="attn-stats">
          <span>累计 <b id="attnWorked">0</b> 天</span>
          <span>缺勤 <b id="attnAbsent">0</b> 天</span>
          <span>总工作日 <b id="attnTotal">0</b></span>
          <span>本月天数 <b id="attnMonthDays">0</b></span>
        </div>
        <div id="attnGridWrap"></div>
      </div>
      <div class="pur-modal-overlay" id="attnSpecialOverlay" style="display:none;">
        <div class="pur-modal">
          <div class="pur-modal-hd">特殊日管理（缩短工时）</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <input class="attn-inp" id="attnSpecialDate" type="date">
            <input class="attn-inp" id="attnSpecialStart" type="text" placeholder="09:30" maxlength="5">
            <span>—</span>
            <input class="attn-inp" id="attnSpecialEnd" type="text" placeholder="14:30" maxlength="5">
            <button class="attn-btn attn-btn-dl" id="attnSpecialAdd">添加</button>
          </div>
          <div id="attnSpecialList" class="pur-mgr-list"></div>
          <div class="pur-modal-actions">
            <button class="attn-btn" id="attnSpecialClose">关闭</button>
          </div>
        </div>
      </div>
      <div class="pur-modal-overlay" id="attnHolidayOverlay" style="display:none;">
        <div class="pur-modal">
          <div class="pur-modal-hd">节假日管理</div>
          <div style="display:flex;gap:8px;align-items:center;">
            <input class="attn-inp" id="attnHolidayInput" type="date">
            <button class="attn-btn attn-btn-dl" id="attnHolidayAdd">添加</button>
          </div>
          <div id="attnHolidayList" class="pur-mgr-list"></div>
          <div class="pur-modal-actions">
            <button class="attn-btn" id="attnHolidayClose">关闭</button>
          </div>
        </div>
      </div>`;

    document.getElementById('attnEmpNew').addEventListener('click', createEmployee);
    document.getElementById('attnEmpDel').addEventListener('click', deleteEmployee);
    document.getElementById('attnEmployee').addEventListener('change', onEmployeeChange);
    document.getElementById('attnMonth').addEventListener('change', onMonthChange);
    document.getElementById('attnPdf').addEventListener('click', downloadPdf);
    document.getElementById('attnCsv').addEventListener('click', downloadCsv);
    document.getElementById('attnHolidays').addEventListener('click', openHolidays);
    document.getElementById('attnHolidayAdd').addEventListener('click', addHoliday);
    document.getElementById('attnHolidayClose').addEventListener('click', () => {
      document.getElementById('attnHolidayOverlay').style.display = 'none';
    });
    document.getElementById('attnSpecial').addEventListener('click', openSpecial);
    document.getElementById('attnSpecialAdd').addEventListener('click', addSpecial);
    document.getElementById('attnSpecialClose').addEventListener('click', () => {
      document.getElementById('attnSpecialOverlay').style.display = 'none';
    });

    document.getElementById('attnMonth').value = new Date().toISOString().slice(0, 7);
    currentMonth = document.getElementById('attnMonth').value;
    loadEmployees();
  }

  async function loadEmployees() {
    try {
      const res = await fetch('/attendance/employees');
      const body = await res.json();
      employees = body.employees || [];
    } catch (e) {
      employees = [];
    }
    renderEmployeeSelect();
    if (employees.length && !currentEmployeeId) {
      currentEmployeeId = employees[0].id;
      document.getElementById('attnEmployee').value = currentEmployeeId;
    }
    loadMonth();
  }

  function renderEmployeeSelect() {
    const sel = document.getElementById('attnEmployee');
    sel.innerHTML = employees.map(e => `<option value="${e.id}">${escapeHtml(e.name)}</option>`).join('');
    if (currentEmployeeId) sel.value = currentEmployeeId;
  }

  async function createEmployee() {
    const name = prompt('新员工姓名：');
    if (!name || !name.trim()) return;
    try {
      const res = await fetch('/attendance/employees', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      currentEmployeeId = body.employee.id;
      await loadEmployees();
    } catch (e) { alert('新建失败：' + e.message); }
  }

  async function deleteEmployee() {
    if (!currentEmployeeId) return;
    const emp = employees.find(e => e.id === currentEmployeeId);
    if (!emp) return;
    if (!confirm(`删除员工 ${emp.name}？历史考勤数据保留但不再显示。`)) return;
    try {
      const res = await fetch(`/attendance/employees/${currentEmployeeId}`, { method: 'DELETE' });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      currentEmployeeId = '';
      await loadEmployees();
    } catch (e) { alert('删除失败：' + e.message); }
  }

  function onEmployeeChange(e) {
    currentEmployeeId = e.target.value;
    loadMonth();
  }

  function onMonthChange(e) {
    currentMonth = e.target.value;
    loadMonth();
  }

  async function loadMonth() {
    const wrap = document.getElementById('attnGridWrap');
    if (!currentEmployeeId || !currentMonth) {
      wrap.innerHTML = '<div style="color:#64748b;padding:20px;">请先选择员工和月份</div>';
      updateStats(null);
      return;
    }
    try {
      const res = await fetch(`/attendance/month/${currentEmployeeId}/${currentMonth}`);
      const body = await res.json();
      if (!body.ok) { wrap.innerHTML = `<div style="color:#fca5a5;">${body.msg}</div>`; return; }
      currentSummary = body;
      renderGrid(body.detail);
      updateStats(body);
    } catch (e) { wrap.innerHTML = `<div style="color:#fca5a5;">加载失败：${e.message}</div>`; }
  }

  function renderGrid(detail) {
    const wrap = document.getElementById('attnGridWrap');
    const rows = detail.map(r => {
      const autoRow = r.status === 'sunday' || r.status === 'holiday';
      const isSpecial = r.status === 'special' || r.status === 'special_absent';
      const clsMap = { sunday: 'sunday', holiday: 'holiday', absent: 'absent', special: 'special', special_absent: 'special absent' };
      const cls = clsMap[r.status] || '';
      const autoLabel = r.status === 'sunday' ? '自动（周日）' : '自动（节假日）';
      const specialHint = isSpecial ? `<span class="attn-hint">缩短 ${r.special_start}-${r.special_end}</span>` : '';
      const startCell = autoRow
        ? `<td colspan="2">${autoLabel}</td>`
        : `<td><input type="text" inputmode="numeric" maxlength="5" placeholder="HH:MM" data-date="${r.date}" data-field="start" value="${r.start}">${specialHint ? '<br>'+specialHint : ''}</td>
           <td><input type="text" inputmode="numeric" maxlength="5" placeholder="HH:MM" data-date="${r.date}" data-field="end" value="${r.end}"></td>`;
      const statusMap = { sunday: '周日', holiday: '节假日', absent: '缺勤', normal: '正常', special: '特殊日', special_absent: '特殊日缺勤' };
      const statusText = statusMap[r.status] || r.status;
      const fillBtn = isSpecial
        ? `<td><button class="attn-btn attn-fill" data-date="${r.date}" data-start="${r.special_start}" data-end="${r.special_end}">按标准</button></td>`
        : (autoRow ? '<td></td>' : `<td><button class="attn-btn attn-fill" data-date="${r.date}" data-start="09:30" data-end="20:00">正常</button></td>`);
      const actionCell = fillBtn;
      return `<tr class="${cls}" data-date="${r.date}">
        <td>${r.date.slice(5)}</td>
        <td>${r.weekday}</td>
        ${startCell}
        <td>${r.day_fraction.toFixed(2)}</td>
        <td class="attn-status">${statusText}</td>
        ${actionCell}
      </tr>`;
    }).join('');
    wrap.innerHTML = `
      <table class="attn-grid">
        <thead><tr><th>日期</th><th>星期</th><th>上班</th><th>下班</th><th>天数</th><th>状态</th><th>快填</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    wrap.querySelectorAll('input[data-field]').forEach(inp => {
      inp.addEventListener('change', () => onCellChange(inp.dataset.date));
    });
    wrap.querySelectorAll('.attn-fill').forEach(btn => {
      btn.addEventListener('click', () => fillNormal(btn.dataset.date, btn.dataset.start, btn.dataset.end));
    });
  }

  async function fillNormal(date, start, end) {
    const row = document.querySelector(`tr[data-date="${date}"]`);
    if (!row) return;
    const startInp = row.querySelector('input[data-field="start"]');
    const endInp = row.querySelector('input[data-field="end"]');
    if (startInp) startInp.value = start || '09:30';
    if (endInp) endInp.value = end || '20:00';
    await onCellChange(date);
  }

  function normalizeTime(raw) {
    const s = String(raw || '').trim();
    if (!s) return '';
    const digits = s.replace(/\D/g, '');
    if (digits.length === 3) return `0${digits[0]}:${digits.slice(1)}`;
    if (digits.length === 4) return `${digits.slice(0, 2)}:${digits.slice(2)}`;
    return s;
  }

  async function onCellChange(date) {
    const row = document.querySelector(`tr[data-date="${date}"]`);
    if (!row) return;
    const startInp = row.querySelector('input[data-field="start"]');
    const endInp = row.querySelector('input[data-field="end"]');
    if (startInp) startInp.value = normalizeTime(startInp.value);
    if (endInp) endInp.value = normalizeTime(endInp.value);
    const start = startInp ? startInp.value : '';
    const end = endInp ? endInp.value : '';
    const timeRe = /^([01]\d|2[0-3]):([0-5]\d)$/;
    if (!start && !end) {
      await fetch(`/attendance/day/${currentEmployeeId}/${date}`, { method: 'DELETE' });
    } else if (start && end) {
      if (!timeRe.test(start) || !timeRe.test(end)) {
        alert('时间格式错误，请按 HH:MM 填写（如 09:30）');
        return;
      }
      const res = await fetch(`/attendance/day/${currentEmployeeId}/${date}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start, end }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } else {
      return;
    }
    await loadMonth();
  }

  function updateStats(summary) {
    document.getElementById('attnWorked').textContent = summary ? summary.worked_days : 0;
    document.getElementById('attnAbsent').textContent = summary ? summary.absent_days : 0;
    document.getElementById('attnTotal').textContent = summary ? summary.total_workdays : 0;
    document.getElementById('attnMonthDays').textContent = summary ? summary.month_days : 0;
  }

  async function openHolidays() {
    document.getElementById('attnHolidayInput').value = '';
    await renderHolidayList();
    document.getElementById('attnHolidayOverlay').style.display = 'flex';
  }

  async function renderHolidayList() {
    try {
      const res = await fetch('/attendance/holidays');
      const body = await res.json();
      const list = document.getElementById('attnHolidayList');
      const holidays = body.holidays || [];
      if (!holidays.length) {
        list.innerHTML = '<div class="empty">暂无节假日</div>';
        return;
      }
      list.innerHTML = holidays.map(d => `
        <div class="pur-mgr-row">
          <div class="pur-mgr-cell">${escapeHtml(d)}</div>
          <button class="pur-btn-copy pur-mgr-del" data-date="${d}">删除</button>
        </div>`).join('');
      list.querySelectorAll('.pur-mgr-del').forEach(btn => {
        btn.addEventListener('click', () => deleteHoliday(btn.dataset.date));
      });
    } catch (e) { alert('加载节假日失败：' + e.message); }
  }

  async function addHoliday() {
    const date = document.getElementById('attnHolidayInput').value;
    if (!date) { alert('请选择日期'); return; }
    try {
      const res = await fetch('/attendance/holidays', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } catch (e) { alert('添加失败：' + e.message); return; }
    document.getElementById('attnHolidayInput').value = '';
    await renderHolidayList();
    await loadMonth();
  }

  async function deleteHoliday(date) {
    if (!confirm(`删除节假日 ${date}？`)) return;
    try {
      const res = await fetch(`/attendance/holidays/${date}`, { method: 'DELETE' });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } catch (e) { alert('删除失败：' + e.message); return; }
    await renderHolidayList();
    await loadMonth();
  }

  async function openSpecial() {
    document.getElementById('attnSpecialDate').value = '';
    document.getElementById('attnSpecialStart').value = '';
    document.getElementById('attnSpecialEnd').value = '';
    await renderSpecialList();
    document.getElementById('attnSpecialOverlay').style.display = 'flex';
  }

  async function renderSpecialList() {
    try {
      const res = await fetch('/attendance/special-days');
      const body = await res.json();
      const list = document.getElementById('attnSpecialList');
      const sd = body.special_days || {};
      const entries = Object.entries(sd).sort(([a], [b]) => a.localeCompare(b));
      if (!entries.length) {
        list.innerHTML = '<div class="empty">暂无特殊日</div>';
        return;
      }
      list.innerHTML = entries.map(([date, range]) => `
        <div class="pur-mgr-row">
          <div class="pur-mgr-cell">${escapeHtml(date)}</div>
          <div class="pur-mgr-cell">${escapeHtml(range.start)} — ${escapeHtml(range.end)}</div>
          <button class="pur-btn-copy pur-mgr-del" data-date="${date}">删除</button>
        </div>`).join('');
      list.querySelectorAll('.pur-mgr-del').forEach(btn => {
        btn.addEventListener('click', () => deleteSpecial(btn.dataset.date));
      });
    } catch (e) { alert('加载特殊日失败：' + e.message); }
  }

  async function addSpecial() {
    const date = document.getElementById('attnSpecialDate').value;
    const start = normalizeTime(document.getElementById('attnSpecialStart').value);
    const end = normalizeTime(document.getElementById('attnSpecialEnd').value);
    const timeRe = /^([01]\d|2[0-3]):([0-5]\d)$/;
    if (!date) { alert('请选择日期'); return; }
    if (!timeRe.test(start) || !timeRe.test(end)) { alert('时间格式错误（HH:MM）'); return; }
    try {
      const res = await fetch('/attendance/special-days', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date, start, end }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } catch (e) { alert('添加失败：' + e.message); return; }
    await renderSpecialList();
    await loadMonth();
  }

  async function deleteSpecial(date) {
    if (!confirm(`删除特殊日 ${date}？`)) return;
    try {
      const res = await fetch(`/attendance/special-days/${date}`, { method: 'DELETE' });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } catch (e) { alert('删除失败：' + e.message); return; }
    await renderSpecialList();
    await loadMonth();
  }

  function downloadPdf() {
    if (!currentMonth) return;
    window.location.href = `/attendance/pdf/${currentMonth}`;
  }

  function downloadCsv() {
    if (!currentMonth) return;
    window.location.href = `/attendance/csv/${currentMonth}`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
    const orig = window.switchPage;
    window.switchPage = function (pg) {
      if (typeof orig === 'function') orig(pg);
      if (pg === 'attendance') {
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.getElementById('navAttendance')?.classList.add('active');
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        document.getElementById('pageAttendance')?.classList.add('active');
      }
    };
  });
})();
