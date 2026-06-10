# cron 失败告警（Telegram）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 服务端每日巡检三类数据超期并经 Telegram 推送（每日最多一条汇总）；scraper 本地周任务失败即时直报；cron 容器自身死亡为 v1 已接受的残余风险。

**Architecture:** 新增 `app/services/alerts.py`（三个巡检探针 + 汇总 + TG 发送 + 每日限频），经 `POST /analytics/alerts/check`（`@require_upload_token`）暴露，由 forecast-cron 容器每天 07:30 Athens curl。`run_weekly.ps1` catch 块加最小 TG 直报。spec: `docs/superpowers/specs/2026-06-10-cron-failure-alert-design.md`（已批准）。

**Tech Stack:** Flask + SQLAlchemy（现有）、urllib.request（TG API，不引新依赖）、pytest（tmp sqlite，conftest 隔离）、PowerShell（scraper 侧）。

**约定**（执行者必读）：
- 仓库测试全跑 sqlite，但生产是 PG —— 含 SQL 的新代码合并前必须按 Task 8 在本地 PG 镜像实跑。
- `created_at` / `computed_at` 都是 Text 时间戳（`CURRENT_TIMESTAMP` 格式 `YYYY-MM-DD HH:MM:SS`），解析统一用 `app.services.analytics._shared._parse_date`（取前 10 字符）。
- TG 凭据 `TG_BOT_TOKEN` / `TG_CHAT_ID`：web 容器走 Coolify env；scraper 走 `scraper/.env`。**绝不进仓库、绝不进日志/消息体。**

---

### Task 1: freshness 抓取阈值常量公开化

**Files:**
- Modify: `app/services/analytics/freshness.py:19`（`_SCRAPE_STALE_DAYS` → 公开名）
- Test: 无新测试（纯改名，现有 freshness 测试守护行为）

- [ ] **Step 1: 改名 + 保留语义注释**

`app/services/analytics/freshness.py` 把：

```python
_SCRAPE_STALE_DAYS = 8
```

改为：

```python
# 公开常量: alerts 巡检与红条必须同口径 (review: 阈值不允许两处漂移)
SCRAPE_STALE_DAYS = 8
```

并把本文件内唯一使用处 `scrape_days_since > _SCRAPE_STALE_DAYS` 改为 `scrape_days_since > SCRAPE_STALE_DAYS`。

- [ ] **Step 2: 确认无其他引用 + 全量相关测试过**

Run: `grep -rn "_SCRAPE_STALE_DAYS" app/ tests/` → 期望无结果；
Run: `pytest tests/ -q -k freshness` → 期望 PASS。

- [ ] **Step 3: Commit**

```bash
git add app/services/analytics/freshness.py
git commit -m "refactor(freshness): SCRAPE_STALE_DAYS 公开化, alerts 与红条共用同一阈值"
```

### Task 2: forecast_eval 公开生产 run 访问器

**Files:**
- Modify: `app/services/forecast_eval.py`（`_latest_run` 定义后，约 line 152 后插入）
- Test: `tests/test_alerts_service.py`（新建，先放这一个测试）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_alerts_service.py`：

```python
"""cron 失败告警 service 测试 (spec 2026-06-10-cron-failure-alert)。"""

from datetime import date

from sqlalchemy import insert

from app.repositories import stockpile_db


def _add_backtest_run(model_name, view, created_at):
    from app.models import BacktestRun

    with stockpile_db._session() as s:
        s.execute(
            insert(BacktestRun).values(
                model_name=model_name, view=view, created_at=created_at
            )
        )
        s.commit()


def test_production_run_created_at_picks_prod_model_only():
    # 生产口径 = EmpiricalQuantile/base_demand; 其它 model 的更新 run 不能顶上来
    from app.services.forecast_eval import production_run_created_at

    _add_backtest_run("EmpiricalQuantile", "base_demand", "2026-06-01 01:00:00")
    _add_backtest_run("CrostonSBA", "base_demand", "2026-06-09 01:00:00")
    with stockpile_db._session() as s:
        assert production_run_created_at(s) == "2026-06-01 01:00:00"


def test_production_run_created_at_none_when_no_run():
    from app.services.forecast_eval import production_run_created_at

    with stockpile_db._session() as s:
        assert production_run_created_at(s) is None
