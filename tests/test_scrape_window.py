"""scraper/scrape_window.py 单元测试 (固定 today, 不依赖系统时钟)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from scraper.scrape_window import parse_window, run_check, weekly_violation

TODAY = date(2026, 6, 8)


class TestParseWindow:
    def test_events_ok(self):
        assert parse_window("events_sale_2026-06-01_2026-06-08.parquet") == (
            "events",
            date(2026, 6, 1),
            date(2026, 6, 8),
        )

    def test_events_purchase_ok(self):
        kind, s, e = parse_window("events_purchase_2020-01-01_2023-12-31.parquet")
        assert kind == "events"
        assert s == date(2020, 1, 1)
        assert e == date(2023, 12, 31)

    def test_snapshot_ok(self):
        assert parse_window("inventory_snapshot_2026-06-08.parquet") == (
            "snapshot",
            date(2026, 6, 8),
            date(2026, 6, 8),
        )

    def test_master_ok(self):
        assert parse_window("product_master_2026-06-08.parquet") == (
            "master",
            date(2026, 6, 8),
            date(2026, 6, 8),
        )

    def test_events_bad_date_keeps_kind_none_dates(self):
        assert parse_window("events_sale_xx_yy.parquet") == ("events", None, None)

    def test_events_invalid_calendar_date(self):
        assert parse_window("events_sale_2026-13-99_2026-06-08.parquet") == (
            "events",
            None,
            None,
        )

    def test_unrelated_file_is_unknown(self):
        assert parse_window("README.md") == ("unknown", None, None)
        assert parse_window("foo.parquet") == ("unknown", None, None)


class TestWeeklyViolation:
    def test_current_week_events_ok(self):
        assert weekly_violation("events_sale_2026-06-01_2026-06-08.parquet", TODAY) is None

    def test_span_too_wide_rejected(self):
        reason = weekly_violation("events_sale_2015-01-01_2023-01-02.parquet", TODAY)
        assert reason is not None
        assert "跨度" in reason

    def test_old_start_short_span_rejected(self):
        reason = weekly_violation("events_sale_2026-05-01_2026-05-08.parquet", TODAY)
        assert reason is not None
        assert "太旧" in reason

    def test_stale_snapshot_rejected(self):
        reason = weekly_violation("inventory_snapshot_2023-01-02.parquet", TODAY)
        assert reason is not None

    def test_current_snapshot_ok(self):
        assert weekly_violation("inventory_snapshot_2026-06-08.parquet", TODAY) is None

    def test_master_any_date_ok(self):
        assert weekly_violation("product_master_2026-06-08.parquet", TODAY) is None
        assert weekly_violation("product_master_2020-01-01.parquet", TODAY) is None

    def test_bad_named_target_rejected(self):
        reason = weekly_violation("events_sale_xx_yy.parquet", TODAY)
        assert reason is not None
        assert "解析" in reason

    def test_unrelated_file_passes(self):
        assert weekly_violation("README.md", TODAY) is None

    def test_boundary_span_exactly_14_ok(self):
        assert weekly_violation("events_sale_2026-05-25_2026-06-08.parquet", TODAY) is None


def _write_parquet(path, n=10):
    # 造一个最小合法 parquet (内容无所谓, 护栏只看文件名)
    pd.DataFrame({"x": list(range(n))}).to_parquet(path, index=False)


class TestRunCheck:
    def test_all_compliant_returns_0(self, tmp_path):
        _write_parquet(tmp_path / "events_sale_2026-06-01_2026-06-08.parquet")
        _write_parquet(tmp_path / "inventory_snapshot_2026-06-08.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=False)
        assert rc == 0

    def test_historical_file_returns_1(self, tmp_path, capsys):
        _write_parquet(tmp_path / "events_sale_2015-01-01_2023-01-02.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=False)
        assert rc == 1
        out = capsys.readouterr().out
        assert "events_sale_2015-01-01_2023-01-02.parquet" in out

    def test_allow_backfill_passes_history(self, tmp_path):
        _write_parquet(tmp_path / "events_sale_2015-01-01_2023-01-02.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=True)
        assert rc == 0

    def test_total_size_over_limit_returns_1(self, tmp_path):
        _write_parquet(tmp_path / "events_sale_2026-06-01_2026-06-08.parquet")
        rc = run_check(str(tmp_path), TODAY, max_total_mb=0.0001, allow_backfill=False)
        assert rc == 1

    def test_manifest_lists_master_by_kind(self, tmp_path, capsys):
        _write_parquet(tmp_path / "product_master_2026-06-08.parquet")
        run_check(str(tmp_path), TODAY, max_total_mb=50.0, allow_backfill=False)
        out = capsys.readouterr().out
        assert "[master]" in out
        assert "product_master_2026-06-08.parquet" in out
