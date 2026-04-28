# 考勤表 Notion 暗色风重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把考勤页表格从「8 列整行染色」重构为「4 列状态点 + hover 操作 + 内联占位编辑」的 Notion 暗色极简风，与站点 tokens.css 完全对齐。

**Architecture:** 前端纯 UI 重构。CSS 改写 `page-attendance.css`，JS 改 `attendance.js` 的 `init()` 顶部 HTML 模板和 `renderGrid()`，新增 `fillAllNormal()` 走现有 `POST /attendance/day` 接口。后端、modal 浮层、PDF 生成全部不动。

**Tech Stack:** 原生 JS（IIFE 模块）、纯 CSS（消费 tokens.css 变量）、Flask 后端（不改）。

**已确认设计决策（来自对话）：**
- 配色：A 套，复用 `tokens.css` 的 `--c-surface` / `--c-border` / `--c-accent` 等变量
- 列结构：日期 / 时段 / 天数 / 状态（含操作）— 共 4 列（原 8 列）
- 行染色：统一中性 surface 色，仅 `absent` 保留极淡红色背景
- 操作按钮：文字样式（"按标准" / "请假" / "取消"），hover 才浮现
- 时段输入：未填时显示 `09:30` / `20:00` 占位
- 顶部统计：5 个等宽 K/V 小卡片（替代现在的横向 `<span>`）
- 顶部新增按钮："一键填全月正常"——只填空白工作日，跳过已填/请假/特殊日/周日/节假日
- 浮层（请假/节假日/特殊日）保持原样不动
- 删除"快填"列（操作合并进状态列）

**参考 mockup：** `C:\Users\jxwu2002\Desktop\attendance_mockup_dark.html` 的 A 套

---

## File Structure

| 文件 | 操作 | 说明 |
|---|---|---|
| `static/css/page-attendance.css` | 全量重写 | 从 121 行改为按新结构组织：toolbar / stats-grid / grid (table) / state-dots / hover-ops |
| `static/js/attendance.js` | 修改 `init()` HTML 模板（行 10-78 中的 `.attn-top` 和 `.attn-stats` 部分），修改 `renderGrid()`（行 185-239），新增 `fillAllNormal()` 函数和事件监听 | modal 浮层 HTML、所有现有函数（`onCellChange`/`addLeave`/`submitLeave` 等）保持不变 |
| `static/js/attendance.js` 中的 modal 部分（行 31-77） | 不动 | 浮层样式继续走 `pur-modal` 类 |
| `attendance_service.py` / `routes_attendance.py` | 不动 | 没有新增/修改接口 |
| `attendance_report_service.py` | 不动 | PDF 生成与本任务无关 |

---

## Verification Strategy

本仓库无前端测试基建（仅 Python `pytest`），因此每个 UI 任务的 verify 用「**浏览器视觉检查清单**」+「**控制台无报错**」+「**网络面板请求正确**」三个具体可执行检查。

启动服务的命令统一为：
```bash
python app.py
```
然后浏览器访问 `http://localhost:5000`，点左侧导航 🕐 考勤。

---

## Task 1: 重写 page-attendance.css

**Files:**
- Modify: `static/css/page-attendance.css`（全量替换内容）

- [ ] **Step 1：备份当前 CSS（仅本次会话工作记忆，不提交）**

```bash
cp static/css/page-attendance.css static/css/page-attendance.css.bak
```

- [ ] **Step 2：用以下内容完全替换 `static/css/page-attendance.css`**