```

注意：`BacktestRun` 若有其它 NOT NULL 列（执行时打开 `app/models.py` 的 BacktestRun 定义核对），在 `insert().values()` 里补上最小合法值。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_alerts_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'production_run_created_at'`

- [ ] **Step 3: 实现**

`app/services/forecast_eval.py` 在 `_latest_run` 函数之后加：

```python
def production_run_created_at(session) -> str | None:
    """最新生产口径 backtest run 的 created_at; 无则 None。

    生产口径 = (_PROD_MODEL, _PROD_VIEW), 与预测效果看板同源。
    供 alerts 巡检用 — 不要绕过本函数去取全表 max(id) (会把 baseline
    比较 run 误判成生产 run)。
    """
    run = _latest_run(session, _PROD_MODEL, _PROD_VIEW)
    return run.created_at if run else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_alerts_service.py -q` → Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/forecast_eval.py tests/test_alerts_service.py
git commit -m "feat(alerts): forecast_eval 公开 production_run_created_at(生产口径单源)"
```

### Task 3: alerts.py 巡检探针 + collect_alerts

**Files:**
- Create: `app/services/alerts.py`
- Test: `tests/test_alerts_service.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 tests/test_alerts_service.py）**

```python
def _set_heartbeat(value):
    from app.models import SystemSetting

    with stockpile_db._session() as s:
        s.add(SystemSetting(key="scrape:last_success_at", value=value, updated_by="t"))
        s.commit()


def _add_forecast_row(computed_at):
    from app.models import ForecastOutput

    with stockpile_db._session() as s:
        s.execute(
            insert(ForecastOutput).values(
                product_barcode="B1",
                model_used="EmpiricalQuantile",
                sku_type="retail_dominant",
                n_weeks_history=10,
                mu=1.0,
                sigma=1.0,
                p50=1.0,
                p98=2.0,
                computed_at=computed_at,
            )
        )
        s.commit()


# ---- collect_alerts: 三类探针 ----


def test_collect_alerts_all_healthy_returns_empty():
    from app.services import alerts

    _set_heartbeat("2026-06-08T12:00:00+00:00")
    _add_forecast_row("2026-06-09 03:00:00")
    _add_backtest_run("EmpiricalQuantile", "base_demand", "2026-06-07 01:00:00")
    with stockpile_db._session() as s:
        assert alerts.collect_alerts(s, as_of=date(2026, 6, 10)) == []


def test_collect_alerts_scrape_stale_over_8_days():
    from app.services import alerts

    _set_heartbeat("2026-06-01T12:00:00+00:00")  # 9 天前
    _add_forecast_row("2026-06-09 03:00:00")
    _add_backtest_run("EmpiricalQuantile", "base_demand", "2026-06-07 01:00:00")
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert [a["kind"] for a in out] == ["scrape_heartbeat"]
    assert out[0]["days_since"] == 9


def test_collect_alerts_no_heartbeat_record_is_silent():
    # 冷启动(从未有心跳)不误报, 与 freshness 行为一致 (spec §2)
    from app.services import alerts

    _add_forecast_row("2026-06-09 03:00:00")
    _add_backtest_run("EmpiricalQuantile", "base_demand", "2026-06-07 01:00:00")
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert out == []


def test_collect_alerts_forecast_stale_and_empty_table():
    from app.services import alerts

    _set_heartbeat("2026-06-08T12:00:00+00:00")
    _add_backtest_run("EmpiricalQuantile", "base_demand", "2026-06-07 01:00:00")
    # 表空 → 报
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert [a["kind"] for a in out] == ["forecast_output"]
    # 超 2 天 → 报
    _add_forecast_row("2026-06-07 03:00:00")  # 3 天前
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert [a["kind"] for a in out] == ["forecast_output"]
    assert out[0]["days_since"] == 3


def test_collect_alerts_backtest_stale_and_missing():
    from app.services import alerts

    _set_heartbeat("2026-06-08T12:00:00+00:00")
    _add_forecast_row("2026-06-09 03:00:00")
    # 无 run → 报
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert [a["kind"] for a in out] == ["backtest_run"]
    # 超 8 天 → 报
    _add_backtest_run("EmpiricalQuantile", "base_demand", "2026-06-01 01:00:00")
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert [a["kind"] for a in out] == ["backtest_run"]
    assert out[0]["days_since"] == 9


def test_collect_alerts_aggregates_all_current_anomalies():
    # review: 消息必须聚合全部异常, 不能只报第一个
    from app.services import alerts

    _set_heartbeat("2026-05-20T12:00:00+00:00")
    with stockpile_db._session() as s:
        out = alerts.collect_alerts(s, as_of=date(2026, 6, 10))
    assert {a["kind"] for a in out} == {"scrape_heartbeat", "forecast_output", "backtest_run"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_alerts_service.py -q`
