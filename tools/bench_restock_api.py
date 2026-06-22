"""补货页后端 perf 门槛：/api/restock/items（投影 + strict 校验）vs 旧 /analytics/list（胖）。

两端同源 list_sku_summary()（60s 缓存），差异 = 新端点每请求的投影 + pydantic 27k 行
校验开销。同机同数据集，预热 3 / 计时 10 取 p50，断言 ratio ≤ 1.3。

跑前置：DATABASE_URL 指向有真实量级数据的库（本地灌 prod DB）。dev.ps1 环境下：
    DATABASE_URL=postgresql+psycopg://dev:devpass@localhost:5433/label_sync python tools/bench_restock_api.py
把输出 ratio 贴进 PR 描述。
"""

from __future__ import annotations

import os
import statistics
import time

os.environ.setdefault("UPLOAD_TOKEN", "bench-upload-token")
os.environ.setdefault("FLASK_SECRET_KEY", "bench-local-secret-key")
_HEADERS = {"X-Upload-Token": os.environ["UPLOAD_TOKEN"]}


def _p50(client, path: str, warm: int = 3, n: int = 10) -> float:
    for _ in range(warm):
        client.get(path, headers=_HEADERS)
    samples = []
    for _ in range(n):
        t = time.perf_counter()
        resp = client.get(path, headers=_HEADERS)
        samples.append(time.perf_counter() - t)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    return statistics.median(samples)


def main() -> None:
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    client = app.test_client()

    old = _p50(client, "/analytics/list")
    new = _p50(client, "/api/restock/items")
    ratio = new / old if old > 0 else float("inf")
    print(
        f"/analytics/list p50={old * 1000:.0f}ms  "
        f"/api/restock/items p50={new * 1000:.0f}ms  ratio={ratio:.2f}"
    )
    assert new <= old * 1.3, (
        f"items p50 {new:.3f}s > analytics {old:.3f}s ×1.3（投影/校验开销超标）"
    )
    print("OK: ratio ≤ 1.3")


if __name__ == "__main__":
    main()
