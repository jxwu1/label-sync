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
          <span class="attn-spacer"></span>
          <button class="attn-btn" id="attnFillAll">一键填全月正常</button>
          <button class="attn-btn attn-btn-dl" id="attnPdf">下载 PDF</button>
          <button class="attn-btn attn-btn-dl" id="attnPayrollPdf">下载工资单 PDF</button>
        </div>
        <div class="attn-stats">
          <div class="attn-stat"><div class="attn-stat-k">累计</div><div class="attn-stat-v"><span id="attnWorked">0</span> <small>天</small></div></div>
          <div class="attn-stat"><div class="attn-stat-k">缺勤</div><div class="attn-stat-v"><span id="attnAbsent">0</span> <small>天</small></div></div>
          <div class="attn-stat"><div class="attn-stat-k">总工作日</div><div class="attn-stat-v" id="attnTotal">0</div></div>
          <div class="attn-stat"><div class="attn-stat-k">本月天数</div><div class="attn-stat-v" id="attnMonthDays">0</div></div>
          <div class="attn-stat"><div class="attn-stat-k">请假</div><div class="attn-stat-v"><span id="attnLeaveH">0</span> <small>h ≈ <span id="attnLeaveD">0</span> 天</small></div></div>
        </div>
        <div id="attnGridWrap"></div>
      </div>
      <div class="pur-modal-overlay attn-hidden" id="attnSpecialOverlay">
        <div class="pur-modal">
          <div class="pur-modal-hd">特殊日管理（缩短工时）</div>
          <div class="attn-time-row">
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
      <div class="pur-modal-overlay attn-hidden" id="attnLeaveOverlay">
        <div class="pur-modal">
          <div class="pur-modal-hd">请假 <span id="attnLeaveDate"></span></div>
          <div class="attn-stack">
            <label><input type="radio" name="attnLeaveType" value="full" checked> 全天</label>
            <label><input type="radio" name="attnLeaveType" value="range"> 离开后回来：
              <input class="attn-inp attn-narrow" id="attnLeaveStart" type="text" placeholder="HH:MM" maxlength="5"> —
              <input class="attn-inp attn-narrow" id="attnLeaveEnd" type="text" placeholder="HH:MM" maxlength="5">
            </label>
            <label><input type="radio" name="attnLeaveType" value="left"> 离开未回来：
              <input class="attn-inp attn-narrow" id="attnLeaveLeftStart" type="text" placeholder="HH:MM" maxlength="5">
            </label>
          </div>
          <div class="pur-modal-actions">
            <button class="attn-btn attn-btn-dl" id="attnLeaveSubmit">确认</button>
            <button class="attn-btn" id="attnLeaveCancel">取消</button>
          </div>
        </div>
      </div>
      <div class="pur-modal-overlay attn-hidden" id="attnHolidayOverlay">
        <div class="pur-modal">
          <div class="pur-modal-hd">节假日管理</div>
          <div class="attn-time-row">
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
    document.getElementById('attnPayrollPdf').addEventListener('click', downloadPayrollPdf);
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
    document.getElementById('attnLeaveSubmit').addEventListener('click', submitLeave);
    document.getElementById('attnLeaveCancel').addEventListener('click', () => {
      document.getElementById('attnLeaveOverlay').style.display = 'none';
    });
    document.getElementById('attnFillAll').addEventListener('click', fillAllNormal);

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
      wrap.innerHTML = '<div class="attn-empty-msg">请先选择员工和月份</div>';
      updateStats(null);
      return;
    }
    try {
      const res = await fetch(`/attendance/month/${currentEmployeeId}/${currentMonth}`);
      const body = await res.json();
      if (!body.ok) { wrap.innerHTML = `<div class="attn-error-msg">${body.msg}</div>`; return; }
      currentSummary = body;
      renderGrid(body.detail);
      updateStats(body);
    } catch (e) { wrap.innerHTML = `<div class="attn-error-msg">加载失败：${e.message}</div>`; }
  }

  function renderGrid(detail) {
    const wrap = document.getElementById('attnGridWrap');
    wrap.classList.add('attn-grid-wrap');
    const statusMap = { sunday: '周日', holiday: '节假日', absent: '缺勤', normal: '正常', special: '特殊日', special_absent: '特殊日缺勤', leave: '请假' };
    const statusClsMap = { sunday: 'attn-st-sunday', holiday: 'attn-st-holiday', absent: 'attn-st-absent', normal: 'attn-st-normal', special: 'attn-st-special', special_absent: 'attn-st-special', leave: 'attn-st-leave' };

    const rows = detail.map(r => {
      const autoRow = r.status === 'sunday' || r.status === 'holiday';
      const isSpecial = r.status === 'special' || r.status === 'special_absent';
      const isLeave = r.status === 'leave';
      const isAbsent = r.status === 'absent' || r.status === 'special_absent';
      const isEmpty = !autoRow && !r.start && !r.end && !isLeave;

      const rowCls = [
        isAbsent ? 'absent' : '',
        isLeave ? 'attn-has-leave' : '',
      ].filter(Boolean).join(' ');

      // 时段单元
      let timeCell;
      if (autoRow) {
        const label = r.status === 'sunday' ? '自动（周日）' : '自动（节假日）';
        timeCell = `<td><span class="attn-time-auto">${label}</span></td>`;
      } else {
        const placeholderStart = isSpecial ? r.special_start : '09:30';
        const placeholderEnd = isSpecial ? r.special_end : '20:00';
        const hint = isSpecial ? `<span class="attn-time-hint">特殊日 · 标准 ${r.special_start}–${r.special_end}</span>` : '';
        timeCell = `<td>
          <span class="attn-time">
            <input type="text" inputmode="numeric" maxlength="5" placeholder="${placeholderStart}" data-date="${r.date}" data-field="start" value="${r.start || ''}">
            <span class="attn-arr">→</span>
            <input type="text" inputmode="numeric" maxlength="5" placeholder="${placeholderEnd}" data-date="${r.date}" data-field="end" value="${r.end || ''}">
          </span>
          ${hint}
        </td>`;
      }

      // 天数
      const fracText = autoRow ? '—' : (isEmpty ? '—' : r.day_fraction.toFixed(2));

      // 状态文字 + 已存在请假 tag
      let stCls, stText;
      if (isEmpty) {
        stCls = 'attn-st-todo';
        stText = '待填';
      } else {
        stCls = statusClsMap[r.status] || '';
        stText = isLeave ? `请假 ${r.leave_hours || 0}h` : (statusMap[r.status] || r.status);
      }
      const leaveTag = (isLeave && r.leave_type === 'range' && r.leave_start && r.leave_end)
        ? `<span class="attn-leave-tag">${r.leave_start}–${r.leave_end}</span>`
        : (isLeave && r.leave_type === 'left' && r.leave_start
            ? `<span class="attn-leave-tag">${r.leave_start} 起</span>`
            : '');

      // 行尾操作（hover 浮现）
      let ops = '';
      if (!autoRow) {
        if (isLeave) {
          ops = `<span class="attn-ops"><button class="attn-op attn-op-danger attn-leave-clear" data-date="${r.date}">取消</button></span>`;
        } else {
          const fillStart = isSpecial ? r.special_start : '09:30';
          const fillEnd = isSpecial ? r.special_end : '20:00';
          ops = `<span class="attn-ops">
            <button class="attn-op attn-fill" data-date="${r.date}" data-start="${fillStart}" data-end="${fillEnd}">按标准</button>
            <button class="attn-op attn-leave-add" data-date="${r.date}">请假</button>
          </span>`;
        }
      }

      return `<tr class="${rowCls}" data-date="${r.date}">
        <td><span class="attn-day">${r.date.slice(5)}</span><span class="attn-wk">周${r.weekday}</span></td>
        ${timeCell}
        <td class="attn-frac">${fracText}</td>
        <td><span class="attn-st ${stCls}">${stText}</span>${leaveTag}${ops}</td>
      </tr>`;
    }).join('');

    wrap.innerHTML = `
      <table class="attn-grid">
        <thead><tr><th style="width:130px">日期</th><th>时段</th><th style="width:80px">天数</th><th>状态</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;

    wrap.querySelectorAll('input[data-field]').forEach(inp => {
      inp.addEventListener('change', () => onCellChange(inp.dataset.date));
    });
    wrap.querySelectorAll('.attn-fill').forEach(btn => {
      btn.addEventListener('click', () => fillNormal(btn.dataset.date, btn.dataset.start, btn.dataset.end));
    });
    wrap.querySelectorAll('.attn-leave-add').forEach(btn => {
      btn.addEventListener('click', () => addLeave(btn.dataset.date));
    });
    wrap.querySelectorAll('.attn-leave-clear').forEach(btn => {
      btn.addEventListener('click', () => clearLeave(btn.dataset.date));
    });
  }

  let pendingLeaveDate = '';

  function addLeave(date) {
    pendingLeaveDate = date;
    document.getElementById('attnLeaveDate').textContent = date;
    document.querySelector('input[name="attnLeaveType"][value="full"]').checked = true;
    document.getElementById('attnLeaveStart').value = '';
    document.getElementById('attnLeaveEnd').value = '';
    document.getElementById('attnLeaveLeftStart').value = '';
    document.getElementById('attnLeaveOverlay').style.display = 'flex';
  }

  async function submitLeave() {
    const date = pendingLeaveDate;
    if (!date) return;
    const type = document.querySelector('input[name="attnLeaveType"]:checked').value;
    const payload = { type };
    const timeRe = /^([01]\d|2[0-3]):([0-5]\d)$/;
    if (type === 'range') {
      const s = normalizeTime(document.getElementById('attnLeaveStart').value);
      const e = normalizeTime(document.getElementById('attnLeaveEnd').value);
      if (!timeRe.test(s) || !timeRe.test(e)) { alert('请填写正确的离开/回来时间（HH:MM）'); return; }
      payload.start = s;
      payload.end = e;
    } else if (type === 'left') {
      const s = normalizeTime(document.getElementById('attnLeaveLeftStart').value);
      if (!timeRe.test(s)) { alert('请填写正确的离开时间（HH:MM）'); return; }
      payload.start = s;
    }
    try {
      const res = await fetch(`/attendance/leave/${currentEmployeeId}/${date}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } catch (e) { alert('请假失败：' + e.message); return; }
    document.getElementById('attnLeaveOverlay').style.display = 'none';
    await loadMonth();
  }

  async function clearLeave(date) {
    if (!confirm(`取消 ${date} 的请假？`)) return;
    try {
      const res = await fetch(`/attendance/leave/${currentEmployeeId}/${date}`, { method: 'DELETE' });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
    } catch (e) { alert('取消失败：' + e.message); return; }
    await loadMonth();
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

  async function fillAllNormal() {
    if (!currentEmployeeId || !currentMonth) {
      alert('请先选择员工和月份');
      return;
    }
    if (!currentSummary || !Array.isArray(currentSummary.detail)) {
      alert('数据未加载');
      return;
    }
    // 仅填空白工作日：跳过周日 / 节假日 / 特殊日 / 请假 / 已填
    const targets = currentSummary.detail.filter(r => {
      if (r.status === 'sunday' || r.status === 'holiday') return false;
      if (r.status === 'leave') return false;
      if (r.status === 'special' || r.status === 'special_absent') return false;
      if (r.start || r.end) return false;
      return true;
    });
    if (targets.length === 0) {
      alert('当前月份没有需要填充的空白工作日');
      return;
    }
    if (!confirm(`将为 ${targets.length} 个空白工作日填入 09:30–20:00，是否继续？`)) return;
    let ok = 0;
    let fail = 0;
    for (const r of targets) {
      try {
        const res = await fetch(`/attendance/day/${currentEmployeeId}/${r.date}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ start: '09:30', end: '20:00' }),
        });
        const body = await res.json();
        if (body.ok) ok++; else fail++;
      } catch (e) {
        fail++;
      }
    }
    await loadMonth();
    if (fail > 0) {
      alert(`填充完成：成功 ${ok} 天，失败 ${fail} 天`);
    }
  }

  function formatLeave(r) {
    const h = r.leave_hours || 0;
    if (!h) return '';
    const t = r.leave_type || '';
    if (t === 'range' && r.leave_start && r.leave_end) {
      return `${r.leave_start}-${r.leave_end} (${h}h)`;
    }
    if (t === 'left' && r.leave_start) {
      return `${r.leave_start} 起 (${h}h)`;
    }
    return `${h}h`;
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
    document.getElementById('attnLeaveH').textContent = summary ? (summary.leave_hours_total || 0) : 0;
    document.getElementById('attnLeaveD').textContent = summary ? (summary.leave_days_equivalent || 0) : 0;
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

  function downloadPayrollPdf() {
    if (!currentMonth) return;
    window.location.href = `/attendance/payroll-pdf/${currentMonth}`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  document.addEventListener('DOMContentLoaded', function () {
    init();
  });
})();