Expected: 新增用例全 FAIL —— `ModuleNotFoundError: No module named 'app.services.alerts'`（Task 2 的 2 个仍 PASS）

- [ ] **Step 3: 实现 app/services/alerts.py**

```python
"""cron 失败告警: 服务端每日巡检 + Telegram 推送。

spec: docs/superpowers/specs/2026-06-10-cron-failure-alert-design.md (已批准)。
覆盖边界: 巡检覆盖数据超期; cron 容器自身死亡 v1 不保证告警 (残余风险§1)。
判定全部集中在本模块, 可单测; 阈值常量不散在函数里。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.services.analytics._shared import _parse_date, _today
from app.services.analytics.freshness import HEARTBEAT_KEY, SCRAPE_STALE_DAYS

logger = logging.getLogger(__name__)

# forecast/refresh 是日任务(03:00) → 2 天 = 容一次失败再报
FORECAST_STALE_DAYS = 2
# backtest/refresh 是周任务(周日 01:00) → 8 天 = 容一次失败再报
BACKTEST_STALE_DAYS = 8
# 每日限频: 仅实际发送成功时写当天日期
LAST_SENT_KEY = "alerts:last_sent_date"


def _heartbeat_days_since(session, as_of: date) -> int | None:
    """距上次抓取成功心跳的天数; 从未有心跳 → None (冷启动不报, 同 freshness)。"""
    from app.models import SystemSetting

    row = session.get(SystemSetting, HEARTBEAT_KEY)
    if row is None or not row.value:
        return None
    return (as_of - _parse_date(row.value)).days


def _forecast_days_since(session, as_of: date) -> int | None:
    """距最新 forecast_output.computed_at 的天数; 表空 → None。"""
    from sqlalchemy import func, select

    from app.models import ForecastOutput

    val = session.execute(select(func.max(ForecastOutput.computed_at))).scalar()
    return (as_of - _parse_date(str(val))).days if val else None


def _backtest_days_since(session, as_of: date) -> int | None:
    """距最新生产口径 backtest run 的天数; 无 run → None。"""
    from app.services.forecast_eval import production_run_created_at

    val = production_run_created_at(session)
    return (as_of - _parse_date(str(val))).days if val else None


def collect_alerts(session, as_of: date) -> list[dict[str, Any]]:
    """三类巡检 (spec §2), 返回当前全部异常 (聚合, 不止报第一个)。

    心跳: 从未有记录不报 (冷启动); forecast/backtest: 空也要报 (生产必须有)。
    """
    out: list[dict[str, Any]] = []

    hb = _heartbeat_days_since(session, as_of)
    if hb is not None and hb > SCRAPE_STALE_DAYS:
        out.append(
            {
                "kind": "scrape_heartbeat",
                "days_since": hb,
                "message": f"抓取心跳超期 {hb} 天 (阈值 {SCRAPE_STALE_DAYS})",
            }
        )

    fc = _forecast_days_since(session, as_of)
    if fc is None:
        out.append(
            {"kind": "forecast_output", "days_since": None, "message": "forecast_output 为空"}
        )
    elif fc > FORECAST_STALE_DAYS:
        out.append(
            {
                "kind": "forecast_output",
                "days_since": fc,
                "message": f"预测快照超期 {fc} 天 (阈值 {FORECAST_STALE_DAYS})",
            }
        )

    bt = _backtest_days_since(session, as_of)
    if bt is None:
        out.append(
            {"kind": "backtest_run", "days_since": None, "message": "无生产口径 backtest run"}
        )
    elif bt > BACKTEST_STALE_DAYS:
        out.append(
            {
                "kind": "backtest_run",
                "days_since": bt,
                "message": f"回测 run 超期 {bt} 天 (阈值 {BACKTEST_STALE_DAYS})",
            }
        )

    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_alerts_service.py -q` → Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/alerts.py tests/test_alerts_service.py
