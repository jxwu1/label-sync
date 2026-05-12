"""etl/parquet_cleaner 单测。

合成 DataFrame 覆盖每条规则 + IO roundtrip。不读真实 parquet。
"""

from __future__ import annotations

import pandas as pd

from etl.parquet_cleaner import (
    CleaningReport,
    _apply_rules,
    _count_irregular_barcodes,
    _drop_concat_barcode,
    _drop_exact_duplicates,
    _drop_tax_rows,
    _split_internal_accounts,
    clean_events_parquet,
)


def _row(**kwargs):
    base = {
        "event_at": "2025-05-31",
        "event_type": "sale",
        "product_barcode": "1234567890123",
        "qty": 1,
        "unit_price": 1.5,
        "discount_pct": 0.0,
        "document_no": "D001",
        "shipping_doc": None,
        "customer_id": "C100",
        "customer_name": "test",
        "supplier_id": None,
        "supplier_name": None,
    }
    base.update(kwargs)
    return base


def test_drop_tax_rows():
    df = pd.DataFrame(
        [
            _row(product_barcode="90000000001"),
            _row(product_barcode="1234567890123"),
            _row(product_barcode="90000000001", document_no="D002"),
        ]
    )
    out, dropped = _drop_tax_rows(df)
    assert dropped == 2
    assert len(out) == 1


def test_drop_tax_rows_none():
    df = pd.DataFrame([_row(product_barcode="1234567890123")])
    out, dropped = _drop_tax_rows(df)
    assert dropped == 0
    assert len(out) == 1


def test_drop_concat_barcode():
    df = pd.DataFrame(
        [
            _row(product_barcode="58280793288955832672714752"),  # 26
            _row(product_barcode="582807927252512"),  # 15
            _row(product_barcode="1234567890123", document_no="D2"),  # 13 keep
            _row(product_barcode="0", document_no="D3"),  # 1 keep
            _row(product_barcode="14904530128483", document_no="D4"),  # 14 keep
        ]
    )
    out, dropped = _drop_concat_barcode(df)
    assert dropped == 2
    assert len(out) == 3


def test_drop_exact_duplicates():
    df = pd.DataFrame(
        [
            _row(),
            _row(),
            _row(document_no="D002"),
        ]
    )
    out, dropped = _drop_exact_duplicates(df)
    assert dropped == 1
    assert len(out) == 2


def test_drop_exact_duplicates_with_none_shipping_doc():
    df = pd.DataFrame([_row(shipping_doc=None), _row(shipping_doc=None)])
    out, dropped = _drop_exact_duplicates(df)
    assert dropped == 1
    assert len(out) == 1


def test_split_internal_accounts():
    df = pd.DataFrame(
        [
            _row(customer_id="999991"),
            _row(customer_id="999993", document_no="D2"),
            _row(customer_id="823016", document_no="D3"),
            _row(customer_id=None, document_no="D4"),
        ]
    )
    cleaned, archive, archived = _split_internal_accounts(df)
    assert archived == 2
    assert len(archive) == 2
    assert len(cleaned) == 2


def test_split_internal_accounts_all_normal():
    df = pd.DataFrame([_row(customer_id="C001"), _row(customer_id="C002")])
    cleaned, archive, archived = _split_internal_accounts(df)
    assert archived == 0
    assert len(archive) == 0
    assert len(cleaned) == 2


def test_count_irregular_barcodes():
    df = pd.DataFrame(
        [
            _row(product_barcode="1234567890123"),
            _row(product_barcode="14904530128483", document_no="D2"),
            _row(product_barcode="0", document_no="D3"),
            _row(product_barcode="12345678901", document_no="D4"),
            _row(product_barcode="RDDT2021", document_no="D5"),
        ]
    )
    n, samples = _count_irregular_barcodes(df)
    assert n == 2
    assert set(samples) == {"12345678901", "RDDT2021"}


