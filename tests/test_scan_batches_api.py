"""GET /api/history/scan-batches 契约测试（Phase 4b）。

鉴权夹具镜像 tests/test_history_recent_changes_api.py（real_app + X-Upload-Token）。
扫描数据走文件系统：monkeypatch scan_history service 的 OUTPUT_DIR 到 tmp 目录。
"""

from __future__ import annotations

import pytest

from app.services import scan_history as scan_history_service


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


_AUTH = {"X-Upload-Token": "test-token-123"}


def _make_batch(
    base, folder_name, *, csv_rows=0, xlsx=None, write_csv=True, csv_name="产品信息导入模板.csv"
):
    batch = base / folder_name
    batch.mkdir()
    if write_csv:
        csv = batch / csv_name
        lines = ["型号,唯一码"]
        lines.extend(f"M{i},B{i}" for i in range(csv_rows))
        csv.write_text("\n".join(lines), encoding="utf-8-sig")
    for x in xlsx or []:
        (batch / x).write_bytes(b"FAKE" * 100)
    return batch


def _get(app):
    return app.test_client().get("/api/history/scan-batches", headers=_AUTH)


def test_returns_strict_schema_with_batches(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", csv_rows=3, xlsx=["ALI.xlsx"])
    _make_batch(tmp_path, "ABDUL价格标20260421100000", csv_rows=5)

    resp = _get(real_app)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert len(data["batches"]) == 2
    # 最近优先：ABDUL（更晚时间戳）在前
    assert data["batches"][0]["employee"] == "ABDUL"


def test_exact_key_sets(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", csv_rows=1, xlsx=["ALI.xlsx"])

    data = _get(real_app).get_json()
    assert set(data.keys()) == {"ok", "batches"}
    b = data["batches"][0]
    assert set(b.keys()) == {
        "batch_id",
        "employee",
        "scanned_at",
        "csv_filename",
        "csv_rows",
        "csv_size_bytes",
        "xlsx_files",
    }
    assert set(b["xlsx_files"][0].keys()) == {"name", "size_bytes"}
    # 值断言：确认主文件名路径实际被检测到
    assert b["csv_filename"] == "产品信息导入模板.csv"
    assert b["csv_rows"] == 1
    assert b["csv_size_bytes"] > 0


def test_legacy_csv_filename_detected(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", csv_rows=2, csv_name="1产品信息导入模板.csv")
    b = _get(real_app).get_json()["batches"][0]
    assert b["csv_filename"] == "1产品信息导入模板.csv"
    assert b["csv_rows"] == 2


def test_missing_csv_nulls_pass_schema(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    _make_batch(tmp_path, "ALI价格标20260420100000", xlsx=["ALI.xlsx"], write_csv=False)

    resp = _get(real_app)
    assert resp.status_code == 200  # 不被 pydantic 打 500
    b = resp.get_json()["batches"][0]
    assert b["csv_filename"] is None
    assert b["csv_rows"] is None
    assert b["csv_size_bytes"] is None


def test_empty_output_dir(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    data = _get(real_app).get_json()
    assert data["batches"] == []


def test_caps_at_100(real_app, tmp_path, monkeypatch):
    monkeypatch.setattr(scan_history_service, "OUTPUT_DIR", tmp_path)
    for i in range(110):
        _make_batch(tmp_path, f"E价格标202604{i:08d}", csv_rows=0)
    data = _get(real_app).get_json()
    assert len(data["batches"]) == 100


def test_unauthenticated_returns_json_401(real_app):
    resp = real_app.test_client().get("/api/history/scan-batches")  # 无 token
    assert resp.status_code == 401
    assert resp.is_json


def test_service_exception_bubbles_500(real_app, monkeypatch):
    def boom():
        raise RuntimeError("scan boom")

    monkeypatch.setattr(scan_history_service, "list_batches", boom)
    client = real_app.test_client()
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    resp = client.get("/api/history/scan-batches", headers=_AUTH)
    assert resp.status_code == 500