git commit -m "feat(alerts): 三类巡检探针 + collect_alerts(聚合全部异常)"
```

### Task 4: TG 发送 + run_alerts_check 编排（限频/未配置）

**Files:**
- Modify: `app/services/alerts.py`（追加）
- Test: `tests/test_alerts_service.py`（追加）

- [ ] **Step 1: 写失败测试（追加）**

```python
# ---- run_alerts_check 编排: 限频 / 未配置 / 消息体安全 ----


def _patch_probes(monkeypatch, alerts_list):
    from app.services import alerts

    monkeypatch.setattr(alerts, "collect_alerts", lambda s, as_of: list(alerts_list))


def _set_tg_env(monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "tok123secret")
    monkeypatch.setenv("TG_CHAT_ID", "42")


_ALERT = {"kind": "forecast_output", "days_since": 3, "message": "预测快照超期 3 天 (阈值 2)"}


def test_check_not_configured_returns_ok_false(monkeypatch):
    from app.services import alerts

    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    _patch_probes(monkeypatch, [_ALERT])
    out = alerts.run_alerts_check(as_of=date(2026, 6, 10))
    assert out["ok"] is False
    assert out["msg"] == "telegram_not_configured"
    assert out["alerts"] == [_ALERT]  # 不因未配置而装健康
    assert out["sent"] is False


def test_check_healthy_sends_nothing(monkeypatch):
    from app.services import alerts

    _set_tg_env(monkeypatch)
    _patch_probes(monkeypatch, [])
    calls = []
    monkeypatch.setattr(alerts, "_send_telegram", lambda t: calls.append(t) or (True, None))
    out = alerts.run_alerts_check(as_of=date(2026, 6, 10))
    assert out == {"ok": True, "alerts": [], "sent": False, "suppressed_reason": None}
    assert calls == []  # 安静即健康


def test_check_sends_aggregated_message_and_records_date(monkeypatch):
    from app.models import SystemSetting
    from app.services import alerts

    _set_tg_env(monkeypatch)
    _patch_probes(
        monkeypatch,
        [_ALERT, {"kind": "backtest_run", "days_since": 9, "message": "回测 run 超期 9 天 (阈值 8)"}],
    )
    sent_texts = []
    monkeypatch.setattr(alerts, "_send_telegram", lambda t: sent_texts.append(t) or (True, None))
    out = alerts.run_alerts_check(as_of=date(2026, 6, 10))
    assert out["ok"] is True
    assert out["sent"] is True
    assert len(sent_texts) == 1
    # 聚合: 两条异常都在同一条消息里
    assert "预测快照超期" in sent_texts[0] and "回测 run 超期" in sent_texts[0]
    # 消息体安全: 不含 token (review: 不放 SQL/traceback/token)
    assert "tok123secret" not in sent_texts[0]
    with stockpile_db._session() as s:
        assert s.get(SystemSetting, alerts.LAST_SENT_KEY).value == "2026-06-10"


def test_check_same_day_second_call_suppressed_but_reports_alerts(monkeypatch):
    from app.services import alerts

    _set_tg_env(monkeypatch)
    _patch_probes(monkeypatch, [_ALERT])
    monkeypatch.setattr(alerts, "_send_telegram", lambda t: (True, None))
    alerts.run_alerts_check(as_of=date(2026, 6, 10))  # 第一次: 发送+记日期
    out = alerts.run_alerts_check(as_of=date(2026, 6, 10))  # 同日第二次
    assert out["sent"] is False
    assert out["suppressed_reason"] == "already_sent_today"
    assert out["alerts"] == [_ALERT]  # JSON 照实返回 (review 非阻断项)


def test_check_send_failure_does_not_record_date(monkeypatch):
    from app.models import SystemSetting
    from app.services import alerts

    _set_tg_env(monkeypatch)
    _patch_probes(monkeypatch, [_ALERT])
    monkeypatch.setattr(alerts, "_send_telegram", lambda t: (False, "http 500"))
    out = alerts.run_alerts_check(as_of=date(2026, 6, 10))
    assert out["sent"] is False
    assert out["suppressed_reason"] == "send_failed: http 500"
    with stockpile_db._session() as s:
        assert s.get(SystemSetting, alerts.LAST_SENT_KEY) is None  # 没发出去不算发过


