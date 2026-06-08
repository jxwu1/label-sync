# scraper 周任务护栏 + staging 自清（最小治本）

**Date:** 2026-06-08
**Branch:** fix/scraper-run-boundary
**Status:** 草案（待用户批准）

## 背景与根因

2026-06-08 事故：每周一 `run_weekly.ps1` 把 `scraper/staging/` 里的历史大文件
（`events_sale_2015-01-01_2023-01-02.parquet` 19MB 等）重新脱敏 + 上传。

根因两条：
1. `scraper/staging/` 是永久垃圾桶——`run_weekly.ps1` 上传成功后只把 `sanitized/`
   挪到 `uploaded/`，**从不清 staging**；scraper 每周写新文件名
   （`events_<type>_<from>_<to>`，窗口每周变），**只累积不覆盖**。
2. `sanitize.py` 批量模式 glob 整个 `STAGING_DIR`（`events_*` / `inventory_snapshot_*`
   / `product_master_*`），不看文件多老，把所有历史文件重新脱敏。

代价：DB 唯一约束 `uq_inventory_events` 挡住重复 → **零数据污染**，但每周白传
~30MB + 全历史 ETL；本次还卡死在 19MB sale 上传上导致本周真增量没上、heartbeat 没打。

## 范围（本轮：护栏优先 + staging 自清）

只做最小可上线防护，把"静默重传历史"改成"遇历史响亮 abort"。

**明确不做**（留给以后的完整 run-boundary 重构）：
- 不做 per-run 目录（`scraper/runs/<run_id>/...`）
- 不做独立 `run_backfill.ps1`
- 不重构整个 scraper 管道
- 不改服务器导入逻辑

## 文件名格式（已核实）

- `events_sale_<from>_<to>.parquet` / `events_purchase_<from>_<to>.parquet`（`.xlsx` 同名，sanitize 只 glob `.parquet`）
- `inventory_snapshot_<date>.parquet`
- `product_master_<date>.parquet`
- 日期一律 `YYYY-MM-DD`

## 设计

### 1. 新模块 `scraper/scrape_window.py`（纯函数 + 轻 CLI）

日期判断单源，两层护栏都复用，单元可测。

```
parse_window(filename) -> (kind, start: date|None, end: date|None)
    kind 由文件名前缀决定（不是解析成功与否）:
      events_*    → kind="events"
      inventory_snapshot_* → kind="snapshot"
      product_master_*     → kind="master"
      其它前缀    → kind="unknown"
    匹配到前缀但日期解析失败 → kind 保持该前缀, start/end=None
      （区分"坏命名的目标文件" vs "无关文件"）

weekly_violation(filename, today, max_span_days=14, max_age_days=14) -> str | None
    返回违规原因字符串，合规返回 None。
    events:   start 或 end 为 None（日期解析失败）→ 拒（坏命名目标文件）
              否则 span = (end - start).days；span > max_span_days → 拒
              start < today - max_age_days → 拒
    snapshot: date 为 None（解析失败）→ 拒
              否则 date < today - max_age_days → 拒（陈旧快照）
    master:   date 为 None（解析失败）→ 拒
              否则永远放行（月度全量，无业务窗口）
    unknown:  放行——仅指**不匹配任何目标前缀**的无关文件
              （CLI/sanitize 的 glob 本来也不会扫到它）
```

**关键**：被扫描 glob（`events_*` / `inventory_snapshot_*` / `product_master_*`）命中的
目标文件，若日期解析失败 → **违规**（防坏命名历史文件绕过护栏）。只有完全不匹配
目标前缀的无关文件才走 `unknown` 放行。

CLI（第二层 manifest 闸用）：
```
python scraper/scrape_window.py --check <dir> [--max-total-mb 50] [--allow-backfill]
    扫描 <dir> 下 events_*/inventory_snapshot_*/product_master_*.parquet
    打印 manifest（每文件名 + 大小 + 总大小）
    任一文件 weekly_violation 命中（且无 --allow-backfill）→ 退出码 1
    总大小 > max_total_mb → 退出码 1
    全部合规 → 退出码 0
```

**manifest 必须按 kind 分组显式列出**，尤其 `product_master_*` 单独成行标注
（如 `[master] product_master_2026-06-08.parquet`）。product_master 设计为日期合法
即放行（本轮重点是阻断 events/snapshot 历史重传，不管 master），所以靠 manifest
让人工可见：**非月初周（day > 7）却出现 product_master → review 时重点看一眼**，
防旧 master 文件静默重传。

`today` 注入：CLI 默认用系统当天；纯函数 `weekly_violation` 接 `today` 参数，
测试传固定日期（不依赖系统时钟）。

### 2. `sanitize.py` —— 第一层（拒绝产出）

- batch（weekly）模式：遍历 staging 文件前，先对每个文件跑 `weekly_violation`。
  命中且**无 `--allow-backfill`** → 打印所有违规文件 + 原因 → **非零退出**
  （`run_weekly.ps1` 的 `Run-Step` 见非零会 throw，整周任务停）。
- 新增 `--allow-backfill` flag：历史回填时手动放行，跳过 `weekly_violation` 检查。
- 单文件 `--input` 模式**不变**（手动操作，信任调用者，不加检查）。
- 复用 `scrape_window.weekly_violation`，不在 sanitize 里重写日期逻辑。

### 3. `run_weekly.ps1` —— 第二层 manifest 闸 + staging 自清

