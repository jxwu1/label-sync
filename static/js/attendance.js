(function () {
  let employees = [];
  let currentEmployeeId = '';
  let currentMonth = '';
  let currentSummary = null;

  // PR-FE-7a：日历视图常量
  const WEEKDAY_HEADERS = ['一', '二', '三', '四', '五', '六', '日'];
  const WEEKDAY_INDEX = { '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6 };
  const STATUS_LABEL = {
    sunday: '周日', holiday: '节假日', absent: '缺勤', normal: '正常',
    special: '特殊日', special_absent: '特殊缺勤', leave: '请假',
    pre_join: '未入职', todo: '待填',
  };
  // 视觉 dot 用的 key（special_absent 折叠成 absent；空 → todo）
  const STATUS_VISUAL_KEY = {
    sunday: 'sunday', holiday: 'holiday', absent: 'absent', normal: 'normal',
    special: 'special', special_absent: 'absent', leave: 'leave',
    pre_join: 'pre-join',
  };

  // PR-FE-7c：多选状态
  const _selectedDates = new Set();
  let _lastClickDate = null;
  // 数字键 → batch action
  const KEY_TO_BATCH = { '1': 'normal', '2': 'absent', '3': 'am', '4': 'pm', '5': 'clear' };

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
          <button class="attn-btn" id="attnLeaveRange">区间请假</button>
          <button class="attn-btn" id="attnInactive">不在职区间</button>
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
        <div class="attn-batch attn-hidden" id="attnBatch">
          <span class="attn-batch-count">已选 <b id="attnBatchN">0</b> 天</span>
          <span class="attn-batch-sep"></span>
          <button class="attn-batch-btn" data-batch="normal">正常 <kbd>1</kbd></button>
          <button class="attn-batch-btn" data-batch="absent">缺勤 <kbd>2</kbd></button>
          <button class="attn-batch-btn" data-batch="am">上半天 <kbd>3</kbd></button>
          <button class="attn-batch-btn" data-batch="pm">下半天 <kbd>4</kbd></button>
          <button class="attn-batch-btn attn-batch-btn-danger" data-batch="clear">清除 <kbd>5</kbd></button>
          <span class="attn-spacer"></span>
          <button class="attn-batch-btn" id="attnBatchCancel">取消选择 <kbd>Esc</kbd></button>
        </div>
        <div class="attn-main">
          <div id="attnGridWrap"></div>
          <aside class="attn-rail" id="attnRail">
            <div class="attn-rail-hd">员工 <span class="attn-rail-count" id="attnRailCount">0</span></div>
            <div class="attn-rail-list" id="attnRailList"></div>
          </aside>
        </div>
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
      <div class="pur-modal-overlay attn-hidden" id="attnLeaveRangeOverlay">
        <div class="pur-modal">
          <div class="pur-modal-hd">区间请假（自动跳过周日）</div>
          <div class="attn-stack">
            <label>从 <input class="attn-inp" id="attnLeaveRangeFrom" type="date"></label>
            <label>到 <input class="attn-inp" id="attnLeaveRangeTo" type="date"></label>
            <label><input type="radio" name="attnLeaveRangeType" value="full" checked> 全天</label>
            <label><input type="radio" name="attnLeaveRangeType" value="range"> 离开后回来：
              <input class="attn-inp attn-narrow" id="attnLeaveRangeStart" type="text" placeholder="HH:MM" maxlength="5"> —
              <input class="attn-inp attn-narrow" id="attnLeaveRangeEnd" type="text" placeholder="HH:MM" maxlength="5">
            </label>
            <label><input type="radio" name="attnLeaveRangeType" value="left"> 离开未回来：
              <input class="attn-inp attn-narrow" id="attnLeaveRangeLeftStart" type="text" placeholder="HH:MM" maxlength="5">
            </label>
          </div>
          <div class="pur-modal-actions">
            <button class="attn-btn attn-btn-dl" id="attnLeaveRangeSubmit">确认</button>
            <button class="attn-btn" id="attnLeaveRangeCancel">取消</button>
          </div>
        </div>
      </div>
      <div class="pur-modal-overlay attn-hidden" id="attnInactiveOverlay">
        <div class="pur-modal">
          <div class="pur-modal-hd">不在职区间（产假 / 长期休假 / 停薪留职）</div>
          <div class="attn-modal-hint">
            区间内每天完全不计入考勤（含周日 / 节假日）。与单日请假不同：单日请假周日仍算 1.0，这里的天周日也不算。
          </div>
          <div class="attn-time-row">
            <input class="attn-inp" id="attnInactiveFrom" type="date">
            <span>—</span>
            <input class="attn-inp" id="attnInactiveTo" type="date">
            <input class="attn-inp" id="attnInactiveReason" type="text" placeholder="原因（可选）">
            <button class="attn-btn attn-btn-dl" id="attnInactiveAdd">添加</button>
          </div>
          <div id="attnInactiveList" class="pur-mgr-list"></div>
          <div class="pur-modal-actions">
            <button class="attn-btn" id="attnInactiveClose">关闭</button>
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
          <div class="attn-time-row">
            <span class="attn-hint-inline">批量导入希腊法定节假日：</span>
            <select class="attn-inp" id="attnHolidayYear">
              <option value="2025">2025</option>
              <option value="2026" selected>2026</option>
            </select>
            <button class="attn-btn attn-btn-dl" id="attnHolidayImport">导入</button>
          </div>
          <div id="attnHolidayList" class="pur-mgr-list"></div>
          <div class="pur-modal-actions">
            <button class="attn-btn" id="attnHolidayClose">关闭</button>
          </div>
        </div>
      </div>
      <div class="attn-pop attn-hidden" id="attnPop">
        <div class="attn-pop-hd" id="attnPopHd"></div>
        <div class="attn-pop-status">
          <button class="attn-pop-btn" data-pop="normal">正常</button>
          <button class="attn-pop-btn" data-pop="leave">请假</button>
          <button class="attn-pop-btn attn-pop-btn-danger" data-pop="clear">清除</button>
        </div>
        <div class="attn-pop-times">
          <input type="text" id="attnPopStart" maxlength="5" placeholder="HH:MM">
          <span class="attn-pop-arr">→</span>
          <input type="text" id="attnPopEnd" maxlength="5" placeholder="HH:MM">
          <button class="attn-pop-btn attn-pop-btn-primary" data-pop="save">保存</button>
        </div>
        <div class="attn-pop-quick">
          <button class="attn-pop-btn-quick" data-quick="standard">按标准</button>
          <button class="attn-pop-btn-quick" data-quick="am">上半天</button>
          <button class="attn-pop-btn-quick" data-quick="pm">下半天</button>
        </div>
        <div class="attn-pop-foot">
          <button class="attn-pop-btn" data-pop="cancel">取消</button>
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
    document.getElementById('attnHolidayImport').addEventListener('click', importHolidaysYear);
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
    document.getElementById('attnLeaveRange').addEventListener('click', openLeaveRange);
    document.getElementById('attnLeaveRangeSubmit').addEventListener('click', submitLeaveRange);
    document.getElementById('attnLeaveRangeCancel').addEventListener('click', () => {
      document.getElementById('attnLeaveRangeOverlay').style.display = 'none';
    });
    document.getElementById('attnInactive').addEventListener('click', openInactive);
    document.getElementById('attnInactiveAdd').addEventListener('click', addInactivePeriod);
    document.getElementById('attnInactiveClose').addEventListener('click', () => {
      document.getElementById('attnInactiveOverlay').style.display = 'none';
    });

    document.getElementById('attnMonth').value = new Date().toISOString().slice(0, 7);
    currentMonth = document.getElementById('attnMonth').value;
    bindPopover();
    bindBatchBar();
    window.addEventListener('resize', syncRailHeight);
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
    await loadMonth();
  }

  function renderEmployeeSelect() {
    const sel = document.getElementById('attnEmployee');
    sel.innerHTML = employees.map(e => `<option value="${e.id}">${escapeHtml(e.name)}</option>`).join('');
    if (currentEmployeeId) sel.value = currentEmployeeId;
  }

  // ===== PR-FE-7d-2：员工 rail（右侧栏 + 月填写率） =====

  async function refreshRail() {
    if (!currentMonth) return;
    let rates = [];
    try {
      const res = await fetch(`/attendance/fill-rates/${currentMonth}`);
      const body = await res.json();
      if (body.ok) rates = body.employees;
    } catch {
      rates = [];
    }
    renderRail(rates);
  }

  function renderRail(rates) {
    const list = document.getElementById('attnRailList');
    document.getElementById('attnRailCount').textContent = rates.length;
    if (!rates.length) {
      list.innerHTML = '<div class="attn-rail-empty">暂无员工</div>';
      return;
    }
    list.innerHTML = rates.map((r) => {
      const pct = Math.round((r.rate || 0) * 100);
      const active = r.id === currentEmployeeId ? ' is-active' : '';
      const fillCls = pct >= 100 ? ' attn-rail-bar-fill--full'
                    : pct >= 70 ? ' attn-rail-bar-fill--ok'
                    : pct >= 30 ? ' attn-rail-bar-fill--mid'
                    : ' attn-rail-bar-fill--low';
      return `<button class="attn-rail-item${active}" data-emp-id="${r.id}">
        <div class="attn-rail-name">${escapeHtml(r.name)}</div>
        <div class="attn-rail-bar"><div class="attn-rail-bar-fill${fillCls}" style="width:${pct}%"></div></div>
        <div class="attn-rail-meta">${r.filled} / ${r.total} 天 · ${pct}%</div>
      </button>`;
    }).join('');
    list.querySelectorAll('.attn-rail-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.empId;
        if (id === currentEmployeeId) return;
        currentEmployeeId = id;
        document.getElementById('attnEmployee').value = id;
        _selectedDates.clear();
        _lastClickDate = null;
        loadMonth();
      });
    });
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
    _selectedDates.clear();
    _lastClickDate = null;
    loadMonth();
  }

  function onMonthChange(e) {
    currentMonth = e.target.value;
    _selectedDates.clear();
    _lastClickDate = null;
    loadMonth();
  }

  async function loadMonth() {
    const wrap = document.getElementById('attnGridWrap');
    if (!currentEmployeeId || !currentMonth) {
      wrap.innerHTML = '<div class="attn-empty-msg">请先选择员工和月份</div>';
      updateStats(null);
      refreshRail();
      return;
    }
    try {
      const res = await fetch(`/attendance/month/${currentEmployeeId}/${currentMonth}`);
      const body = await res.json();
      if (!body.ok) { wrap.innerHTML = `<div class="attn-error-msg">${body.msg}</div>`; return; }
      currentSummary = body;
      renderCalendar(body.detail);
      updateStats(body);
    } catch (e) { wrap.innerHTML = `<div class="attn-error-msg">加载失败：${e.message}</div>`; }
    refreshRail();
  }

  // ===== PR-FE-7a：日历视图渲染 =====

  function isAutoStatus(status) {
    return status === 'sunday' || status === 'holiday';
  }

  function deriveCellStatus(r) {
    if (r.status === 'pre_join') return { key: 'pre-join', label: '未入职' };
    const isLeave = r.status === 'leave';
    const isEmpty = !isAutoStatus(r.status) && !isLeave && !r.start && !r.end;
    if (isEmpty) return { key: 'todo', label: '待填' };
    return {
      key: STATUS_VISUAL_KEY[r.status] || 'normal',
      label: STATUS_LABEL[r.status] || r.status,
    };
  }

  function buildTimeText(r) {
    if (r.status === 'pre_join') return '—';
    if (r.status === 'sunday') return '自动 · 周日';
    if (r.status === 'holiday') return '自动 · 节假日';
    if (r.status === 'leave') {
      if (r.leave_type === 'range' && r.leave_start && r.leave_end) {
        return `请假 ${r.leave_start}–${r.leave_end}`;
      }
      if (r.leave_type === 'left' && r.leave_start) {
        return `请假 ${r.leave_start} 起`;
      }
      return `请假 ${r.leave_hours || 0}h`;
    }
    if (r.start || r.end) return `${r.start || '—'} → ${r.end || '—'}`;
    return '—';
  }

  function buildCellHtml(r) {
    const dayNum = parseInt(r.date.slice(8, 10), 10);
    const st = deriveCellStatus(r);
    const time = buildTimeText(r);
    const showFrac = !isAutoStatus(r.status) && r.status !== 'pre_join'
      && (r.day_fraction || r.status === 'leave');
    const fracText = showFrac ? `<div class="attn-cell-frac">${(r.day_fraction || 0).toFixed(2)}d</div>` : '';
    return `<div class="attn-cell attn-cell--${st.key}" data-date="${r.date}">
      <div class="attn-cell-hd">
        <span class="attn-cell-day">${dayNum}</span>
        <span class="attn-cell-dot"></span>
      </div>
      <div class="attn-cell-bd">
        <div class="attn-cell-time">${escapeHtml(time)}</div>
        ${fracText}
        <div class="attn-cell-st">${st.label}</div>
      </div>
    </div>`;
  }

  function buildEmptyCellHtml() {
    return '<div class="attn-cell attn-cell--out"></div>';
  }

  function buildCalendarHtml(detail) {
    if (!detail.length) return '<div class="attn-empty-msg">无数据</div>';
    const leadingEmpty = WEEKDAY_INDEX[detail[0].weekday] || 0;
    const cells = [];
    for (let i = 0; i < leadingEmpty; i++) cells.push(buildEmptyCellHtml());
    for (const r of detail) cells.push(buildCellHtml(r));
    while (cells.length % 7 !== 0) cells.push(buildEmptyCellHtml());
    const headers = WEEKDAY_HEADERS.map((w) => `<div class="attn-cal-hd">周${w}</div>`).join('');
    return `<div class="attn-cal">
      <div class="attn-cal-headers">${headers}</div>
      <div class="attn-cal-grid">${cells.join('')}</div>
    </div>`;
  }

  function isCellEditable(cell) {
    return !(cell.classList.contains('attn-cell--out')
      || cell.classList.contains('attn-cell--pre-join')
      || cell.classList.contains('attn-cell--sunday')
      || cell.classList.contains('attn-cell--holiday'));
  }

  function bindCellClicks(wrap) {
    wrap.querySelectorAll('.attn-cell[data-date]').forEach((cell) => {
      if (!isCellEditable(cell)) return;
      cell.addEventListener('click', (e) => onCellClick(e, cell));
    });
  }

  function onCellClick(e, cell) {
    const date = cell.dataset.date;
    if (e.metaKey || e.ctrlKey) {
      if (_popDate) closePopover();
      toggleSelected(date);
    } else if (e.shiftKey && _lastClickDate) {
      if (_popDate) closePopover();
      selectDateRange(_lastClickDate, date);
    } else {
      // 单击：清空选择，开 popover
      if (_selectedDates.size > 0) clearSelection();
      openPopover(date, cell);
    }
    _lastClickDate = date;
  }

  function toggleSelected(date) {
    if (_selectedDates.has(date)) _selectedDates.delete(date);
    else _selectedDates.add(date);
    syncSelectionUI();
  }

  function selectDateRange(fromDate, toDate) {
    if (!currentSummary || !Array.isArray(currentSummary.detail)) return;
    const dates = currentSummary.detail.map((r) => r.date);
    let i = dates.indexOf(fromDate);
    let j = dates.indexOf(toDate);
    if (i < 0 || j < 0) return;
    if (i > j) [i, j] = [j, i];
    for (let k = i; k <= j; k++) {
      const d = dates[k];
      const r = currentSummary.detail[k];
      // 跳过不可编辑日
      if (r.status === 'pre_join' || r.status === 'sunday' || r.status === 'holiday') continue;
      _selectedDates.add(d);
    }
    syncSelectionUI();
  }

  function clearSelection() {
    _selectedDates.clear();
    syncSelectionUI();
  }

  function syncSelectionUI() {
    const wrap = document.getElementById('attnGridWrap');
    wrap.querySelectorAll('.attn-cell.is-selected').forEach((c) => c.classList.remove('is-selected'));
    _selectedDates.forEach((d) => {
      const cell = wrap.querySelector(`.attn-cell[data-date="${d}"]`);
      if (cell) cell.classList.add('is-selected');
    });
    const bar = document.getElementById('attnBatch');
    document.getElementById('attnBatchN').textContent = _selectedDates.size;
    if (_selectedDates.size > 0) bar.classList.remove('attn-hidden');
    else bar.classList.add('attn-hidden');
  }

  function renderCalendar(detail) {
    const wrap = document.getElementById('attnGridWrap');
    wrap.classList.add('attn-grid-wrap');
    wrap.innerHTML = buildCalendarHtml(detail);
    bindCellClicks(wrap);
    syncSelectionUI();
    observeCalendarHeight();
  }

  function syncRailHeight() {
    const cal = document.querySelector('.attn-cal');
    const rail = document.getElementById('attnRail');
    if (!cal || !rail) return;
    const h = cal.offsetHeight;
    if (h > 0) rail.style.maxHeight = h + 'px';
  }

  let _calHeightObserver = null;
  function observeCalendarHeight() {
    if (_calHeightObserver) _calHeightObserver.disconnect();
    const cal = document.querySelector('.attn-cal');
    if (!cal) return;
    // ResizeObserver 在 cal 任何尺寸变化（包括从 display:none 变可见）时触发
    _calHeightObserver = new ResizeObserver(syncRailHeight);
    _calHeightObserver.observe(cal);
  }

  // ===== PR-FE-7b：DayEditor popover =====

  let _popDate = '';

  function detailFor(date) {
    if (!currentSummary || !Array.isArray(currentSummary.detail)) return null;
    return currentSummary.detail.find((r) => r.date === date) || null;
  }

  function defaultTimes(r) {
    const isSpecial = r && (r.status === 'special' || r.status === 'special_absent');
    return {
      start: isSpecial ? r.special_start : '09:30',
      end: isSpecial ? r.special_end : '20:00',
    };
  }

  function positionPopover(pop, anchor) {
    const ar = anchor.getBoundingClientRect();
    const margin = 8;
    pop.style.visibility = 'hidden';
    pop.classList.remove('attn-hidden');
    const pr = pop.getBoundingClientRect();
    let top = ar.bottom + margin;
    if (top + pr.height > window.innerHeight - margin) {
      top = Math.max(margin, ar.top - margin - pr.height);
    }
    let left = ar.left;
    if (left + pr.width > window.innerWidth - margin) {
      left = window.innerWidth - margin - pr.width;
    }
    if (left < margin) left = margin;
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;
    pop.style.visibility = '';
  }

  function openPopover(date, anchor) {
    const r = detailFor(date);
    if (!r) return;
    _popDate = date;
    const pop = document.getElementById('attnPop');
    const def = defaultTimes(r);
    document.getElementById('attnPopHd').textContent = `${date} · 周${r.weekday}`;
    document.getElementById('attnPopStart').value = r.start || '';
    document.getElementById('attnPopEnd').value = r.end || '';
    document.getElementById('attnPopStart').placeholder = def.start;
    document.getElementById('attnPopEnd').placeholder = def.end;
    positionPopover(pop, anchor);
  }

  function closePopover() {
    _popDate = '';
    document.getElementById('attnPop').classList.add('attn-hidden');
  }

  async function popoverAction(action) {
    if (!_popDate) return;
    if (action === 'cancel') { closePopover(); return; }
    if (action === 'leave') {
      const date = _popDate;
      closePopover();
      addLeave(date);
      return;
    }
    if (action === 'clear') {
      const r = detailFor(_popDate);
      if (r && r.status === 'leave') {
        const date = _popDate;
        closePopover();
        await clearLeave(date);
      } else {
        await saveCellTimes(_popDate, '', '');
        closePopover();
      }
      return;
    }
    if (action === 'normal') {
      const r = detailFor(_popDate);
      const def = defaultTimes(r);
      const ok = await saveCellTimes(_popDate, def.start, def.end);
      if (ok) closePopover();
      return;
    }
    if (action === 'save') {
      const start = document.getElementById('attnPopStart').value;
      const end = document.getElementById('attnPopEnd').value;
      const ok = await saveCellTimes(_popDate, start, end);
      if (ok) closePopover();
    }
  }

  async function popoverQuickFill(kind) {
    if (!_popDate) return;
    let start;
    let end;
    if (kind === 'standard') {
      const r = detailFor(_popDate);
      const def = defaultTimes(r);
      start = def.start;
      end = def.end;
    } else if (kind === 'am') {
      start = '09:30';
      end = '14:00';
    } else if (kind === 'pm') {
      start = '14:00';
      end = '20:00';
    } else {
      return;
    }
    document.getElementById('attnPopStart').value = start;
    document.getElementById('attnPopEnd').value = end;
    const ok = await saveCellTimes(_popDate, start, end);
    if (ok) closePopover();
  }

  function bindPopover() {
    const pop = document.getElementById('attnPop');
    pop.addEventListener('click', (e) => {
      const popBtn = e.target.closest('[data-pop]');
      if (popBtn) { popoverAction(popBtn.dataset.pop); return; }
      const quickBtn = e.target.closest('[data-quick]');
      if (quickBtn) popoverQuickFill(quickBtn.dataset.quick);
    });
    document.addEventListener('click', (e) => {
      if (!_popDate) return;
      if (e.target.closest('#attnPop')) return;
      if (e.target.closest('.attn-cell[data-date]')) return; // 让 cell click 自己换 anchor
      closePopover();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && _popDate) closePopover();
    });
  }

  // ===== PR-FE-7c：批量操作 =====

  function batchActionUrlAndBody(action, date, r) {
    if (action === 'normal') {
      const isSpecial = r && (r.status === 'special' || r.status === 'special_absent');
      const start = isSpecial ? r.special_start : '09:30';
      const end = isSpecial ? r.special_end : '20:00';
      return { method: 'POST', url: `/attendance/day/${currentEmployeeId}/${date}`, body: { start, end } };
    }
    if (action === 'am') {
      return { method: 'POST', url: `/attendance/day/${currentEmployeeId}/${date}`, body: { start: '09:30', end: '14:00' } };
    }
    if (action === 'pm') {
      return { method: 'POST', url: `/attendance/day/${currentEmployeeId}/${date}`, body: { start: '14:00', end: '20:00' } };
    }
    if (action === 'absent' || action === 'clear') {
      // 缺勤 = 清除时段（backend 派生 absent）
      return { method: 'DELETE', url: `/attendance/day/${currentEmployeeId}/${date}`, body: null };
    }
    return null;
  }

  async function applyBatchAction(action) {
    if (_selectedDates.size === 0) return;
    const dates = [..._selectedDates];
    const detail = (currentSummary && currentSummary.detail) || [];
    let ok = 0;
    let fail = 0;
    for (const date of dates) {
      const r = detail.find((x) => x.date === date);
      const req = batchActionUrlAndBody(action, date, r);
      if (!req) continue;
      try {
        const init = { method: req.method };
        if (req.body) {
          init.headers = { 'Content-Type': 'application/json' };
          init.body = JSON.stringify(req.body);
        }
        const res = await fetch(req.url, init);
        if (req.method !== 'DELETE') {
          const body = await res.json();
          if (body.ok) ok++; else fail++;
        } else {
          ok++;
        }
      } catch {
        fail++;
      }
    }
    clearSelection();
    await loadMonth();
    if (fail > 0) alert(`批量操作完成：成功 ${ok} 天，失败 ${fail} 天`);
  }

  function bindBatchBar() {
    const bar = document.getElementById('attnBatch');
    bar.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-batch]');
      if (btn) applyBatchAction(btn.dataset.batch);
    });
    document.getElementById('attnBatchCancel').addEventListener('click', clearSelection);
    document.addEventListener('keydown', (e) => {
      if (_selectedDates.size === 0) return;
      // 跳过输入态
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (e.key === 'Escape') { clearSelection(); return; }
      const action = KEY_TO_BATCH[e.key];
      if (action) {
        e.preventDefault();
        applyBatchAction(action);
      }
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

  function openLeaveRange() {
    if (!currentEmployeeId) {
      alert('请先选择员工');
      return;
    }
    // 默认填当月第 1 天到当月最后一天
    const m = currentMonth || new Date().toISOString().slice(0, 7);
    document.getElementById('attnLeaveRangeFrom').value = `${m}-01`;
    // 算当月最后一天
    const [yy, mm] = m.split('-').map(Number);
    const last = new Date(yy, mm, 0).getDate();
    document.getElementById('attnLeaveRangeTo').value = `${m}-${String(last).padStart(2, '0')}`;
    document.querySelector('input[name="attnLeaveRangeType"][value="full"]').checked = true;
    document.getElementById('attnLeaveRangeStart').value = '';
    document.getElementById('attnLeaveRangeEnd').value = '';
    document.getElementById('attnLeaveRangeLeftStart').value = '';
    document.getElementById('attnLeaveRangeOverlay').style.display = 'flex';
  }

  async function submitLeaveRange() {
    const from = document.getElementById('attnLeaveRangeFrom').value;
    const to = document.getElementById('attnLeaveRangeTo').value;
    if (!from || !to) { alert('请填写起止日期'); return; }
    if (from > to) { alert('起始日不能晚于结束日'); return; }
    const type = document.querySelector('input[name="attnLeaveRangeType"]:checked').value;
    const payload = { from_date: from, to_date: to, type };
    const timeRe = /^([01]\d|2[0-3]):([0-5]\d)$/;
    if (type === 'range') {
      const s = normalizeTime(document.getElementById('attnLeaveRangeStart').value);
      const e = normalizeTime(document.getElementById('attnLeaveRangeEnd').value);
      if (!timeRe.test(s) || !timeRe.test(e)) { alert('请填写正确的离开/回来时间（HH:MM）'); return; }
      payload.start = s;
      payload.end = e;
    } else if (type === 'left') {
      const s = normalizeTime(document.getElementById('attnLeaveRangeLeftStart').value);
      if (!timeRe.test(s)) { alert('请填写正确的离开时间（HH:MM）'); return; }
      payload.start = s;
    }
    try {
      const res = await fetch(`/attendance/leave-range/${currentEmployeeId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      const skipped = body.days_skipped_sunday || 0;
      const set = body.days_set || 0;
      alert(`已设置 ${set} 天请假${skipped > 0 ? `（跳过 ${skipped} 个周日）` : ''}`);
    } catch (e) { alert('区间请假失败：' + e.message); return; }
    document.getElementById('attnLeaveRangeOverlay').style.display = 'none';
    await loadMonth();
  }

  async function openInactive() {
    if (!currentEmployeeId) {
      alert('请先选择员工');
      return;
    }
    document.getElementById('attnInactiveFrom').value = '';
    document.getElementById('attnInactiveTo').value = '';
    document.getElementById('attnInactiveReason').value = '';
    await loadInactiveList();
    document.getElementById('attnInactiveOverlay').style.display = 'flex';
  }

  async function loadInactiveList() {
    try {
      const res = await fetch(`/attendance/inactive-periods/${currentEmployeeId}`);
      const body = await res.json();
      renderInactiveList(body.periods || []);
    } catch (e) {
      renderInactiveList([]);
    }
  }

  function renderInactiveList(periods) {
    const list = document.getElementById('attnInactiveList');
    if (!periods.length) {
      list.innerHTML = '<div class="empty">暂无不在职区间</div>';
      return;
    }
    list.innerHTML = periods.map(p => `
      <div class="attn-inactive-row">
        <span class="attn-inactive-range">${escapeHtml(p.from)} 至 ${escapeHtml(p.to)}</span>
        ${p.reason ? `<span class="attn-inactive-reason">${escapeHtml(p.reason)}</span>` : ''}
        <button class="attn-btn attn-btn-danger attn-inactive-del" data-from="${p.from}" data-to="${p.to}">删除</button>
      </div>
    `).join('');
    list.querySelectorAll('.attn-inactive-del').forEach(btn => {
      btn.addEventListener('click', () => removeInactivePeriod(btn.dataset.from, btn.dataset.to));
    });
  }

  async function addInactivePeriod() {
    const from = document.getElementById('attnInactiveFrom').value;
    const to = document.getElementById('attnInactiveTo').value;
    const reason = document.getElementById('attnInactiveReason').value.trim();
    if (!from || !to) { alert('请填写起止日期'); return; }
    if (from > to) { alert('起始日不能晚于结束日'); return; }
    try {
      const res = await fetch(`/attendance/inactive-periods/${currentEmployeeId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: from, to_date: to, reason }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      renderInactiveList(body.periods);
      document.getElementById('attnInactiveFrom').value = '';
      document.getElementById('attnInactiveTo').value = '';
      document.getElementById('attnInactiveReason').value = '';
      // 刷新当月 summary（如果当前月份有受影响的天）
      await loadMonth();
    } catch (e) { alert('添加失败：' + e.message); }
  }

  async function removeInactivePeriod(from, to) {
    if (!confirm(`删除不在职区间 ${from} ~ ${to}？`)) return;
    try {
      const res = await fetch(`/attendance/inactive-periods/${currentEmployeeId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: from, to_date: to }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return; }
      renderInactiveList(body.periods);
      await loadMonth();
    } catch (e) { alert('删除失败：' + e.message); }
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

  async function saveCellTimes(date, start, end) {
    const s = normalizeTime(start);
    const e = normalizeTime(end);
    const timeRe = /^([01]\d|2[0-3]):([0-5]\d)$/;
    if (!s && !e) {
      await fetch(`/attendance/day/${currentEmployeeId}/${date}`, { method: 'DELETE' });
    } else if (s && e) {
      if (!timeRe.test(s) || !timeRe.test(e)) {
        alert('时间格式错误，请按 HH:MM 填写（如 09:30）');
        return false;
      }
      const res = await fetch(`/attendance/day/${currentEmployeeId}/${date}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start: s, end: e }),
      });
      const body = await res.json();
      if (!body.ok) { alert(body.msg); return false; }
    } else {
      alert('开始和结束时间需都填或都空');
      return false;
    }
    await loadMonth();
    return true;
  }

  async function fillNormal(date, start, end) {
    await saveCellTimes(date, start || '09:30', end || '20:00');
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

  function normalizeTime(raw) {
    const s = String(raw || '').trim();
    if (!s) return '';
    const digits = s.replace(/\D/g, '');
    if (digits.length === 3) return `0${digits[0]}:${digits.slice(1)}`;
    if (digits.length === 4) return `${digits.slice(0, 2)}:${digits.slice(2)}`;
    return s;
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

  async function importHolidaysYear() {
    const year = document.getElementById('attnHolidayYear').value;
    try {
      const res = await fetch(`/attendance/holidays/import-year/${year}`, { method: 'POST' });
      const body = await res.json();
      if (!body.ok) { alert(body.msg || '导入失败'); return; }
      alert(`已导入 ${year} 年希腊法定节假日：新增 ${body.added} 天`);
    } catch (e) { alert('导入失败：' + e.message); return; }
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