def test_send_telegram_posts_to_api(monkeypatch):
    from app.services import alerts

    captured = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setenv("TG_BOT_TOKEN", "tok123secret")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    ok, err = alerts._send_telegram("hello")
    assert ok is True and err is None
    assert "api.telegram.org/bottok123secret/sendMessage" in captured["url"]
    assert b"chat_id=42" in captured["data"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_alerts_service.py -q`
Expected: 新增用例 FAIL — `AttributeError: ... has no attribute 'run_alerts_check'`

- [ ] **Step 3: 实现（追加到 app/services/alerts.py）**

文件头部 import 区追加：

```python
import os
import urllib.parse
import urllib.request
```

文件尾部追加：

```python
def _send_telegram(text: str) -> tuple[bool, str | None]:
    """发送 TG 消息。返回 (ok, err)。凭据/异常细节只进服务端日志, 不进返回值正文。"""
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, None
            return False, f"http {resp.status}"
    except Exception as exc:  # noqa: BLE001 — 告警发送失败不能炸掉巡检本身
        logger.warning("telegram send failed: %s", exc)
        return False, type(exc).__name__


def _tg_configured() -> bool:
    return bool(os.environ.get("TG_BOT_TOKEN")) and bool(os.environ.get("TG_CHAT_ID"))


def run_alerts_check(as_of: date | None = None) -> dict[str, Any]:
    """巡检 + 发送编排 (spec §1/§3)。

    返回 {ok, alerts, sent, suppressed_reason}; TG 未配置 → ok=False +
    msg=telegram_not_configured (不假装成功, 但 alerts 照实返回)。
    每日最多一条汇总; 同日二次 sent=False/already_sent_today 但 alerts 照返;
    发送失败不写 last_sent_date (明天还有机会报)。恢复正常不发。
    """
    from app.models import SystemSetting
    from app.repositories import stockpile_db

    as_of = as_of or _today()
    with stockpile_db._session() as session:
        found = collect_alerts(session, as_of)

        if not _tg_configured():
            return {
                "ok": False,
                "msg": "telegram_not_configured",
                "alerts": found,
                "sent": False,
                "suppressed_reason": None,
            }

        if not found:
            return {"ok": True, "alerts": found, "sent": False, "suppressed_reason": None}

        last = session.get(SystemSetting, LAST_SENT_KEY)
        if last is not None and last.value == as_of.isoformat():
            return {
                "ok": True,
                "alerts": found,
                "sent": False,
                "suppressed_reason": "already_sent_today",
            }

        lines = [f"⚠ label-sync 巡检 {as_of.isoformat()}"] + [
            f"- {a['message']}" for a in found
        ]
        ok, err = _send_telegram("\n".join(lines))
        if not ok:
            return {
                "ok": True,
                "alerts": found,
                "sent": False,
                "suppressed_reason": f"send_failed: {err}",
            }

        if last is not None:
            last.value = as_of.isoformat()
            last.updated_by = "alerts"
        else:
            session.add(
                SystemSetting(key=LAST_SENT_KEY, value=as_of.isoformat(), updated_by="alerts")
            )
        session.commit()
        return {"ok": True, "alerts": found, "sent": True, "suppressed_reason": None}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_alerts_service.py -q` → Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/alerts.py tests/test_alerts_service.py
git commit -m "feat(alerts): TG 发送 + run_alerts_check(每日限频/未配置不装成功/发送失败不记日期)"
```

### Task 5: 路由 POST /analytics/alerts/check + 鉴权契约测试

**Files:**
- Modify: `app/routes/analytics.py`（`scrape_heartbeat` 路由之后插入）
- Test: `tests/test_cron_alerts_auth.py`（新建，镜像 `tests/test_cron_forecast_auth.py` 模式）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_cron_alerts_auth.py`：

```python
"""alerts/check 鉴权契约 (镜像 test_cron_forecast_auth.py 的 4 态矩阵)。

无 token → 302 /login; 错 token → 401; 缺 env 且带 token → 500; 正确 token → 200。
"""

import os
from unittest.mock import patch

from server import create_app


def _client():
    app = create_app(seed_auth=False, prewarm=False)
    app.config["TESTING"] = True
    return app.test_client()


def test_alerts_check_without_token_redirected_to_login():
    resp = _client().post("/analytics/alerts/check")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_alerts_check_wrong_token_401():
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().post(
            "/analytics/alerts/check", headers={"X-Upload-Token": "wrong"}
        )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)
    assert resp.status_code == 401


