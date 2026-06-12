"""backtest_service 单测 (plan §2.1-2.7)."""

from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import insert, select

from app.models import BacktestResult, BacktestRun, InventoryEvent, Stockpile
from app.repositories import stockpile_db


class ForecastDistTests(unittest.TestCase):
    def test_dataclass_fields(self) -> None:
        from app.services.backtest import ForecastDist

        d = ForecastDist(mu=1.5, sigma=0.3, p50=1.5, p98=2.1)
        assert d.mu == 1.5
        assert d.p98 == 2.1


class MetricsTests(unittest.TestCase):
    def test_mape_simple(self) -> None:
        from app.services.backtest import mape

        assert abs(mape([10, 20], [12, 18]) - 0.15) < 1e-9

    def test_mape_zero_actuals_excluded(self) -> None:
        from app.services.backtest import mape

        assert abs(mape([0, 10], [5, 11]) - 0.1) < 1e-9

    def test_mape_all_zero_actuals_returns_none(self) -> None:
        from app.services.backtest import mape

        assert mape([0, 0, 0], [1, 2, 3]) is None

    def test_mape_empty_returns_none(self) -> None:
        from app.services.backtest import mape

        assert mape([], []) is None

    def test_bias_signed(self) -> None:
        from app.services.backtest import bias

        assert abs(bias([10, 20], [12, 17]) - (-0.5)) < 1e-9

    def test_in_sample_naive_mae(self) -> None:
        from app.services.backtest import _in_sample_naive_mae

        # |12-10|,|8-12|,|14-8| = 2,4,6 → 12/3 = 4
        assert abs(_in_sample_naive_mae([10, 12, 8, 14]) - 4.0) < 1e-9

    def test_in_sample_naive_mae_constant_none(self) -> None:
        from app.services.backtest import _in_sample_naive_mae

        assert _in_sample_naive_mae([5, 5, 5]) is None  # 差分全 0

    def test_in_sample_naive_mae_short_none(self) -> None:
        from app.services.backtest import _in_sample_naive_mae

        assert _in_sample_naive_mae([5]) is None

    def test_mase_from_records_paper_value(self) -> None:
        """标准 MASE 逐窗标准化, 纸面精确值 (Hyndman & Koehler 2006)。

        walk_forward 是 expanding window: train=series[:train_end] (累计扩张),
        NaiveMean4W.predict 用 train 最后 4 周均值。
        series=[10,12,8,14,20,6], window_train=4, window_test=1:
          窗0 train=[10,12,8,14]
              naive_mae=mean(2,4,6)=4    pred=mean(10,12,8,14)=11   |20-11|/4 = 2.25
          窗1 train=[10,12,8,14,20]
              naive_mae=mean(2,4,6,6)=4.5 pred=mean(12,8,14,20)=13.5 |6-13.5|/4.5 = 5/3
        MASE = (2.25 + 5/3)/2 = 1.9583333…
        """
        from app.services.backtest import NaiveMean4W, mase_from_records, walk_forward_backtest

        records = walk_forward_backtest(
            [10, 12, 8, 14, 20, 6], NaiveMean4W, window_train=4, window_test=1
        )
        assert abs(mase_from_records(records) - (2.25 + 5 / 3) / 2) < 1e-9

    def test_mase_from_records_all_constant_train_none(self) -> None:
        """全常数序列 → 每窗 train_naive_mae=0 被剔 → None。"""
        from app.services.backtest import NaiveMean4W, mase_from_records, walk_forward_backtest

        records = walk_forward_backtest(
            [5, 5, 5, 5, 5, 5], NaiveMean4W, window_train=4, window_test=1
        )
        assert mase_from_records(records) is None

    def test_mase_from_records_empty_none(self) -> None:
        from app.services.backtest import mase_from_records

        assert mase_from_records([]) is None

    def test_mase_from_records_single_window(self) -> None:
        """单窗序列: 只产出一组 record, MASE = 该窗 scaled error 均值。

        series=[10,12,8,14,20], window_train=4, window_test=1:
          窗0 train=[10,12,8,14] naive_mae=4 pred=11 |20-11|/4 = 2.25
        """
        from app.services.backtest import NaiveMean4W, mase_from_records, walk_forward_backtest

        records = walk_forward_backtest(
            [10, 12, 8, 14, 20], NaiveMean4W, window_train=4, window_test=1
        )
        assert abs(mase_from_records(records) - 2.25) < 1e-9

    def test_coverage_p98_in_bound(self) -> None:
        from app.services.backtest import coverage_p98

        assert abs(coverage_p98([5, 15, 25], [10, 20, 20]) - 2 / 3) < 1e-9

    def test_coverage_p98_all_in(self) -> None:
        from app.services.backtest import coverage_p98

        assert coverage_p98([1, 2, 3], [10, 10, 10]) == 1.0


