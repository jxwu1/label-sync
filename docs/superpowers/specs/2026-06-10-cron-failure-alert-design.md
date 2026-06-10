# cron 失败告警（Telegram）设计稿

- **日期**: 2026-06-10
- **状态**: 已批准（2026-06-10，两轮 review 后）
- **来源**: engineering-backlog P0「cron 失败告警接通」；2026-06-06-scrape-failure-alert-design.md 的告警渠道升级（红条 → 主动推送）

## 结论（先说清楚覆盖边界）

服务端巡检覆盖**数据超期**；scraper catch 覆盖**本地周任务即时失败**；**cron 容器自身死亡 v1 不保证 TG 告警**，只能通过工作台/外部监控发现。

## 背景与问题

现状告警只有 index.html 顶部红条（被动，要开页面才看到）：

- scraper 周一失败 → heartbeat 不写 → 第 8 天红条才亮，期间盲飞
- forecast-cron 容器里的 daily forecast/refresh、weekly backtest/refresh 失败**完全无判定**，只留 docker logs
- `forecast-cron` 在 docker-compose.yml 是独立 service（注释明确 cron 重启不影响 web）——它单独死时 web 还活着，任何「服务端巡检」都不会被触发

## 方案：B（服务端每日巡检）+ A-min（scraper catch 直报）

### 1. 服务端新增 `POST /analytics/alerts/check`

- `@require_upload_token`（与 forecast/refresh 同机器鉴权模式）
- 只做两件事：巡检 + 发 TG；判定逻辑集中在 Python service（可单测）
- 返回 JSON：`{ok, alerts: [...], sent: bool, suppressed_reason: str|null}`
  - 同日已发过 → `sent=false, suppressed_reason="already_sent_today"`，但 `alerts` **照实返回当前全部异常**（不因抑制而装健康）
  - TG 未配置 → `ok=false, msg="telegram_not_configured"`，**不假装成功**

### 2. 巡检项 v1 只放三类

| 巡检项 | 判定 | 阈值依据 |
|---|---|---|
| scrape heartbeat | `scrape:last_success_at` 距今 > 8 天（无心跳记录时不报，与 freshness 冷启动行为一致） | 与红条 `_SCRAPE_STALE_DAYS=8` 同口径 |
| forecast 新鲜度 | `forecast_output.computed_at` 最新值距今 > 2 天，或表空 | 日任务（03:00），2 天 = 容一次失败 |
| backtest 新鲜度 | 最新**生产口径** backtest run（EmpiricalQuantile / base_demand，等价 `forecast_eval._latest_run(session, _PROD_MODEL, _PROD_VIEW)` 的选取逻辑，**不取全表 max id**）距今 > 8 天，或无 run | 周任务（周日 01:00），8 天 = 容一次失败 |

阈值进模块常量，不散在判定函数里。

### 3. TG 发送规则

- 凭据：`TG_BOT_TOKEN` / `TG_CHAT_ID`，Coolify env 注入（web 容器）；scraper 侧落 `scraper/.env`。**不进仓库**
- 限频：每天最多一条**汇总**消息，消息体聚合当前**所有**异常（避免单日新增故障被「一天一条」压掉信息）；`SystemSetting` 记 `alerts:last_sent_date`（仅实际发送成功时写）
- 恢复正常**不发**——安静即健康
- 消息内容只放状态摘要（哪项超期、距今几天），**不放 SQL / traceback / token / URL query secret**
- 发送失败（TG API 不通）：JSON 返回 `sent=false` + 原因，错误进 web 容器日志

### 4. cron 接线

- forecast-cron 容器 crontab 加一行：每天 07:30 Athens（在 03:00 forecast/refresh 之后，当天早上就能抓到夜里的失败）
- **沿用现有 forecast/backtest 两行 crontab 的写法**：compose 里用 `$$UPLOAD_TOKEN`，在容器启动 shell 写入 `/etc/crontabs/root` 时展开、把 token 烤进任务行——**crond 不继承容器环境变量，不能让 crond 运行期读 `$UPLOAD_TOKEN`**（docker-compose.yml 注释已写明的既有约束）
- 保持 `-fsS`：失败进容器 stdout，Coolify 看日志可查

### 5. A-min：仅 scraper 失败点直报

- `run_weekly.ps1` 的 catch 块发 TG：`scraper 周任务失败：<阶段名>`
- 只发**阶段名、退出码、简短错误**；不发完整命令行、不发 token
- TG 凭据从 `scraper/.env` 读（沿用 UPLOAD_TOKEN 的 Read-EnvVar 机制）；未配置则跳过发送只写本地 log（不让告警缺配置反过来弄死任务收尾）
- forecast-cron **不做**失败点上报——避免第二套 shell 告警逻辑，靠每日巡检兜底

## 残余风险（v1 明确接受）

1. **cron 容器单独死亡**：巡检本身跑在 forecast-cron 里，容器死 = 巡检死 = TG 静默。web 仍活着但无人调 /alerts/check。v1 只能靠工作台红条（最晚 8 天）或人工 `docker ps` 发现。**彻底补洞需外部死人开关**（Healthchecks.io / Uptime Kuma 从外部等 ping），列为 v2 候选
2. **本地 scraper 机器没开机 / Task Scheduler 没触发**：catch 不会执行（根本没跑），靠巡检兜底——时效与现状红条相同，无恶化
3. 巡检为日粒度：故障最晚次日 07:30 才推送

## 测试

- service 层：三类巡检项各自的 超期/空/健康 路径；限频（同日二发抑制但 alerts 照返）；TG 未配置 → ok=false；消息体不含敏感串（断言不含 token）
- route 层（与全局鉴权门的真实行为一致，参照 `test_scrape_heartbeat_without_token_redirected_to_login`）：完全无 X-Upload-Token 的未登录请求 → **302 到 /login**；带错误 token → **401**；服务端缺 UPLOAD_TOKEN env 且请求带 token → **500**；正确 token → **200** + TG mock 下 shape 校验
- TG 发送函数：mock HTTP，不真发
- 实测：本地起 server 真 curl 一次（TG 配真值收到一条）；判定 SQL 在 PG 镜像实跑（吸取 sqlite/PG GROUP BY 教训）

## 不做（YAGNI）

- 邮件/SMS/多渠道抽象
- 恢复通知、告警历史表、告警 UI 页
- forecast-cron 内失败点上报
- 外部死人开关（v2 候选，等需要时再加）