def test_alerts_check_token_present_but_server_unconfigured_500():
    os.environ.pop("UPLOAD_TOKEN", None)
    resp = _client().post(
        "/analytics/alerts/check", headers={"X-Upload-Token": "whatever"}
    )
    assert resp.status_code == 500


def test_alerts_check_correct_token_200_shape():
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    payload = {"ok": True, "alerts": [], "sent": False, "suppressed_reason": None}
    try:
        with patch("app.services.alerts.run_alerts_check", return_value=payload) as m:
            resp = _client().post(
                "/analytics/alerts/check", headers={"X-Upload-Token": "secret_token_abc"}
            )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"ok", "alerts", "sent", "suppressed_reason"}
    m.assert_called_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_cron_alerts_auth.py -q`
Expected: 4 个全 FAIL（无 token 测试得到 404 而非 302——路由不存在）

- [ ] **Step 3: 实现路由（app/routes/analytics.py，scrape_heartbeat 之后）**

```python
@bp.post("/alerts/check")
@require_upload_token
def alerts_check():
    """cron 失败告警巡检 (spec 2026-06-10): 巡检三类数据超期 + TG 推送。

    供 forecast-cron 每天 07:30 curl; 判定/限频/发送全在 services/alerts.py。
    """
    from app.services.alerts import run_alerts_check

    return jsonify(run_alerts_check())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_cron_alerts_auth.py tests/test_alerts_service.py -q` → Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/analytics.py tests/test_cron_alerts_auth.py
git commit -m "feat(alerts): POST /analytics/alerts/check 路由(@require_upload_token)+4态鉴权契约测试"
```

### Task 6: forecast-cron 容器加巡检 crontab 行

**Files:**
- Modify: `docker-compose.yml`（cron service 的 command 块，backtest 行之后）

- [ ] **Step 1: 加 crontab 行**

在 `echo "0 1 * * 0 ... backtest/refresh ..."` 行之后、`echo "[cron] installed: ..."` 之前插入（**沿用既有写法：`$$UPLOAD_TOKEN` 在启动 shell 写 crontab 时展开烤进任务行，crond 不继承容器环境变量**）：

```yaml
        # 每天 07:30 巡检告警 (03:00 forecast 之后): 数据超期 → TG 推送 (spec 2026-06-10)
        echo "30 7 * * * curl -fsS -X POST -H \"X-Upload-Token: $$UPLOAD_TOKEN\" http://label-sync:5000/analytics/alerts/check >> /proc/1/fd/1 2>&1" >> /etc/crontabs/root
```

并把下一行的安装日志改为：

```yaml
        echo "[cron] installed: daily 03:00 forecast/refresh + Sun 01:00 backtest/refresh + daily 07:30 alerts/check, Athens (authed)"
```

- [ ] **Step 2: 校验 compose 语法**

