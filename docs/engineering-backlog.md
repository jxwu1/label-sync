# 工程待办总览（engineering backlog）

> 生成: 2026-06-09，来源：后端（架构/质量/运维）+ 前端（模板/JS）五路全项目 review
> + shared.js 统一实操中的发现。与论文 Phase 无关的工程债集中在这里，做完打勾。
>
> 已完成：✅ 前端工具层统一（shared.js: esc/byId/qs/apiFetch，14 文件去重，`fc0d72a`）
> ✅ cron 失败告警接通（TG 每日巡检 + scraper 失败直报，`e809f7d`，2026-06-10）

---

## P0 — 价值兑现 + 防盲飞（各 2-3 天）

- [ ] **dashboard 预测卡片** — forecast_output 表已建并被简报/补货页消费（本条原表述过时），
  剩 dashboard 的 UI 出口半截；方案见 `docs/superpowers/plans/2026-05-12-forecast-and-backtest.md` §3.7
- [x] **cron 失败告警接通** — ✅ 2026-06-10（`e809f7d`）：服务端每日 07:30 巡检三类数据超期 → TG
  推送（每日限频）+ run_weekly.ps1 失败直报；残余风险（cron 容器自身死亡不报警）见
  `docs/superpowers/specs/2026-06-10-cron-failure-alert-design.md`，v2 候选外部死人开关

## P1 — 工程质量收口（各 0.5-2 天，独立可发布）

- [ ] **后端统一错误处理** — 8+ 路由裸 `except Exception` 无日志（`app/routes/attendance.py` 7 处、
  `app/routes/history.py:15`）；3 处 `except OSError: pass` 静默吞错（`app/routes/inventory.py:88`、
  `app/routes/stockpile.py:50`）→ Flask errorhandler + logging 收口
- [ ] **apiFetch 迁移** — shared.js 封装已就位，25 个 JS 文件散装 fetch 逐文件迁；
  优先修两个真 bug：`inventory.js` 预览失败不清缓存、`purchase.js` 解析失败 rows 残留
- [ ] **修 e2e 烟雾测试** — `test_smoke_nav.py` / `test_nav_lazy_load.py` 在 main 上已坏
  （auth 后没更新被 302 到登录墙 + 引用已下线的 sales_analytics/transfer 页）；
  修法：`page.request.post("/login")` + nav 列表从 Alpine store 动态取
- [ ] **requirements.txt 锁版本** — 目前全裸名，每次 Coolify build 赌上游兼容

## P2 — 结构债（无依赖，有重构窗口时整体做）

- [ ] 拆 `app/routes/analytics.py`（983 行单蓝图 → sku / restock / forecast 子蓝图）
- [ ] 拆 `app/services/attendance.py`（794 行混 CRUD / 假期 / 报表 / 导入四职责）
- [ ] route→service 越层收口（20+ 处路由直接 ORM：`dashboard.py:119-285`、
  `inventory.py:298-353`、`analytics.py:87`、`admin.py:45`）
- [ ] 拆三个千行 JS（attendance 1340 / restock 1248 / purchase 996 → 按渲染/动作/数据切）
- [ ] pnl 面板头 Jinja 宏化（同一结构 12 个 partial 里重复 50+ 次）
- [ ] Alembic 25 个迁移补 downgrade（目前全单向，生产回滚难）

## P3 — 运维硬化（部分与论文路线图 Phase 4 重合，同做）

- [ ] **scraper 单点消除**（风险最高）— Task Scheduler + Chrome session 绑死本地机，
  失败无重试；短期加重试+告警，中期评估迁容器内 cron
- [ ] 日志中央化（docker logs 无聚合，Loki 轻量方案优先）
- [ ] 业务监控指标（healthcheck 只测 HTTP 200；导入延迟/预测新鲜度无暴露）
- [ ] DB 备份 RTO/RPO 明确化 + 恢复演练（与 pg_dump 自动备份同做）

## P4 — 小项（顺手做）

- [ ] 折叠控件补 `aria-expanded` + 键盘支持（`_page_admin.html:60`、`_page_history.html:54` onclick 改 Alpine）
- [ ] 2 处 `x-html` 审核，能换 `x-text` 就换（`_page_dashboard.html:91`、`_page_main.html:181`）
- [ ] 搜索框补关联 label（`_page_restock.html:33`、`_page_history.html:14`）
- [ ] components.css 收敛（`.btn--primary` / `.btn-primary` 双命名统一，重复规则约减 40%）
- [ ] `store.js:126` setInterval 不清理 + `window.__xxx` 全局函数收口（可并入千行 JS 拆分）
- [ ] 测试盲区：异常路径集成测试、task_state 并发、upload→import→analytics 端到端链

---

## 建议节奏

本周 P0 两项 → 之后 P1 逐项穿插 → 重构窗口进 P2 → 服务器侧有空时 P3。
