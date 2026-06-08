"""scraper/sanitize.py 单元测试.

覆盖:
  - customer_name / supplier_name → SHA-256[:16] (确定性 + 不同值不同 hash)
  - 空值 / NaN / 空字符串 → None
  - 2026-05-21 起 purchase.unit_price **不再** NULL out, plaintext 通过
  - event_type='sale' 行的 unit_price 一直保留
  - 输入 df 不被修改 (copy-on-write)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


class HashNameTests(unittest.TestCase):
    def _h(self, v):
        from scraper.sanitize import _hash_name

        return _hash_name(v)

    def test_deterministic_same_name_same_hash(self) -> None:
        assert self._h("张三") == self._h("张三")

    def test_different_names_different_hashes(self) -> None:
        assert self._h("张三") != self._h("李四")

    def test_length_16_hex(self) -> None:
        h = self._h("Some Name 123")
        assert h is not None
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_none_returns_none(self) -> None:
        assert self._h(None) is None

    def test_nan_returns_none(self) -> None:
        import math

        assert self._h(math.nan) is None

    def test_empty_string_returns_none(self) -> None:
        assert self._h("") is None
        assert self._h("   ") is None

    def test_strips_whitespace_before_hash(self) -> None:
        assert self._h("foo") == self._h("  foo  ")

    def test_pd_na_returns_none(self) -> None:
        """pandas string dtype 用 pd.NA 表示缺失, 必须接住."""
        assert self._h(pd.NA) is None

    def test_pd_na_in_string_series(self) -> None:
        """从 pandas StringDtype Series .apply() 进来的 NA 也要正确处理.

        pandas 在 result Series 里把 None 转成 nan, 所以用 pd.isna 而不是 is None.
        """
        s = pd.Series(["张三", pd.NA, "", "  "], dtype="string")
        hashed = s.apply(self._h)
        assert not pd.isna(hashed[0]) and len(hashed[0]) == 16
        assert pd.isna(hashed[1])
        assert pd.isna(hashed[2])
        assert pd.isna(hashed[3])


class SanitizeDataframeTests(unittest.TestCase):
    def _sanitize(self, df):
        from scraper.sanitize import sanitize_dataframe

        return sanitize_dataframe(df)

    def test_customer_name_hashed(self) -> None:
        df = pd.DataFrame(
            {
                "event_type": ["sale"],
                "customer_name": ["张三"],
            }
        )
        out = self._sanitize(df)
        assert out.loc[0, "customer_name"] != "张三"
        assert len(out.loc[0, "customer_name"]) == 16

    def test_supplier_name_hashed(self) -> None:
        df = pd.DataFrame(
            {
                "event_type": ["purchase"],
                "supplier_name": ["GR05 SomeSupplier Ltd"],
            }
        )
        out = self._sanitize(df)
        assert out.loc[0, "supplier_name"] != "GR05 SomeSupplier Ltd"
        assert len(out.loc[0, "supplier_name"]) == 16

    def test_purchase_unit_price_kept(self) -> None:
        """2026-05-21 起策略变更, purchase.unit_price 也保留 (不再 NULL out)."""
        df = pd.DataFrame(
            {
                "event_type": ["purchase", "purchase"],
                "unit_price": [1.23, 4.56],
            }
        )
        out = self._sanitize(df)
        assert out.loc[0, "unit_price"] == 1.23
        assert out.loc[1, "unit_price"] == 4.56

    def test_sale_unit_price_kept(self) -> None:
        df = pd.DataFrame(
            {
                "event_type": ["sale", "sale"],
                "unit_price": [1.23, 4.56],
            }
        )
        out = self._sanitize(df)
        assert out.loc[0, "unit_price"] == 1.23
        assert out.loc[1, "unit_price"] == 4.56

    def test_mixed_sale_and_purchase_both_kept(self) -> None:
        """2026-05-21 起 sale + purchase 的 unit_price 都保留."""
        df = pd.DataFrame(
            {
                "event_type": ["sale", "purchase", "sale"],
                "unit_price": [1.0, 2.0, 3.0],
            }
        )
        out = self._sanitize(df)
        assert out.loc[0, "unit_price"] == 1.0
        assert out.loc[1, "unit_price"] == 2.0
        assert out.loc[2, "unit_price"] == 3.0

    def test_input_not_modified(self) -> None:
        df = pd.DataFrame(
            {
                "event_type": ["sale"],
                "customer_name": ["张三"],
                "unit_price": [9.99],
            }
        )
        df_before = df.copy()
        _ = self._sanitize(df)
        assert df.loc[0, "customer_name"] == "张三"
        assert df.loc[0, "unit_price"] == 9.99
        pd.testing.assert_frame_equal(df, df_before)

    def test_missing_columns_no_crash(self) -> None:
        df = pd.DataFrame(
            {
                "event_type": ["sale"],
                "qty": [5],
            }
        )
        out = self._sanitize(df)
        assert "qty" in out.columns
        assert out.loc[0, "qty"] == 5

    def test_none_customer_name_stays_none(self) -> None:
        df = pd.DataFrame(
            {
                "event_type": ["sale", "sale"],
                "customer_name": [None, "张三"],
            }
        )
        out = self._sanitize(df)
        assert pd.isna(out.loc[0, "customer_name"])
        assert len(out.loc[1, "customer_name"]) == 16


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SANITIZE = _REPO_ROOT / "scraper" / "sanitize.py"


def _run_sanitize(staging_dir, sanitized_dir, *extra):
    env = dict(os.environ)
    env["SCRAPE_OUTPUT_DIR"] = str(staging_dir)
    env["SCRAPE_SANITIZED_DIR"] = str(sanitized_dir)
    return subprocess.run(
        [sys.executable, str(_SANITIZE), *extra],
        env=env,
        capture_output=True,
        text=True,
    )


class SanitizeWeeklyGateTests(unittest.TestCase):
    def test_historical_file_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d) / "staging"
            sanitized = Path(d) / "sanitized"
            staging.mkdir()
            pd.DataFrame({"x": [1]}).to_parquet(
                staging / "events_sale_2015-01-01_2023-01-02.parquet", index=False
            )
            r = _run_sanitize(staging, sanitized)
            assert r.returncode != 0, r.stdout + r.stderr
            assert not (sanitized / "events_sale_2015-01-01_2023-01-02.parquet").exists()

    def test_allow_backfill_processes_history(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d) / "staging"
            sanitized = Path(d) / "sanitized"
            staging.mkdir()
            pd.DataFrame({"customer_name": ["张三"]}).to_parquet(
                staging / "events_sale_2015-01-01_2023-01-02.parquet", index=False
            )
            r = _run_sanitize(staging, sanitized, "--allow-backfill")
            assert r.returncode == 0, r.stdout + r.stderr
            assert (sanitized / "events_sale_2015-01-01_2023-01-02.parquet").exists()

    def test_current_week_file_processed(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d) / "staging"
            sanitized = Path(d) / "sanitized"
            staging.mkdir()
            today = date.today()
            wk = today - timedelta(days=7)
            name = f"events_sale_{wk}_{today}.parquet"
            pd.DataFrame({"customer_name": ["张三"]}).to_parquet(staging / name, index=False)
            r = _run_sanitize(staging, sanitized)
            assert r.returncode == 0, r.stdout + r.stderr
            assert (sanitized / name).exists()


if __name__ == "__main__":
    unittest.main()