**上传前**（sanitize 之后、curl 之前）：
- 调 `python scraper/scrape_window.py --check $sanitizedDir`，输出进日志。
- 非零退出 → `throw` → 落入现有 `catch` → exit 1 → **不上传、不触发
  categories/forecast/heartbeat**（沿用现有 try/catch 链，天然满足）。
- 这是防御纵深：第一层（sanitize）正常时 sanitized/ 已不含历史；第二层兜
  sanitize 被绕过/出 bug 的情况，并额外加总大小闸 + manifest 日志。

**上传成功后**（所有 curl 成功、sanitized 已挪 uploaded 之后）：
- 把对应 staging 源文件挪到 `uploaded/<ts>/staging/`（对称于 sanitized→uploaded）：
  移动 `staging/` 下 `events_*` / `inventory_snapshot_*` / `product_master_*` 的
  `.parquet` + `.xlsx`。
- **保留 `staging/_cache/`**（抓取缓存，不上传、不归档）。
- 效果：staging 自清，护栏长期成立，不再累积历史。

### 4. 一次性清理（实施前归档全部现存目标文件）

实施前，把 `staging/` 与 `sanitized/` 下**所有现存**的目标文件
（`events_*` / `inventory_snapshot_*` / `product_master_*` 的 `.parquet` + `.xlsx`）
归档到 `staging_archive/` 下一个带说明的目录（保留现场，不删），让下周一 staging
从干净开始。`_cache/` 保留。

**执行者必须以实际扫描结果为准，不照搬固定名单**——历史上 staging 是垃圾桶，
可能残留任意多个历史文件。

> 本次（2026-06-08）核实快照：`staging/` 恰好只剩本周 6 文件
> （`events_purchase_2026-06-01_2026-06-08.{parquet,xlsx}`、
> `events_sale_2026-06-01_2026-06-08.{parquet,xlsx}`、
> `inventory_snapshot_2026-06-08.{parquet,xlsx}`），`sanitized/` 为空——历史大文件
> 已在前一 session 归档到 `staging_archive/`。但实现时仍须用 glob 扫实际内容归档，
> 不得 hardcode 这 6 个名字。

## 数据流（weekly 正常路径，改造后）

```
refresh_cookie → 抓取(sale/purchase/inventory[/master]) → 写 staging/
  → sanitize.py(第一层: weekly_violation 全过 → 写 sanitized/)
  → scrape_window --check sanitized(第二层: manifest + 大小闸 → 通过)
  → curl 上传每个 sanitized 文件 → 成功挪 uploaded/<ts>/
  → 挪对应 staging 源文件 → uploaded/<ts>/staging/   ← 新增自清
  → categories/recompute → forecast/refresh → heartbeat → exit 0
```

任一步失败 → throw → catch → exit 1 → 不打 heartbeat → 8 天后服务端红条告警。

## 错误处理

- 目标文件（匹配三类前缀）日期解析失败 → **违规退出**（防坏命名历史文件绕过）。
- 仅不匹配任何目标前缀的无关文件 → `kind="unknown"` 放行（glob 本来也不扫它）。
- `weekly_violation` 命中 → 第一层 sanitize 非零退出，第二层 CLI 退出码 1，
  PS 侧 throw。错误信息列出**具体文件名 + 原因**（span 超 / start 太旧 / 快照陈旧 / 总量超）。
- staging 自清 Move-Item 失败 → throw（数据已入库不会丢，仅 staging 没清干净，
  下次仍会被护栏挡或重传，dedup 兜底）。

## 测试（TDD）

`tests/` 下新增 `test_scrape_window.py`，覆盖纯函数：
- `parse_window`：四类前缀（events/snapshot/master/unknown）kind 判定正确；
  匹配前缀但日期坏（如 `events_sale_xx_yy.parquet`）→ kind 仍为前缀、start/end=None。
- 坏命名目标文件（`events_*` 前缀但日期解析失败）→ `weekly_violation` 返回违规；
  无关前缀文件（如 `README.md`、`foo.parquet`）→ `weekly_violation` 返回 None。
- `weekly_violation`（固定 `today=2026-06-08`）：
  - 正常本周 events（06-01→06-08，span 7）→ None
  - span > 14（如 2015-01-01→2023-01-02）→ 拒，原因含 span
  - start < today-14（旧但短跨度）→ 拒，原因含 age/start
  - 陈旧 snapshot（2023-01-02）→ 拒
  - 当周 snapshot（2026-06-08）→ None
  - master（任意日期）→ None
  - 边界：start == today-14、span == 14 的处理明确（实现时定 ≤/< 并测）

CLI `--check` 行为（用 tmp_path 造文件）：
- 全合规 → 退出 0
- 含历史文件 → 退出 1 + 打印违规
- `--allow-backfill` → 历史也退出 0
- 总大小超阈值 → 退出 1

`run_weekly.ps1` 不做单测（PS 脚本），靠第二层 CLI 的 pytest + 一次手动 dry-run
验收（造一个历史文件进 sanitized，确认 `--check` 挡住）。

## 验收标准

1. `pytest tests/test_scrape_window.py` 全绿。
2. 全量 `pytest tests/` 不回归。
3. 手动 dry-run：sanitized/ 放一个 2015 历史文件 → `scrape_window --check` 退出码 1。
4. 本周残留已归档，staging 只剩 `_cache/`。
5. `run_weekly.ps1` review：abort 路径不触发 heartbeat；成功路径自清 staging。
