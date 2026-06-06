# 抓取失败告警 — 设计 spec

**日期**: 2026-06-06
**状态**: 设计已确认, 待 review → writing-plans
**所属**: 第1期② 稳定可信 / 老板视角 backlog #1 数据新鲜度延伸

## 问题

当前 `get_data_freshness()` 只看 `max(inventory_events.imported_at)`, 距上次灌数 > 9 天报红。
缺陷: 分不清两种情况, 两者都表现为 `imported_at` 不前进——

- **静默周**: 抓取器正常跑了, 但这周真没新销售 → 正常, 不该告警。
- **抓取挂了**: cookie 失效 / 抓取器没跑 → 该告警, 但要等 9 天才被动变红。

需要一个**独立于"数据是否到达"的"抓取成败"信号源**, 让抓取中断能更早(且可区分地)暴露。

## 范围

**全在本仓**: 心跳端点 + 存储 + freshness 集成 + 红条逻辑 + (顺带) admin.js bug 修复 +
抓取器侧接线。抓取器 `scraper/run_weekly.ps1` 也在本仓 (非跨仓), 故在其成功刷新链
末尾加 `Invoke-Refresh "scrape/heartbeat"` 也是本 feature 的一部分 (否则脚本一直正常跑
也永远不打心跳, 8 天后红条必然误报)。

## 设计

### ① 存储 — SystemSetting

复用现有 `system_settings` 表 (key/value/updated_at/updated_by), **零迁移**。

- key: `scrape:last_success_at`
- value: **UTC ISO 时间戳**, `datetime.now(timezone.utc).isoformat(timespec="seconds")`
  - 例: `2026-06-06T12:34:56+00:00`
- 写入用现有 SystemSetting upsert 路径 (get/set helper 或 session merge)。

### ② 心跳端点 — POST /analytics/scrape/heartbeat

放 analytics 蓝图 (与 `/analytics/data-freshness` 同组, 复用 before_request, 省一个 blueprint)。

- 鉴权: `@require_upload_token` (token-only; 抓取器持 UPLOAD_TOKEN, 与 cron 同源)。
- **无 body**: 服务端盖 `now(UTC)` 写 `scrape:last_success_at`。
- 返回: `{"ok": true, "last_scrape_success_at": "<UTC ISO>"}`。
- 语义: 抓取器**仅在成功跑完时**打这一下 (无论本轮有无新数据)。这正是"静默周 vs 抓取挂"可区分的来源。

抓取器侧 (本仓 `scraper/run_weekly.ps1`, 本 feature 实现): 在成功刷新链
(`categories/recompute` → `forecast/refresh`) **末尾**加一行, 只有整条链路成功才打:
```
Invoke-Refresh "scrape/heartbeat" "$refreshBase/scrape/heartbeat"
```
(`Invoke-Refresh` 是脚本既有 helper, 带 `X-Upload-Token` POST 并校验返回 ok。)

### ③ freshness 集成 — get_data_freshness() 增 3 字段

在现有返回 (`last_import_at, last_import_date, days_since, stale`) 基础上增:

- `last_scrape_success_at`: 存储里的 UTC ISO 字符串, 没有则 `None`
- `scrape_days_since`: `(as_of - 心跳日期).days`, 没有则 `None`
- `scrape_stale`: `scrape_days_since > _SCRAPE_STALE_DAYS`, 没有心跳则 `False`

要点:
- 阈值 `_SCRAPE_STALE_DAYS = 8` (周抓 7 天 + 1 缓冲; 比数据龄 `_DATA_STALE_DAYS=9` 更早暴露)。
- **只按日期算** `scrape_days_since`: 解析存储的 UTC ISO → 取其 `date()` → `(as_of - scrape_date).days`。`as_of` 用本地 `_today()`。刻意只到天粒度, 避免时区细节影响 UI (8 天阈值下 ±1 天 TZ 偏差可接受)。
- 从没收到心跳 (key 不存在) → `last_scrape_success_at=None, scrape_days_since=None, scrape_stale=False` (新系统/本地不误报, 与现有空库 `stale=False` 行为一致)。
- 既有数据龄 `stale` 保留, 降为辅助信号。

### ④ 红条逻辑 — 改 x-show 优先级

当前模板红条条件是 `x-show="f && f.last_import_date"`——未来"没有入库记录但有/缺心跳"时红条会完全不显示。改成按优先级:

1. `scrape_stale` → **红色**, 「抓取可能中断（距上次成功抓取 N 天）」
2. 否则 `stale` → 保留原"数据陈旧"提示
3. 否则有 `last_import_date` → 正常显示数据截止
4. 否则有 `last_scrape_success_at` → 中性显示"抓取器最近成功 ..."
5. 都没有 → 不显示

**红条整体显示条件写死** (避免实现时还挂在旧的 `last_import_date` 上):
```
f && (f.scrape_stale || f.stale || f.last_import_date || f.last_scrape_success_at)
```
内部再按上述 1-5 优先级决定颜色/文案。

### ⑤ admin.js bug — opportunistic bugfix (独立 task/commit)

`renderRecentImports` 与 `/inventory/imports` 端点字段对不上, 永远显示"暂无 import 记录":

- `r.items` → 应为 `r.imports`
- 逐行字段重映射到端点真字段:
  - `it.status` → 由 `error_count` 派生: `error_count > 0` → ✗; `error_count === 0` → ✓
  - `it.file_type` → `it.event_type`
  - `it.rows_imported` → 行数优先用 `total_rows`, 必要时旁边显示 `ok_count`
  - `it.file_name` → `it.filename`

**与心跳不是同一逻辑链**, 单独 commit。**不计入 heartbeat 的验收标准**, 仅因都在"系统状态/数据新鲜度"页面附近顺手修。验证靠本地浏览器 / e2e。

## 测试语义 (写死)

### 心跳端点鉴权 (full-app, 经 before_request + decorator)
- 无 token + 未登录 → **302** `/login`
- 错 token → **401**
- 服务端缺 `UPLOAD_TOKEN` env 且请求带 token → **500**
- 正确 token → **200** 且写入 `SystemSetting(key="scrape:last_success_at")`

### freshness scrape 字段
- 空心跳 (无 key) → `last_scrape_success_at=None, scrape_stale=False`
- fresh 心跳 (今天) → `scrape_stale=False`
- stale 心跳 (> 8 天前) → `scrape_stale=True`
- **8 天边界**: 恰好 8 天 → `False`; 9 天 → `True` (即 `> 8`, 非 `>=`)

## 非目标 (YAGNI)

- 抓取器失败时主动上报 (本设计只做成功心跳 + 缺心跳推断, 不接收 failure POST)。
- 邮件/推送告警 (只页面红条)。
- 心跳历史/审计表 (只存最近一次成功时间, 单 SystemSetting key)。

## 受影响文件 (预估)

- `app/routes/analytics.py` — 新增 heartbeat 端点
- `app/services/analytics/freshness.py` — 增 3 字段 + `_SCRAPE_STALE_DAYS`
- `templates/` + `static/js/` — 红条优先级逻辑
- `static/js/admin.js` — bug 修复 (独立 commit)
- `scraper/run_weekly.ps1` — 成功刷新链末尾加 heartbeat 接线
- `tests/` — 端点鉴权 + freshness scrape 字段