def test_count_irregular_excludes_tax():
    df = pd.DataFrame([_row(product_barcode="90000000001")])
    n, _ = _count_irregular_barcodes(df)
    assert n == 0


def test_apply_rules_end_to_end():
    df = pd.DataFrame(
        [
            _row(product_barcode="1234567890123", document_no="D1"),
            _row(product_barcode="90000000001", document_no="D2"),
            _row(product_barcode="58280793288955832672714752", document_no="D3"),
            _row(product_barcode="1234567890124", document_no="D4", customer_id="999991"),
            _row(product_barcode="1234567890123", document_no="D1"),
        ]
    )
    cleaned, archive, report = _apply_rules(df)
    assert report.rows_in == 5
    assert report.dropped_tax_rows == 1
    assert report.dropped_concat_barcode == 1
    assert report.dropped_duplicates == 1
    assert report.archived_internal == 1
    assert report.rows_out == 1
    assert len(cleaned) == 1
    assert len(archive) == 1


def test_apply_rules_empty():
    df = pd.DataFrame(
        columns=[
            "event_at",
            "event_type",
            "product_barcode",
            "qty",
            "unit_price",
            "document_no",
            "shipping_doc",
            "customer_id",
        ]
    )
    cleaned, archive, report = _apply_rules(df)
    assert report.rows_in == 0
    assert report.rows_out == 0
    assert len(archive) == 0


def test_clean_events_parquet_roundtrip(tmp_path):
    df = pd.DataFrame(
        [
            _row(document_no="D1"),
            _row(document_no="D2", customer_id="999991"),
            _row(document_no="D3", product_barcode="90000000001"),
        ]
    )
    src = tmp_path / "raw.parquet"
    df.to_parquet(src, index=False)

    dst_cleaned = tmp_path / "cleaned.parquet"
    dst_archive = tmp_path / "archive.parquet"
    report = clean_events_parquet(src, dst_cleaned, dst_archive)

    assert report.rows_in == 3
    assert report.rows_out == 1
    assert report.dropped_tax_rows == 1
    assert report.archived_internal == 1

    out = pd.read_parquet(dst_cleaned)
    assert len(out) == 1
    arc = pd.read_parquet(dst_archive)
    assert len(arc) == 1
    assert arc.iloc[0]["customer_id"] == "999991"


def test_clean_events_parquet_no_archive(tmp_path):
    df = pd.DataFrame(
        [
            _row(document_no="D1"),
            _row(document_no="D2", customer_id="999991"),
        ]
    )
    src = tmp_path / "raw.parquet"
    df.to_parquet(src, index=False)
    dst_cleaned = tmp_path / "cleaned.parquet"

    report = clean_events_parquet(src, dst_cleaned, dst_archive=None)
    assert report.archived_internal == 1
    assert report.rows_out == 1
    assert dst_cleaned.exists()


def test_clean_events_parquet_archive_skipped_when_no_internal(tmp_path):
    df = pd.DataFrame([_row(document_no="D1")])
    src = tmp_path / "raw.parquet"
    df.to_parquet(src, index=False)

    dst_cleaned = tmp_path / "cleaned.parquet"
    dst_archive = tmp_path / "archive.parquet"
    report = clean_events_parquet(src, dst_cleaned, dst_archive)

    assert report.archived_internal == 0
    assert dst_cleaned.exists()
    assert not dst_archive.exists()


def test_cleaning_report_summary_format():
    report = CleaningReport(
        src_path="/x/foo.parquet",
        rows_in=100,
        dropped_tax_rows=2,
        dropped_concat_barcode=1,
        dropped_duplicates=3,
        archived_internal=10,
        rows_out=84,
        irregular_barcode_count=5,
        irregular_barcode_samples=["a", "b"],
    )
    s = report.summary()
    assert "foo.parquet" in s
    assert "100" in s
    assert "84" in s
    assert "5 笔" in s