```css
/* ========== Page: 考勤（Notion 暗色极简风） ========== */
#pageAttendance.active {
  display: block;
  overflow: auto;
  height: calc(100vh - 100px);
}

/* ===== 外层 ===== */
.attn-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
}

/* ===== 顶部工具条 ===== */
.attn-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.attn-top label { color: var(--c-text-muted); font-size: var(--fs-base); }
.attn-top .attn-spacer { flex: 1; }

.attn-inp {
  padding: 5px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--c-border);
  background: var(--c-surface);
  color: var(--c-text);
  font-size: var(--fs-base);
}
.attn-inp:focus {
  outline: none;
  border-color: var(--c-accent);
  box-shadow: 0 0 0 2px var(--c-accent-soft);
}

.attn-btn {
  padding: 5px 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--c-border);
  background: var(--c-surface);
  color: var(--c-text);
  cursor: pointer;
  font-size: var(--fs-base);
  transition: background var(--t-fast), border-color var(--t-fast);
}
.attn-btn:hover { background: var(--c-surface-elev); border-color: var(--c-accent); }
.attn-btn-danger { border-color: #b91c1c; color: var(--c-danger); }
.attn-btn-dl {
  background: var(--c-accent);
  border-color: var(--c-accent);
  color: #fff;
}
.attn-btn-dl:hover { background: var(--c-accent-hover); border-color: var(--c-accent-hover); }

/* ===== 统计 K/V 小卡片（5 等分网格） ===== */
.attn-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 1px;
  background: var(--c-border);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  overflow: hidden;
}
.attn-stat {
  background: var(--c-surface);
  padding: 12px 16px;
}
.attn-stat-k {
  color: var(--c-text-dim);
  font-size: var(--fs-md);
}
.attn-stat-v {
  font-size: 20px;
  font-weight: 600;
  color: var(--c-text);
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}
.attn-stat-v small {
  font-size: var(--fs-md);
  color: var(--c-text-dim);
  font-weight: 400;
  margin-left: 4px;
}

/* ===== 表格容器 ===== */
.attn-grid-wrap {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  overflow: hidden;
}

/* ===== 表格 ===== */
.attn-grid {
  width: 100%;
  border-collapse: collapse;
  color: var(--c-text);
  font-size: var(--fs-base);
}
.attn-grid thead th {
  text-align: left;
  font-weight: 500;
  font-size: var(--fs-sm);
  color: var(--c-text-dim);
  letter-spacing: .04em;
  text-transform: uppercase;
  padding: 10px 16px;
  background: var(--c-surface-elev);
  border-bottom: 1px solid var(--c-border);
}
.attn-grid tbody td {
  padding: 9px 16px;
  vertical-align: middle;
  border-bottom: 1px solid var(--c-border-subtle);
}
.attn-grid tbody tr:last-child td { border-bottom: none; }
.attn-grid tbody tr:hover td { background: rgba(129,140,248,.04); }

/* 行背景：默认统一，仅 absent 保留极淡红 */
.attn-grid tr.absent td { background: rgba(248,113,113,.05); }
.attn-grid tr.absent:hover td { background: rgba(248,113,113,.08); }

/* ===== 日期 / 星期 ===== */
.attn-day { font-variant-numeric: tabular-nums; font-weight: 500; }
.attn-wk  { color: var(--c-text-dim); margin-left: 8px; font-size: var(--fs-md); }

/* ===== 时段单元 ===== */
.attn-time { display: inline-flex; align-items: center; gap: 4px; }
.attn-time input {
  width: 56px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--c-text);
  font: inherit;
  font-variant-numeric: tabular-nums;
  text-align: center;
  padding: 3px 6px;
  border-radius: var(--r-sm);
}
.attn-time input::placeholder { color: var(--c-text-faint); }
.attn-time input:hover { background: rgba(255,255,255,.04); }
.attn-time input:focus {
  outline: none;
  background: var(--c-bg);
  border-color: var(--c-accent);
  box-shadow: 0 0 0 2px var(--c-accent-soft);
}
.attn-time .attn-arr { color: var(--c-text-faint); }
.attn-time-auto { color: var(--c-text-dim); font-style: italic; }

/* 时段后的小提示（特殊日缩短工时） */
.attn-time-hint {
  display: block;
  color: var(--c-text-faint);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

/* ===== 天数 ===== */
.attn-frac {
  font-variant-numeric: tabular-nums;
  color: var(--c-text-mute2);
}

/* ===== 状态点 + 文字 ===== */
.attn-st {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-md);
  color: var(--c-text-muted);
}
.attn-st::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c-text-faint);
  flex-shrink: 0;
}
.attn-st-normal::before  { background: var(--c-success); }
.attn-st-absent          { color: var(--c-danger); }
.attn-st-absent::before  { background: var(--c-danger); }
.attn-st-leave           { color: var(--c-warn); }
.attn-st-leave::before   { background: var(--c-warn); }
.attn-st-special         { color: var(--c-warn-strong); }
.attn-st-special::before { background: var(--c-warn-strong); }
.attn-st-sunday::before  { background: var(--c-accent-fg); }
.attn-st-holiday         { color: var(--c-info); }
.attn-st-holiday::before { background: var(--c-info); }
.attn-st-todo::before    { background: transparent; box-shadow: inset 0 0 0 1px var(--c-text-faint); }

/* 已存在的请假信息 tag */
.attn-leave-tag {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: var(--r-sm);
  background: var(--c-warn-bg);
  color: var(--c-warn);
  font-size: var(--fs-xs);
  border: 1px solid rgba(251,191,36,.25);
}

/* ===== 行尾操作按钮组（hover 浮现） ===== */
.attn-ops {
  display: inline-flex;
  gap: 2px;
  margin-left: 10px;
  opacity: 0;
  transition: opacity var(--t-fast);
}
.attn-grid tr:hover .attn-ops,
.attn-grid tr.attn-has-leave .attn-ops { opacity: 1; }
.attn-op {
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: var(--fs-md);
  color: var(--c-text-muted);
  padding: 3px 8px;
  border-radius: var(--r-sm);
}
.attn-op:hover { background: var(--c-accent-soft); color: var(--c-accent-fg); }
.attn-op-danger:hover { background: var(--c-danger-bg); color: var(--c-danger); }

/* ===== 浮层（保留原 .pur-modal 类，下面只补 attn 专用辅助类） ===== */
.attn-hidden { display: none; }
.attn-time-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.attn-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.attn-narrow { width: 70px; }

/* ===== 错误/空提示 ===== */
.attn-empty-msg { color: var(--c-text-dim); padding: 20px; }
.attn-error-msg { color: var(--c-danger); padding: 20px; }
```

