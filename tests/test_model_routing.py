"""模型选择路由测试 — ADR-0002 D1 路由表逐行验收。

seed 全走 SQLAlchemy（PG 腿要过）。日期相对 _AS_OF 构造，保证分类稳定。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models import ForecastOutput, InventoryEvent, Stockpile
from app.repositories import stockpile_db

_AS_OF = dt.date(2026, 6, 8)  # 周一，做窗口末端


def _seed_sales(barcode: str, docs: list[tuple[int, int]]) -> None:
    """docs: list of (weeks_ago, qty) — 每条一个独立 document_no。"""
    with stockpile_db._session() as s:
        for i, (weeks_ago, qty) in enumerate(docs):
            d = _AS_OF - dt.timedelta(days=7 * weeks_ago)
            s.add(
                InventoryEvent(
                    event_at=d.isoformat(),
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    document_no=f"DOC-{barcode}-{i}",
                )
            )
        s.commit()


def _seed_stockpile(barcode: str) -> None:
    with stockpile_db._session() as s:
        s.add(
            Stockpile(
                product_barcode=barcode,
                product_model=f"M{barcode[-4:]}",
                stockpile_location="A1",
                is_active=1,
            )
        )
        s.commit()


# ── build_routed_series 路由表逐行 ──────────────────────────────────────


class TestBuildRoutedSeries:
    def test_wholesale_routes_to_croston(self):
        """6 笔大单(qty 100, 零售样本 0 < 5) → wholesale_only → CrostonSBA。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000001"
        _seed_sales(bc, [(1, 100), (3, 100), (5, 100), (7, 100), (9, 100), (11, 100)])
        with stockpile_db._session() as s:
            built = build_routed_series(bc, _AS_OF, weeks=13, session=s)
        assert built is not None
        series, sku_type, n_excluded, model_name, raw = built
        assert sku_type == "wholesale_only"
        assert model_name == "CrostonSBA"
        assert len(series) == 13  # 原始窗口周数(无缺货剔除)
        assert sum(1 for q in series if q > 0) == 6
        assert n_excluded == 0
        assert isinstance(raw, dict) and len(raw) == 13

    def test_wholesale_below_nonzero_gate_skipped(self):
        """非零周 < 5 的 wholesale → None（CrostonSBA interval 估计是噪声）。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000002"
        _seed_sales(bc, [(1, 100), (4, 100), (8, 100)])  # 仅 3 个非零周
        with stockpile_db._session() as s:
            assert build_routed_series(bc, _AS_OF, weeks=13, session=s) is None

    def test_retail_routes_to_empirical_quantile(self):
        """30 笔小单(qty 2) → retail_dominant → EmpiricalQuantile（既有行为保持）。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000003"
        _seed_sales(bc, [(w % 12, 2) for w in range(30)])
        with stockpile_db._session() as s:
            built = build_routed_series(bc, _AS_OF, weeks=13, session=s)
        assert built is not None
        _series, sku_type, _n_excl, model_name, _raw = built
        assert sku_type == "retail_dominant"
        assert model_name == "EmpiricalQuantile"

    def test_dying_not_forecast(self):
        """深度死亡（最后销售 ≥26 周前）→ None，批发也不豁免。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000004"
        _seed_sales(bc, [(27, 100), (29, 100), (31, 100), (33, 100), (35, 100)])
        with stockpile_db._session() as s:
            assert build_routed_series(bc, _AS_OF, weeks=40, session=s) is None

    def test_wholesale_marginal_band_routes(self):
        """边际带（13-26 周）的 wholesale → 仍路由 CrostonSBA（dying 分型）。

        注意 Croston 对长零尾不衰减（TSB 才修，ADR-0002 D4）——
        补货量由 bootstrap horizon 列兜底，零周稀释了分位数。
        """
        from app.services.forecast import build_routed_series

        bc = "7700000000006"
        _seed_sales(bc, [(18, 100), (20, 100), (22, 100), (24, 100), (25, 100)])
        with stockpile_db._session() as s:
            built = build_routed_series(bc, _AS_OF, weeks=30, session=s)
        assert built is not None
        _series, sku_type, _n_excl, model_name, _raw = built
        assert sku_type == "wholesale_only"
        assert model_name == "CrostonSBA"

    def test_no_sales_unclassified_none(self):
        from app.services.forecast import build_routed_series

        with stockpile_db._session() as s:
            assert build_routed_series("7700000000005", _AS_OF, weeks=13, session=s) is None


# ── refresh 端到端: wholesale 行落库 ───────────────────────────────────


class TestRefreshWithRouting:
    def test_refresh_writes_croston_row_for_wholesale(self):
        from app.services.forecast import refresh_forecast_output

        bc = "7700000000010"
        _seed_stockpile(bc)
        _seed_sales(bc, [(1, 80), (3, 120), (5, 90), (7, 100), (9, 110), (11, 95)])

        refresh_forecast_output(end_date=_AS_OF, weeks=13, barcodes=[bc])

        with stockpile_db._session() as s:
            row = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == bc)
            ).scalar_one()
        assert row.model_used == "CrostonSBA"
        assert row.sku_type == "wholesale_only"
        # horizon 列模型无关, bootstrap 照写 (ADR-0002 D3)
        assert row.p98_h is not None and row.p98_h > 0
        assert row.p50_h is not None
        assert row.horizon_weeks >= 2
        # 周字段非负 + 单调 (RL-5 口径)
        assert 0 <= row.p50 <= row.p98

    def test_refresh_still_writes_empirical_for_retail(self):
        from app.services.forecast import refresh_forecast_output

        bc = "7700000000011"
        _seed_stockpile(bc)
        _seed_sales(bc, [(w % 12, 2) for w in range(30)])

        refresh_forecast_output(end_date=_AS_OF, weeks=13, barcodes=[bc])

        with stockpile_db._session() as s:
            row = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == bc)
            ).scalar_one()
        assert row.model_used == "EmpiricalQuantile"
        assert row.sku_type == "retail_dominant"


# ── RL-11 退化检测 (ADR-0002 D5) ───────────────────────────────────────


class TestRL11DegradationAlerts:
    def test_rl11_coverage_collapse_alert(self):
        """forecast 覆盖率 < 15% 且非冷启动 → 告警。"""

        from app.services.alerts import _forecast_routing_degraded

        with stockpile_db._session() as s:
            # 100 个 active SKU, 只 3 个有预测 → 3% < 15% → 报
            for i in range(100):
                s.add(
                    Stockpile(
                        product_barcode=f"66000000{i:05d}",
                        product_model=f"C{i:05d}",
                        stockpile_location="A1",
                        is_active=1,
                    )
                )
            for i in range(3):
                s.add(
                    ForecastOutput(
                        product_barcode=f"66000000{i:05d}",
                        model_used="EmpiricalQuantile",
                        sku_type="retail_dominant",
                        n_weeks_history=20,
                        mu=1.0,
                        sigma=0.5,
                        p50=1.0,
                        p98=2.0,
                    )
                )
            s.commit()
            msgs = _forecast_routing_degraded(s)
        assert any("覆盖率" in m for m in msgs)

    def test_rl11_sku_type_monopoly_alert(self):
        """任一 sku_type 占 forecast_output > 97% → 告警(wholesale 腿断)。"""
        from app.services.alerts import _forecast_routing_degraded

        with stockpile_db._session() as s:
            for i in range(50):
                s.add(
                    Stockpile(
                        product_barcode=f"65000000{i:05d}",
                        product_model=f"D{i:05d}",
                        stockpile_location="A1",
                        is_active=1,
                    )
                )
                s.add(
                    ForecastOutput(
                        product_barcode=f"65000000{i:05d}",
                        model_used="EmpiricalQuantile",
                        sku_type="retail_dominant",  # 100% 单一类型
                        n_weeks_history=20,
                        mu=1.0,
                        sigma=0.5,
                        p50=1.0,
                        p98=2.0,
                    )
                )
            s.commit()
            msgs = _forecast_routing_degraded(s)
        assert any("垄断" in m or "单一" in m for m in msgs)

    def test_rl11_empty_table_cold_start_silent(self):
        """forecast_output 全空 → 冷启动不报(既有'表空'告警兜底)。"""
        from app.services.alerts import _forecast_routing_degraded

        with stockpile_db._session() as s:
            assert _forecast_routing_degraded(s) == []


# ── full refresh 清理不再够格 SKU 的陈旧行 ─────────────────────────────


class TestRefreshCleansStaleRows:
    def test_full_refresh_deletes_ineligible_rows(self):
        """全量 refresh 后, 本轮未写入的 SKU 旧行被清除（防僵尸预测）。"""
        from app.services.forecast import refresh_forecast_output

        stale_bc = "7700000000099"
        live_bc = "7700000000098"
        with stockpile_db._session() as s:
            s.add(
                ForecastOutput(
                    product_barcode=stale_bc,  # 不在 stockpile, 本轮必不写
                    model_used="EmpiricalQuantile",
                    sku_type="retail_dominant",
                    n_weeks_history=20,
                    mu=1.0,
                    sigma=0.5,
                    p50=1.0,
                    p98=2.0,
                )
            )
            s.commit()
        _seed_stockpile(live_bc)
        _seed_sales(live_bc, [(w % 12, 2) for w in range(30)])

        refresh_forecast_output(end_date=_AS_OF, weeks=13)  # barcodes=None → 全量

        with stockpile_db._session() as s:
            remaining = {r[0] for r in s.execute(select(ForecastOutput.product_barcode)).all()}
        assert stale_bc not in remaining
        assert live_bc in remaining

    def test_partial_refresh_keeps_other_rows(self):
        """指定 barcodes 的局部 refresh 不清别人的行。"""
        from app.services.forecast import refresh_forecast_output

        keep_bc = "7700000000097"
        target_bc = "7700000000096"
        with stockpile_db._session() as s:
            s.add(
                ForecastOutput(
                    product_barcode=keep_bc,
                    model_used="EmpiricalQuantile",
                    sku_type="retail_dominant",
                    n_weeks_history=20,
                    mu=1.0,
                    sigma=0.5,
                    p50=1.0,
                    p98=2.0,
                )
            )
            s.commit()
        _seed_stockpile(target_bc)
        _seed_sales(target_bc, [(w % 12, 2) for w in range(30)])

        refresh_forecast_output(end_date=_AS_OF, weeks=13, barcodes=[target_bc])

        with stockpile_db._session() as s:
            remaining = {r[0] for r in s.execute(select(ForecastOutput.product_barcode)).all()}
        assert keep_bc in remaining  # 局部刷新不动它
        assert target_bc in remaining