class NaiveMean4WTests(unittest.TestCase):
    def test_predicts_mean_of_last_4(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([1, 2, 3, 4, 5, 6, 7, 8])
        p = m.predict()
        assert p.mu == 6.5
        assert p.p50 == 6.5

    def test_short_history_uses_all(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([10, 20])
        assert m.predict().mu == 15.0

    def test_empty_history(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([])
        p = m.predict()
        assert p.mu == 0.0
        assert p.sigma == 0.0
        assert p.p98 == 0.0

    def test_p98_never_negative(self) -> None:
        from app.services.backtest import NaiveMean4W

        m = NaiveMean4W()
        m.fit([0, 0, 0, 0])
        assert m.predict().p98 >= 0


class NaiveSeasonal52WTests(unittest.TestCase):
    def test_predicts_lag_52(self) -> None:
        from app.services.backtest import NaiveSeasonal52W

        history = [0] + [42] + [0] * 51
        m = NaiveSeasonal52W()
        m.fit(history)
        assert m.predict().mu == 42.0

    def test_short_history_falls_back_to_mean(self) -> None:
        from app.services.backtest import NaiveSeasonal52W

        m = NaiveSeasonal52W()
        m.fit([1, 2, 3])
        assert m.predict().mu == 2.0


class LinearTrend12WTests(unittest.TestCase):
    def test_increasing_trend(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        assert abs(m.predict().mu - 13.0) < 1e-6

    def test_constant_trend_predicts_constant(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([5] * 12)
        assert abs(m.predict().mu - 5.0) < 1e-6

    def test_short_history_falls_back_to_mean(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([5, 10])
        assert m.predict().mu == 7.5

    def test_p98_never_negative(self) -> None:
        from app.services.backtest import LinearTrend12W

        m = LinearTrend12W()
        m.fit([10, 8, 6, 4, 2, 1, 0, 0, 0, 0, 0, 0])
        assert m.predict().p98 >= 0


class CrostonSBATests(unittest.TestCase):
    """plan §2.2 间歇需求 baseline."""

    def test_basic_intermittent(self) -> None:
        from app.services.backtest import CrostonSBA

        history = [0, 0, 6, 0, 0, 6, 0, 0, 6]
        m = CrostonSBA()
        m.fit(history)
        p = m.predict()
        assert 1.5 < p.mu < 2.0

    def test_no_demand(self) -> None:
        from app.services.backtest import CrostonSBA

        m = CrostonSBA()
        m.fit([0, 0, 0, 0, 0])
        assert m.predict().mu == 0.0

    def test_single_demand_at_start(self) -> None:
        from app.services.backtest import CrostonSBA

        m = CrostonSBA()
        m.fit([10, 0, 0, 0, 0])
        p = m.predict()
        assert 9.0 <= p.mu <= 10.0

    def test_empty_history(self) -> None:
        from app.services.backtest import CrostonSBA

        m = CrostonSBA()
        m.fit([])
        assert m.predict().mu == 0.0


class WalkForwardTests(unittest.TestCase):
    def test_record_count(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert len(records) == 30

    def test_record_keys(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert set(records[0].keys()) == {
            "step_idx",
            "horizon",
            "predicted",
            "p50",
            "p98",
            "actual",
            "train_naive_mae",
        }

    def test_horizon_cycles(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert [r["horizon"] for r in records[:4]] == [1, 2, 1, 2]

    def test_actual_matches_test_window(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert records[0]["actual"] == 5
        assert records[1]["actual"] == 6

    def test_step_idx_global_position(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        series = list(range(1, 21))
        records = walk_forward_backtest(series, NaiveMean4W, window_train=4, window_test=2)
        assert records[0]["step_idx"] == 4
        assert records[1]["step_idx"] == 5

    def test_too_short_returns_empty(self) -> None:
        from app.services.backtest import NaiveMean4W, walk_forward_backtest

        records = walk_forward_backtest([1, 2, 3], NaiveMean4W, window_train=4, window_test=2)
        assert records == []


class _DBBase(unittest.TestCase):
    """DB 集成测试基类: 在临时 SQLite 上 seed 一个高频零售 SKU."""

    # DB 隔离由 conftest autouse _isolate_db 负责（unified engine 指向 tmp db_path）

    def _seed_stockpile(self, barcode: str) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(Stockpile).values(
                    product_barcode=barcode,
                    product_model=barcode,
                    stockpile_location="",
                    is_active=1,
                )
            )
            s.commit()

    def _seed_retail_weekly(self, barcode: str, weeks: int, qty: int = 5) -> None:
        """构造 weeks 周, 每周 qty 单零售销售 (qty<=24 → retail_dominant)."""
        from datetime import timedelta

        with stockpile_db._session() as s:
            for w in range(weeks):
                event_at = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=event_at,
                        event_type="sale",
                        product_barcode=barcode,
                        qty=qty,
                        document_no=f"{barcode}-D{w}",
                    )
                )
            s.commit()


class RunBacktestForSkuTests(_DBBase):
    def test_returns_metrics_dict(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        self._seed_retail_weekly("B1", weeks=30)
        r = run_backtest_for_sku("B1", end_date=date(2026, 5, 13), weeks=30, model_cls=NaiveMean4W)
        assert r is not None
        assert r["barcode"] == "B1"
        assert r["sku_type"] == "retail_dominant"
        assert r["mape"] is not None
        assert "bias" in r
        assert "coverage_p98" in r

    def test_returns_none_if_too_short(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        self._seed_retail_weekly("B1", weeks=5)
        r = run_backtest_for_sku(
            "B1",
            end_date=date(2026, 5, 13),
            weeks=4,
            model_cls=NaiveMean4W,
            window_train=13,
            window_test=4,
        )
        assert r is None

    def test_returns_none_if_min_weeks_not_met(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        self._seed_retail_weekly("B1", weeks=30)
        r = run_backtest_for_sku(
            "B1",
            end_date=date(2026, 5, 13),
            weeks=30,
            model_cls=NaiveMean4W,
            min_weeks=100,
        )
        assert r is None

    def test_wholesale_only_returns_none(self) -> None:
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        # 5 个大单 doc → wholesale_only
        with stockpile_db._session() as s:
            for i in range(5):
                s.execute(
                    insert(InventoryEvent).values(
                        event_at="2026-04-01",
                        event_type="sale",
                        product_barcode="WO",
                        qty=720,
                        document_no=f"D{i}",
                    )
                )
            s.commit()
        r = run_backtest_for_sku(
            "WO",
            end_date=date(2026, 5, 13),
            weeks=30,
            model_cls=NaiveMean4W,
            view="base_demand",
        )
        assert r is None

    def test_view_all_includes_wholesale(self) -> None:
        """view='all' 不过 base_demand → wholesale_only SKU 也跑."""
        from datetime import timedelta

        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        with stockpile_db._session() as s:
            for w in range(30):
                event_at = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=event_at,
                        event_type="sale",
                        product_barcode="WO",
                        qty=720,
                        document_no=f"D{w}",
                    )
                )
            s.commit()
        r = run_backtest_for_sku(
            "WO",
            end_date=date(2026, 5, 13),
            weeks=30,
            model_cls=NaiveMean4W,
            view="all",
        )
        assert r is not None
        assert r["sku_type"] == "wholesale_only"


class RunBacktestSelectionSn2Tests(_DBBase):
    """SN-2: 入选过滤只数训练可用段, 测试期销量不参与准入判定 (审计 #5)."""

    _END = date(2026, 5, 13)
    _WEEKS = 30

    def _seed_weeks(self, barcode: str, week_offsets: list[int], qty: int = 5) -> None:
        """在距 end_date 第 week_offsets[i] 周 (0=末周) 各灌一笔零售单。"""
        from datetime import timedelta

        with stockpile_db._session() as s:
            for w in week_offsets:
                event_at = (self._END - timedelta(days=w * 7)).isoformat()
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=event_at,
                        event_type="sale",
                        product_barcode=barcode,
                        qty=qty,
                        document_no=f"{barcode}-W{w}",
                    )
                )
            s.commit()

    def test_test_period_burst_excluded(self) -> None:
        """训练段稀疏 (< min_weeks 非零), 测试段 (末 window_test 周) 爆发 → 仍排除。"""
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        # 末 4 周 (offset 0..3 = 测试期) 每周都有量; 训练段只有 3 个非零周
        self._seed_weeks("SP", [0, 1, 2, 3] + [10, 15, 20])
        r = run_backtest_for_sku(
            "SP",
            end_date=self._END,
            weeks=self._WEEKS,
            model_cls=NaiveMean4W,
            window_test=4,
            min_weeks=12,
        )
        assert r is None

    def test_training_dense_test_zero_included(self) -> None:
        """训练段达标 (>= min_weeks 非零), 测试段 (末 4 周) 归零 → 仍入选。"""
        from app.services.backtest import NaiveMean4W, run_backtest_for_sku

        # 训练段 offset 4..21 共 18 个非零周, 测试段 offset 0..3 全空
        self._seed_weeks("DN", list(range(4, 22)))
        r = run_backtest_for_sku(
            "DN",
            end_date=self._END,
            weeks=self._WEEKS,
            model_cls=NaiveMean4W,
            window_test=4,
            min_weeks=12,
        )
        assert r is not None
        assert r["barcode"] == "DN"


class RunBacktestAllSkusTests(_DBBase):
    def test_writes_run_and_results(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_retail_weekly("B1", weeks=30)
        run_id = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
            notes="test",
        )
        with stockpile_db._session() as s:
            run = s.execute(select(BacktestRun).where(BacktestRun.id == run_id)).scalar_one()
            assert run.model_name == "NaiveMean4W"
            assert run.notes == "test"
            assert run.n_skus_total == 1
            assert run.n_skus_scored == 1
            results = (
                s.execute(select(BacktestResult).where(BacktestResult.run_id == run_id))
                .scalars()
                .all()
            )
            assert len(results) == 1
            assert results[0].product_barcode == "B1"
            assert results[0].sku_type == "retail_dominant"

    def test_skipped_sku_not_in_results(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_retail_weekly("B1", weeks=5)  # 太短
        run_id = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        with stockpile_db._session() as s:
            run = s.execute(select(BacktestRun).where(BacktestRun.id == run_id)).scalar_one()
            assert run.n_skus_total == 1
            assert run.n_skus_scored == 0
            results = (
                s.execute(select(BacktestResult).where(BacktestResult.run_id == run_id))
                .scalars()
                .all()
            )
            assert results == []

    def test_unknown_model_raises(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        with self.assertRaises(ValueError):
            run_backtest_all_skus(
                model_name="DoesNotExist",
                end_date=date(2026, 5, 13),
                barcodes=[],
            )

    def test_unknown_view_raises(self) -> None:
        from app.services.backtest import run_backtest_all_skus

        with self.assertRaises(ValueError):
            run_backtest_all_skus(
                model_name="NaiveMean4W",
                end_date=date(2026, 5, 13),
                view="not_a_view",
                barcodes=[],
            )


class CompareRunPairTests(_DBBase):
    """plan §2.8 双视图回测对比."""

    def test_returns_summary_with_common_skus(self) -> None:
        from app.services.backtest import compare_run_pair, run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_retail_weekly("B1", weeks=30)
        run_a = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            view="all",
            barcodes=["B1"],
        )
        run_b = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            view="base_demand",
            barcodes=["B1"],
        )
        cmp = compare_run_pair(run_a, run_b)
        assert cmp["run_a"]["id"] == run_a
        assert cmp["run_b"]["id"] == run_b
        assert cmp["run_a"]["view"] == "all"
        assert cmp["run_b"]["view"] == "base_demand"
        assert cmp["common_skus"] == 1
        assert len(cmp["items"]) == 1
        item = cmp["items"][0]
        assert item["product_barcode"] == "B1"
        assert "mase_delta" in item

    def test_summary_counts_unchanged_when_identical(self) -> None:
        """同一 SKU 同一视图 同一模型 → MASE 一致 → unchanged 计 1."""
        from datetime import timedelta

        from app.services.backtest import compare_run_pair, run_backtest_all_skus

        # 波动序列, 让 lag-1 naive MAE != 0 → MASE 非 None
        self._seed_stockpile("B1")
        with stockpile_db._session() as s:
            for w in range(30):
                d = (date(2026, 5, 13) - timedelta(days=w * 7)).isoformat()
                qty = 5 + (w % 3)  # 5, 6, 7, 5, 6, 7, ...
                s.execute(
                    insert(InventoryEvent).values(
                        event_at=d,
                        event_type="sale",
                        product_barcode="B1",
                        qty=qty,
                        document_no=f"B1-D{w}",
                    )
                )
            s.commit()
        ra = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        rb = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        cmp = compare_run_pair(ra, rb)
        assert cmp["common_skus"] == 1
        assert cmp["summary"]["improved"] == 0
        assert cmp["summary"]["worsened"] == 0
        assert cmp["summary"]["unchanged"] == 1
        assert cmp["summary"]["median_mase_delta"] == 0.0

    def test_unknown_run_raises(self) -> None:
        from app.services.backtest import compare_run_pair

        with self.assertRaises(ValueError):
            compare_run_pair(99999, 99998)

    def test_no_common_skus_empty_items(self) -> None:
        from app.services.backtest import compare_run_pair, run_backtest_all_skus

        self._seed_stockpile("B1")
        self._seed_stockpile("B2")
        self._seed_retail_weekly("B1", weeks=30)
        self._seed_retail_weekly("B2", weeks=30)
        ra = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B1"],
        )
        rb = run_backtest_all_skus(
            model_name="NaiveMean4W",
            end_date=date(2026, 5, 13),
            weeks=30,
            barcodes=["B2"],
        )
        cmp = compare_run_pair(ra, rb)
        assert cmp["common_skus"] == 0
        assert cmp["items"] == []


if __name__ == "__main__":
    unittest.main()
