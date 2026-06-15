"""cron 失败告警 service 测试 (spec 2026-06-10-cron-failure-alert)。"""

from datetime import date

from sqlalchemy import insert

from app.repositories import stockpile_db


def _add_backtest_run(model_name, view, created_at):
    from app.models import BacktestRun

    with stockpile_db._session() as s:
        s.execute(
            insert(BacktestRun).values(
                model_name=model_name,
                view=view,
                created_at=created_at,
                window_train=13,
                window_test=4,
                min_weeks=20,
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
        [
            _ALERT,
            {"kind": "backtest_run", "days_since": 9, "message": "回测 run 超期 9 天 (阈值 8)"},
        ],
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


# ---- _forecast_routing_degraded: RL-11 垄断 + wholesale 腿归零 ----


def _add_forecast_rows(sku_type, n, start=0):
    from app.models import ForecastOutput

    with stockpile_db._session() as s:
        for i in range(n):
            s.execute(
                insert(ForecastOutput).values(
                    product_barcode=f"{sku_type}-{start + i}",
                    model_used="EmpiricalQuantile",
                    sku_type=sku_type,
                    n_weeks_history=10,
                    mu=1.0,
                    sigma=1.0,
                    p50=1.0,
                    p98=2.0,
                    computed_at="2026-06-09 03:00:00",
                )
            )
        s.commit()


def test_routing_baseline_98pct_not_flagged():
    # ADR-0002 实施验证基线: retail ~98% (6170/74/49) 是健康结构, 不该报。
    # 旧阈值 0.97 会在此误报 (本次修复的回归守护)。
    from app.services import alerts

    _add_forecast_rows("retail_dominant", 196)
    _add_forecast_rows("wholesale_only", 2)
    _add_forecast_rows("mixed", 2)
    with stockpile_db._session() as s:
        assert alerts._forecast_routing_degraded(s) == []


def test_routing_wholesale_leg_zero_flagged():
    # ADR D5.2 真正担心的故障: wholesale(CrostonSBA) 腿断 → forecast_output 里归零。
    # retail 98% < 0.99 不触发垄断, 由专门的归零探针抓。
    from app.services import alerts

    _add_forecast_rows("retail_dominant", 196)
    _add_forecast_rows("mixed", 4)
    with stockpile_db._session() as s:
        msgs = alerts._forecast_routing_degraded(s)
    assert any("wholesale" in m for m in msgs)


def test_routing_true_monopoly_flagged():
    # 单一类型 > 99% (分类全面塌方把 SKU 全甩进 retail) 仍要报。
    from app.services import alerts

    _add_forecast_rows("retail_dominant", 199)
    _add_forecast_rows("wholesale_only", 1)  # wholesale 非空 → 只触发垄断, 不触发归零
    with stockpile_db._session() as s:
        msgs = alerts._forecast_routing_degraded(s)
    assert any("垄断" in m for m in msgs)
    assert not any("归零" in m for m in msgs)


def test_routing_small_sample_silent():
    # < _MONOPOLY_MIN_ROWS: 测试/冷启动期不谈垄断, 也不谈腿归零。
    from app.services import alerts

    _add_forecast_rows("retail_dominant", 10)
    with stockpile_db._session() as s:
        assert alerts._forecast_routing_degraded(s) == []


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
