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
          <button class="attn-btn attn-btn-dl" id="attnPdf">下载 PDF</button>
          <button class="attn-btn attn-btn-dl" id="attnCsv">下载 CSV</button>
        </div>
        <div class="attn-stats">
          <span>累计 <b id="attnWorked">0</b> 天</span>
          <span>缺勤 <b id="attnAbsent">0</b> 天</span>
          <span>总工作日 <b id="attnTotal">0</b></span>
        </div>
        <div id="attnGridWrap"></div>
      </div>`;

    document.getElementById('attnEmpNew').addEventListener('click', createEmployee);
    document.getElementById('attnEmpDel').addEventListener('click', deleteEmployee);
    document.getElementById('attnEmployee').addEventListener('change', onEmployeeChange);
    document.getElementById('attnMonth').addEventListener('change', onMonthChange);
    document.getElementById('attnPdf').addEventListener('click', downloadPdf);
    document.getElementById('attnCsv').addEventListener('click', downloadCsv);

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
      const cls = r.status === 'sunday' ? 'sunday' : (r.status === 'absent' ? 'absent' : '');
      const startCell = r.status === 'sunday'
        ? '<td colspan="2">自动（周日）</td>'
        : `<td><input type="time" data-date="${r.date}" data-field="start" value="${r.start}"></td>
           <td><input type="time" data-date="${r.date}" data-field="end" value="${r.end}"></td>`;
      const statusText = r.status === 'sunday' ? '🔒' : (r.status === 'absent' ? '缺勤' : '✓');
      const actionCell = r.status === 'sunday'
        ? '<td></td>'
        : `<td><button class="attn-btn attn-fill" data-date="${r.date}">正常</button></td>`;
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
    wrap.querySelectorAll('input[type=time]').forEach(inp => {
      inp.addEventListener('change', () => onCellChange(inp.dataset.date));
    });
    wrap.querySelectorAll('.attn-fill').forEach(btn => {
      btn.addEventListener('click', () => fillNormal(btn.dataset.date));
    });
  }

  async function fillNormal(date) {
    const row = document.querySelector(`tr[data-date="${date}"]`);
    if (!row) return;
    const startInp = row.querySelector('input[data-field="start"]');
    const endInp = row.querySelector('input[data-field="end"]');
    if (startInp) startInp.value = '09:30';
    if (endInp) endInp.value = '20:00';
    await onCellChange(date);
  }

  async function onCellChange(date) {
    const row = document.querySelector(`tr[data-date="${date}"]`);
    if (!row) return;
    const startInp = row.querySelector('input[data-field="start"]');
    const endInp = row.querySelector('input[data-field="end"]');
    const start = startInp ? startInp.value : '';
    const end = endInp ? endInp.value : '';
    if (!start && !end) {
      await fetch(`/attendance/day/${currentEmployeeId}/${date}`, { method: 'DELETE' });
    } else if (start && end) {
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
