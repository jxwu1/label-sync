"""cron 失败告警: 服务端每日巡检 + Telegram 推送。

spec: docs/superpowers/specs/2026-06-10-cron-failure-alert-design.md (已批准)。
覆盖边界: 巡检覆盖数据超期; cron 容器自身死亡 v1 不保证告警 (残余风险§1)。
判定全部集中在本模块, 可单测; 阈值常量不散在函数里。
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
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


def _missing_monday_snapshots(session, as_of: date, n_weeks: int = 4) -> list[str]:
    """最近 n_weeks 个已过去的周一中无库存快照的日期（RL-10）。

    无周一快照 → stockout_weeks 对该周返回 unknown → 缺货修正(RL-3)
    对该周静默失效, 必须有信号。
    快照表全空 → 冷启动不报 (同 heartbeat 口径)；as_of 当天是周一不算
    "已过去" (scraper 可能还没跑)。
    """
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models import StockpileInventorySnapshot
    from app.utils.forecast_data import _monday

    total = session.execute(select(func.count(StockpileInventorySnapshot.id))).scalar()
    if not total:
        return []

    this_monday = _monday(as_of)
    start = 0 if as_of > this_monday else 1
    mondays = [this_monday - timedelta(days=7 * i) for i in range(start, start + n_weeks)]
    monday_strs = [m.isoformat() for m in mondays]
    have = {
        r[0]
        for r in session.execute(
            select(StockpileInventorySnapshot.snapshot_date.distinct()).where(
                StockpileInventorySnapshot.snapshot_date.in_(monday_strs)
            )
        )
    }
    return [m for m in monday_strs if m not in have]


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

    missing = _missing_monday_snapshots(session, as_of)
    if missing:
        out.append(
            {
                "kind": "missing_monday_snapshot",
                "days_since": None,
                "message": f"缺周一库存快照: {', '.join(missing)} (削弱缺货修正 RL-10)",
            }
        )

    return out


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

        lines = [f"⚠ label-sync 巡检 {as_of.isoformat()}"] + [f"- {a['message']}" for a in found]
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
