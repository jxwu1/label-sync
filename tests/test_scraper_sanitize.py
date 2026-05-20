"""scraper/sanitize.py 单元测试.

覆盖:
  - customer_name / supplier_name → SHA-256[:16] (确定性 + 不同值不同 hash)
  - 空值 / NaN / 空字符串 → None
  - event_type='purchase' 行的 unit_price → None
  - event_type='sale' 行的 unit_price 保留
  - 输入 df 不被修改 (copy-on-write)
"""
from __future__ import annotations

import unittest

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
        df = pd.DataFrame({
            "event_type": ["sale"],
            "customer_name": ["张三"],
        })
        out = self._sanitize(df)
        assert out.loc[0, "customer_name"] != "张三"
        assert len(out.loc[0, "customer_name"]) == 16

    def test_supplier_name_hashed(self) -> None:
        df = pd.DataFrame({
            "event_type": ["purchase"],
            "supplier_name": ["GR05 SomeSupplier Ltd"],
        })
        out = self._sanitize(df)
        assert out.loc[0, "supplier_name"] != "GR05 SomeSupplier Ltd"
        assert len(out.loc[0, "supplier_name"]) == 16

    def test_purchase_unit_price_dropped(self) -> None:
        df = pd.DataFrame({
            "event_type": ["purchase", "purchase"],
            "unit_price": [1.23, 4.56],
        })
        out = self._sanitize(df)
        assert pd.isna(out.loc[0, "unit_price"])
        assert pd.isna(out.loc[1, "unit_price"])

    def test_sale_unit_price_kept(self) -> None:
        df = pd.DataFrame({
            "event_type": ["sale", "sale"],
            "unit_price": [1.23, 4.56],
        })
        out = self._sanitize(df)
        assert out.loc[0, "unit_price"] == 1.23
        assert out.loc[1, "unit_price"] == 4.56

    def test_mixed_sale_and_purchase(self) -> None:
        df = pd.DataFrame({
            "event_type": ["sale", "purchase", "sale"],
            "unit_price": [1.0, 2.0, 3.0],
        })
        out = self._sanitize(df)
        assert out.loc[0, "unit_price"] == 1.0
        assert pd.isna(out.loc[1, "unit_price"])
        assert out.loc[2, "unit_price"] == 3.0

    def test_input_not_modified(self) -> None:
        df = pd.DataFrame({
            "event_type": ["sale"],
            "customer_name": ["张三"],
            "unit_price": [9.99],
        })
        df_before = df.copy()
        _ = self._sanitize(df)
        assert df.loc[0, "customer_name"] == "张三"
        assert df.loc[0, "unit_price"] == 9.99
        pd.testing.assert_frame_equal(df, df_before)

    def test_missing_columns_no_crash(self) -> None:
        df = pd.DataFrame({
            "event_type": ["sale"],
            "qty": [5],
        })
        out = self._sanitize(df)
        assert "qty" in out.columns
        assert out.loc[0, "qty"] == 5

    def test_none_customer_name_stays_none(self) -> None:
        df = pd.DataFrame({
            "event_type": ["sale", "sale"],
            "customer_name": [None, "张三"],
        })
        out = self._sanitize(df)
        assert pd.isna(out.loc[0, "customer_name"])
        assert len(out.loc[1, "customer_name"]) == 16


if __name__ == "__main__":
    unittest.main()