- [ ] **Step 3：删除备份**

```bash
rm static/css/page-attendance.css.bak
```

- [ ] **Step 4：Commit**

```bash
git add static/css/page-attendance.css
git commit -m "refactor(attendance): 重写表格 CSS 为 Notion 暗色极简风"
```

---

## Task 2: 修改 attendance.js init() 顶部模板（toolbar + stats 卡片）

**Files:**
- Modify: `static/js/attendance.js:10-30`（`init()` 函数中 `page.innerHTML` 模板的开头部分）

- [ ] **Step 1：将 `init()` 中 `page.innerHTML` 的前 21 行（即 `<div class="attn-wrap">` 至 `<div id="attnGridWrap"></div>` 之间的 toolbar + stats 部分）替换为新结构**

定位锚点：当前文件的 `init()` 函数从行 7 开始，`page.innerHTML = \`...\``  从行 10 开始。整个模板字符串结束于行 78（反引号结尾）。本步骤**只**替换 `<div class="attn-wrap">` 内部的前两块：`.attn-top` 和 `.attn-stats`。

将原来的：

```js
        <div class="attn-top">
          <label>月份 <input class="attn-inp" id="attnMonth" type="month"></label>
          <label>员工 <select class="attn-inp" id="attnEmployee"></select></label>
          <button class="attn-btn" id="attnEmpNew">+ 新建</button>
          <button class="attn-btn attn-btn-danger" id="attnEmpDel">删除员工</button>
          <button class="attn-btn" id="attnHolidays">节假日</button>
          <button class="attn-btn" id="attnSpecial">特殊日</button>
          <button class="attn-btn attn-btn-dl" id="attnPdf">下载 PDF</button>
          <button class="attn-btn attn-btn-dl" id="attnPayrollPdf">下载工资单 PDF</button>
        </div>
        <div class="attn-stats">
          <span>累计 <b id="attnWorked">0</b> 天</span>
          <span>缺勤 <b id="attnAbsent">0</b> 天</span>
          <span>总工作日 <b id="attnTotal">0</b></span>
          <span>本月天数 <b id="attnMonthDays">0</b></span>
          <span>请假 <b id="attnLeaveH">0</b> 小时（约 <b id="attnLeaveD">0</b> 天）</span>
        </div>
        <div id="attnGridWrap"></div>
```

替换为：

```js
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
```

**注意：** `id="attnWorked"` 等 5 个 ID 都从 `<b>` 标签搬到了 `<span>` 标签，但 ID 名称完全不变，所以 `updateStats()` 函数（行 355-362）不需要改。