Run（git-bash）: `docker compose -f docker-compose.yml config > /dev/null; echo exit=$?`
Expected: `exit=0`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(alerts): forecast-cron 每天 07:30 巡检 alerts/check(token 烤入 crontab 行)"
```

### Task 7: run_weekly.ps1 失败直报（A-min）

**Files:**
- Modify: `scraper/run_weekly.ps1`（`Read-EnvVar` 函数后加 `Send-TgAlert` + 阶段跟踪 + catch 块调用）

- [ ] **Step 1: 加 Send-TgAlert 函数（Read-EnvVar 函数之后）**

```powershell
function Send-TgAlert {
    # 失败直报 (spec 2026-06-10 A-min)。TG 未配置 → 只写本地 log, 绝不让告警
    # 自己 throw 反过来弄死收尾; 消息只含阶段名+简短错误, 不含命令行/token。
    param([string]$Text)
    $tgToken = $null; $tgChat = $null
    try {
        $tgToken = Read-EnvVar "TG_BOT_TOKEN"
        $tgChat  = Read-EnvVar "TG_CHAT_ID"
    } catch {
        Log "TG 未配置, 跳过失败通知"
        return
    }
    try {
        curl.exe --silent --show-error --max-time 30 -X POST `
            "https://api.telegram.org/bot$tgToken/sendMessage" `
            --data-urlencode "chat_id=$tgChat" `
            --data-urlencode "text=$Text" | Out-Null
        Log "已发送 TG 失败通知"
    } catch {
        Log "TG 通知发送失败: $($_.Exception.Message)"
    }
}
```

- [ ] **Step 2: 阶段跟踪**

`$ts = Get-Date -Format "yyyyMMdd-HHmmss"` 行之前加：

```powershell
$script:stage = "init"
```

`Run-Step` 函数体内 `param(...)` 之后第一行加：

```powershell
    $script:stage = $Name
```

`Invoke-Refresh` 函数体内 `param(...)` 之后第一行加：

```powershell
    $script:stage = "refresh:$Name"
```

- [ ] **Step 3: catch 块加直报（保持现有日志行为，在 `exit 1` 之前）**

把现有 catch 块：

```powershell
catch {
    Log "!!! 失败: $_"
    Log "!!! 完整 trace:"
    Log ($_ | Out-String)
    exit 1
}
```

改为：

```powershell
catch {
    Log "!!! 失败: $_"
    Log "!!! 完整 trace:"
    Log ($_ | Out-String)
    # 只发阶段名+截断摘要 (spec: 不发完整命令/trace/token)
    $brief = "$($_.Exception.Message)"
    if ($brief.Length -gt 200) { $brief = $brief.Substring(0, 200) + "..." }
    Send-TgAlert "scraper 周任务失败：$($script:stage)`n$brief"
    exit 1
}
```

- [ ] **Step 4: 语法校验（无 PowerShell 单测设施，静态解析即验证）**

Run（PowerShell）:

```powershell
$errs = $null
[void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "scraper/run_weekly.ps1"), [ref]$null, [ref]$errs)
$errs.Count
```

Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add scraper/run_weekly.ps1
git commit -m "feat(alerts): run_weekly 失败直报 TG(阶段名+截断摘要, 未配置只写log)"
```

### Task 8: 全量验证 + PG 镜像实跑 + 真发一条

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -q`
Expected: 全 PASS（基线 1176 passed + 2 skipped 之上新增 ~17 个）

- [ ] **Step 2: 判定 SQL 在 PG 镜像实跑（sqlite/PG 差异教训，必做）**

Run（worktree 根目录，git-bash）:

```bash
DATABASE_URL='postgresql+psycopg://dev:devpass@localhost:5433/label_sync' python -c "
from datetime import date
from app.repositories import stockpile_db
from app.services.alerts import collect_alerts
with stockpile_db._session() as s:
    print(collect_alerts(s, as_of=date.today()))
"
```

Expected: 不抛异常，输出当前镜像数据的真实判定（镜像数据新鲜则 `[]`）。

- [ ] **Step 3: 端到端真发一条（需要用户配合提供 TG 凭据）**

本地起 server（设 `TG_BOT_TOKEN`/`TG_CHAT_ID`/`UPLOAD_TOKEN`/`FLASK_SECRET_KEY` env），
`curl -X POST -H "X-Upload-Token: <token>" http://127.0.0.1:5000/analytics/alerts/check`，
确认 JSON shape + 手机收到消息（可临时把 `FORECAST_STALE_DAYS` 改 0 制造异常，测完改回）。

- [ ] **Step 4: 汇报 + 部署侧待办（代码外）**

告知用户：Coolify 给 **web 容器**加 `TG_BOT_TOKEN`/`TG_CHAT_ID` env；本地 `scraper/.env` 加同名两行；合并部署后次日 07:30 起生效。

---

## Self-Review 记录

- spec 覆盖：§1 路由（Task 5）、§2 三巡检（Task 3）、§3 发送规则（Task 4）、§4 cron 接线（Task 6）、§5 A-min（Task 7）、测试章（Task 2-5 + Task 8 PG 实跑/真发）✓
- 无占位符；跨任务命名一致（`run_alerts_check` / `_send_telegram` / `LAST_SENT_KEY` / `production_run_created_at` 各处同名）✓
- 残余风险（cron 容器死亡）不需要代码，spec 已记录 ✓
