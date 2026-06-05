# 预测效果看板 UI — 设计

**日期：** 2026-06-05
**分支：** feat/forecast-eval-ui
**状态：** 待实现

## 背景与目标

后端切片①②③已上线（main `ac4c7fe`）：置信度分层 `confidence_tier` + 聚合端点 `GET /analytics/backtest/dashboard`，但**零前端**。本任务做切片④：一个只读的「预测效果」看板页，让老板/操作员快速判断「预测可不可信」「该不该换模型」。

cron⑤（定时刷新）不在本 spec，另起分支。

## 端点契约（已实现，前端只消费）

`GET /analytics/backtest/dashboard` 返回：
```
{
  ok: true,
  run_id: int | null,            // null = 尚无 backtest 数据
  backtest_date: str | null,     // 生产 run 的 created_at
  forecast_skus: int,            // forecast_output 总行数
  scored_skus: int,              // 有 backtest mase 的 SKU 数
  tiers: { high: int, medium: int, low: int },
  headline: { n, median_mase, beats_naive_pct, avg_coverage_p98 },
  by_sku_type: [ { sku_type, n, median_mase, beats_naive_pct, avg_coverage_p98 } ],
  models: [ { model_name, run_id, created_at, is_production, n, median_mase, beats_naive_pct, avg_coverage_p98 } ]
}
```

**指标单位（前端格式化依据）：**
- `median_mase`：浮点（如 0.87）→ `.toFixed(2)`
- `beats_naive_pct`：已 ×100（如 62.0）→ 四舍五入 + `%`
- `avg_coverage_p98`：0–1（如 0.96）→ `×100` 四舍五入 + `%`
- 任一为 `null` → 显示 `—`

**重要契约：`models` 不保证 6 行。** 后端是「每个模型有最新 run 才返回」，空库 / 本地 seed 不全时可能 <6 行甚至 0 行。前端必须渲染 `data.models || []`，空则整表显 `—`，**不得硬编码 6 行**。`by_sku_type` 同理（可能为空数组）。

## 范围

**做：** 只读看板——数据新鲜度 + headline KPI + 置信度分布 + 按 SKU 类型表 + 模型对比表 + 刷新。

**不做（YAGNI）：** 点 tier 下钻 per-SKU 清单（端点不返明细）、切换生产模型、导出。

## 视觉风格

**工作台看板风格**：不要 hero、不要大装饰。顶部紧凑标题 + KPI 条 + 两个表格面板，方便老板一眼扫到「MASE<1 占比」。复用现有 `.pnl` 面板风格与设计 token。

## 架构

### 后端
无改动。复用 `GET /analytics/backtest/dashboard`。

### 前端：新页面 + 新模块
- **导航项**：`store.js` 的 `pages` 数组加 `{ id: "forecast_eval", label: "预测效果", icon: "sales", code: "09", shortcut: "9" }`（复用空出的 09 槽；旧 `sales_analytics` 已注释，不冲突）。
- **页面容器**：`templates/index.html` 加 `<div class="page" id="pageForecastEval" x-data :class="$store.nav.current === 'forecast_eval' ? 'active' : ''"></div>`。
- **模块** `static/js/forecast_eval.js`：自注册 `Alpine.store("nav").onFirstActivate("forecast_eval", initForecastEval)` 懒加载（首次开页才拉数）。`initForecastEval` fetch `GET /analytics/backtest/dashboard` → 渲染进 `#pageForecastEval`。
- **脚本挂载**：`templates/index.html` 底部 `<script type="module">` 块（现 1493–1506）内加一行：
  ```html
  <script type="module" src="{{ url_for('static', filename='js/forecast_eval.js') }}"></script>
  ```
  （**实现清单必须包含这一步**，否则模块不加载、`onFirstActivate` 永不注册。）

## 渲染块（五块，只读）

1. **头部**：标题「预测效果」+ 数据新鲜度 `run #{run_id} · {backtest_date}` + 「↻ 刷新」按钮。
2. **headline KPI 条**：MASE<1占比（`beats_naive_pct`）/ 中位 MASE（`median_mase`）/ 覆盖@p98（`avg_coverage_p98`）/ 评分 `{scored_skus}/{forecast_skus}`。
3. **置信度分布**：高/中/低 三色比例条 + 计数（`tiers.high/medium/low`）。
4. **表1 按 SKU 类型**：列 = SKU类型 / 评分数(n) / 中位MASE / 胜Naive% / 覆盖。数据 `by_sku_type`，空 → 表内 `—`。
5. **表2 模型对比**：列 = 模型 / 中位MASE / 胜Naive% / 覆盖 / 生产。数据 `data.models || []`，`is_production` 行高亮 + ★，空 → `—`。

## 空 / 缺态

`run_id === null`（无 backtest）：顶部黄条提示「尚无回测数据，置信度全部按缺失评为低」。tier 分布仍渲染（后端返回全 low），两表与 headline 显 `—`。前端只需识别 `run_id === null` 即可，结构由后端保证完整。

## 安全 / 转义

`sku_type`、`model_name` 来自 DB，拼进 innerHTML 前经 `shared.js` 的 `esc`。数值字段格式化后是受控字符串。

## 样式

新增 CSS 进 `static/css/components.css`：置信度三色比例条 + 两个表格。复用现有 `.pnl` / `.pnl-hd` / KPI 条 token。

## 测试 / 验证

后端端点已测（`test_forecast_eval_dashboard.py`）。前端无 JS 单测框架 → 本地浏览器手测 + Playwright 截图。

**本地数据注意（用户 PG 备忘）：** 本地 PG 可能无 backtest/forecast_output 数据 → 默认进**空/缺态**。验证分两路：
1. **空/缺态 + 布局**：直接开页，确认 `run_id===null` 黄条 + 全低 tier + 两表 `—`，布局不裂。
2. **正常态**：seed 少量 `ForecastOutput`（含 sku_type/n_weeks_history/nonzero_weeks/zero_weeks_last8）+ `BacktestRun`/`BacktestResult`（mase/coverage_p98）行，刷新看 KPI / 分布 / 两表渲染；或部署后对线上 run 44（4279 SKU）核对。
3. Playwright 暗/亮主题各截一张。

## 开放项 / 范围外

- 下钻、导出、切模型：YAGNI，不做。
- 旧 `pageSalesAnalytics` DOM：保持现状（已无 nav 入口），不在本任务清理。