- [ ] **Step 2：在 `init()` 末尾（其他 `addEventListener` 之后、`document.getElementById('attnMonth').value = ...` 之前）追加一行事件绑定**

定位：当前文件 `init()` 函数中最后一个 `addEventListener` 在行 99（`attnLeaveCancel`）。在它后面、行 101 之前插入：

```js
    document.getElementById('attnFillAll').addEventListener('click', fillAllNormal);
```

- [ ] **Step 3：浏览器视觉验证**

```bash
python app.py
```

打开 `http://localhost:5000` → 切到考勤页 → 检查：
- [ ] 顶部工具条最右侧出现"一键填全月正常"按钮（点击会报错是正常的，函数下个 task 才加）
- [ ] 统计区是 5 个等宽卡片（一行排列），每个卡片上方小灰字 K、下方大白字 V
- [ ] 5 个数值正确显示（点击其他月份/员工切换时会变）
- [ ] 浏览器 F12 控制台**无 JS 报错**（点 fillAll 按钮会报错，先不点）

- [ ] **Step 4：Commit**

```bash
git add static/js/attendance.js
git commit -m "refactor(attendance): 顶部工具条新增填月按钮，统计区改为卡片网格"
```

---

## Task 3: 重写 renderGrid() — 4 列状态点 + hover 操作 + 占位编辑

**Files:**
- Modify: `static/js/attendance.js:185-239`（整个 `renderGrid()` 函数）

- [ ] **Step 1：将整个 `renderGrid()` 函数（行 185-239）替换为以下实现**

```js
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
```

**关键差异说明（给执行者）：**
- 列从 8 列降为 4 列：日期合并星期、上班+下班合并为时段、快填列移除、请假并入状态列
- 状态用「色点 + 文字」（`.attn-st` + 状态修饰类），不再整行染色（除 absent 保留极淡红色）
- 操作按钮在状态单元格末尾，hover 行才浮现（`.attn-ops`）
- 时段输入框未填时显示占位（特殊日用 `special_start/end`，普通日用 `09:30/20:00`）
- 引入 `isEmpty`（工作日空白）显示「待填」状态点
- `r.weekday` 后端返回的是数字字符（"一"/"二"...），保持原样在前缀加"周"

- [ ] **Step 2：浏览器视觉验证清单**

```bash
python app.py
```

切到考勤页（任选一个有数据的员工 + 月份），逐项核对：
- [ ] 表格只有 4 列：日期 / 时段 / 天数 / 状态
- [ ] 普通工作日已填：时段显示绿色"正常"点 + 文字，hover 行才看到行尾"请假"按钮
- [ ] 普通工作日未填：时段输入框是淡灰占位 `09:30`/`20:00`，状态显示空心圆 + "待填"
- [ ] 缺勤行：极淡红色行底，状态红点 + "缺勤"
- [ ] 周日：时段显示斜体"自动（周日）"，无操作按钮
- [ ] 节假日：时段显示斜体"自动（节假日）"
- [ ] 特殊日：时段输入框占位是缩短工时的时间，下方小灰字 hint "特殊日 · 标准 09:30–14:30"
- [ ] 请假行：状态黄点 + "请假 4h" + 黄色 tag 显示具体时段，行尾按钮始终可见（不需 hover）
- [ ] 点击时段输入框 → 蓝色聚焦边框 → 输入新时间 → 失焦保存 → 行刷新
- [ ] 点击 hover 出现的"按标准"按钮 → 填入 09:30/20:00 并保存
- [ ] 点击"请假"按钮 → 弹出原有请假浮窗（功能不变）
- [ ] 点击请假行的"取消"按钮 → 弹 confirm → 取消请假
- [ ] 浏览器 F12 控制台无 JS 报错

- [ ] **Step 3：Commit**

```bash
git add static/js/attendance.js
git commit -m "refactor(attendance): renderGrid 改为 4 列状态点 + hover 操作"
```

---

## Task 4: 实现 fillAllNormal() — 一键填全月正常

**Files:**
- Modify: `static/js/attendance.js`（在 `fillNormal` 函数后追加新函数，约行 302 之后）

- [ ] **Step 1：在 `fillNormal` 函数（当前 attendance.js:293-301）的右花括号 `}` 之后插入新函数**

```js
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
```

- [ ] **Step 2：确认 `currentSummary` 在 `loadMonth()` 中被赋值**

