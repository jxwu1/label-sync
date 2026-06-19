"""大批次性能验收：/api/history/recent-changes/<id>/changes（Phase 4a Task 8 Step 5）。

PERF TEST（无 skip marker，CI 照常跑）：
seed 5000+ 条 DISTINCT (barcode, field) change → raw mode 不折叠 → 全量 >=5000 行。
单次 GET 经 get_batch_detail → pydantic RecentChangesDetail → JSON，
验证服务端 cap=500、total_count 反映真实全量、端到端耗时在可接受界限内。

seed 复用 tests/test_recent_changes_detail_service.py 的
`_seed_import_batch_with_n_changes` 约定；authed client 复用
tests/test_history_recent_changes_api.py 的 real_app + X-Upload-Token。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import insert

from app.models import StockpileChange, StockpileSnapshot
from app.repositories import stockpile_db


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


_AUTH = {"X-Upload-Token": "test-token-123"}


def _seed_import_batch_with_n_changes(n: int) -> int:
    """import 批次 + n 条 DISTINCT (barcode, field) changes（raw 不折叠 → n 行）。

    镜像 tests/test_recent_changes_detail_service.py 的同名 helper。
    """
    with stockpile_db._session() as session:
        result = session.execute(
            insert(StockpileSnapshot).values(
                taken_at="2026-04-29 14:00:00", trigger="import", total_local=0
            )
        )
        bid = result.inserted_primary_key[0]
        for i in range(n):
            session.execute(
                insert(StockpileChange).values(
                    product_barcode=f"B{i}",
                    field_name="stockpile_location",
                    old_value="A1",
                    new_value="A2",
                    change_type="update",
                    created_at=f"2026-04-29 13:00:{i % 60:02d}.{i:06d}",
                )
            )
        session.commit()
    return bid


def test_large_batch_raw_perf_cap_and_total(real_app):
    n = 5000
    with real_app.app_context():
        bid = _seed_import_batch_with_n_changes(n)

    client = real_app.test_client()
    start = time.perf_counter()
    r = client.get(f"/api/history/recent-changes/{bid}/changes?mode=raw", headers=_AUTH)
    elapsed = time.perf_counter() - start
    print(f"\n[PERF] /recent-changes/{bid}/changes?mode=raw n={n} elapsed={elapsed:.4f}s")

    assert r.status_code == 200
    body = r.get_json()
    assert len(body["changes"]) == 500, "服务端 cap _RC_MAX_ROWS=500"
    assert body["total_count"] >= 5000, f"全量计数应 >=5000，实测 {body['total_count']}"

    # 端到端耗时界限。目标 < 1.0s（plan 性能验收）。
    # 若 DB 读取本身成为瓶颈（无 SQL 级 LIMIT），放宽到 < 3.0s 守护病态回归，
    # 并将 SQL 级 LIMIT 列为 backlog（见 spec §服务端 cap）。
    assert elapsed < 1.0, (
        f"端到端耗时 {elapsed:.3f}s 超过 1.0s 目标；若稳定超标，SQL 级 LIMIT 应排 backlog"
    )