定位 attendance.js 中的 `loadMonth` 函数（约行 175-183），检查是否有 `currentSummary = body;` 这行。如果没有，在 `renderGrid(body.detail);` 之前一行插入：

```js
      currentSummary = body;
```

完整 `loadMonth` 应大致如下（仅做参考，找到对应位置确认即可）：

```js
  async function loadMonth() {
    if (!currentEmployeeId || !currentMonth) return;
    const wrap = document.getElementById('attnGridWrap');
    wrap.innerHTML = '<div class="attn-empty-msg">加载中...</div>';
    try {
      const res = await fetch(`/attendance/month/${currentEmployeeId}/${currentMonth}`);
      const body = await res.json();
      if (!body.ok) { wrap.innerHTML = `<div class="attn-error-msg">${body.msg || '加载失败'}</div>`; return; }
      currentSummary = body;
      renderGrid(body.detail);
      updateStats(body);
    } catch (e) { wrap.innerHTML = `<div class="attn-error-msg">加载失败：${e.message}</div>`; }
  }
```

- [ ] **Step 3：浏览器验证**

```bash
python app.py
```

测试场景：
- [ ] 选一个有 5+ 个空白工作日的月份 → 点"一键填全月正常" → 弹 confirm 显示具体数量 → 确认 → 表格刷新，所有空白工作日变为已填
- [ ] 再次点击 → 提示"当前月份没有需要填充的空白工作日"
- [ ] 选一个全是特殊日 + 周日的月份（或先全部请假）→ 点击 → 提示"没有需要填充的空白工作日"
- [ ] F12 网络面板：可看到对应数量的 `POST /attendance/day/<emp>/<date>` 请求，全部 200
- [ ] 已请假/特殊日/已填的日期**没有**被覆盖（视觉上确认行还是原状态）

- [ ] **Step 4：Commit**

```bash
git add static/js/attendance.js
git commit -m "feat(attendance): 新增「一键填全月正常」按钮"
```

---

## Task 5: 端到端回归 + 编码检查

**Files:** 无修改，仅验证

- [ ] **Step 1：回归现有功能（确认重构没破坏老路径）**

```bash
python app.py
```

逐项过：
- [ ] 切换月份 / 员工 → 表格刷新正常
- [ ] 新建员工 / 删除员工 → 浮窗弹出、操作生效
- [ ] 节假日管理 → 浮窗弹出、增删生效（浮窗样式仍是原 `pur-modal` 风格，**这是预期的**）
- [ ] 特殊日管理 → 同上
- [ ] 请假浮窗 → 三种类型（全天 / 离开后回来 / 离开未回来）都能提交
- [ ] 取消请假 → confirm 后状态变回普通
- [ ] 下载 PDF / 工资单 PDF → 文件正常生成（PDF 内容样式与本次重构无关）
- [ ] 控制台无任何 JS 错误

- [ ] **Step 2：跑后端测试，确认 Python 侧没受牵连**

```bash
pytest tests/test_attendance_service.py tests/test_attendance_report_service.py -v
```

预期：全部 PASS（本次未改 Python，应不受影响）。

- [ ] **Step 3：编码检查**

`page-attendance.css` 和 `attendance.js` 含中文注释/字符串，确认 UTF-8 无 BOM：

```bash
file static/css/page-attendance.css static/js/attendance.js
```

预期：均为 `UTF-8 Unicode text`（不含 `with BOM`）。如果是 BOM，重新保存为 UTF-8 无 BOM。

- [ ] **Step 4：（可选）截图归档**

把考勤页正常状态的截图保存到 `docs/superpowers/specs/` 旁边（命名 `2026-04-28-attendance-table-redesign.png`），便于后续比对。

- [ ] **Step 5：最终 commit（仅当有修复项才需要；正常情况下无需）**

```bash
# 如果回归过程中发现并修了小 bug：
git add -A
git commit -m "fix(attendance): 重构后回归修复"
```

---

## 完成判据

全部 5 个 Task 完成、全部 verify 清单勾上、`pytest` 全过、F12 无报错、视觉与 mockup A 套基本一致 → 任务完成。

如有视觉细节需要微调（行高、字号、间距、状态点颜色饱和度等），独立提交一个 commit："style(attendance): 视觉微调"。
