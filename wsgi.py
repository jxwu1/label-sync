"""WSGI 入口 (生产部署用).

Docker / waitress / gunicorn 都通过这里加载 Flask app.
开发仍可以直接 `python server.py`.
"""

from server import create_app

app = create_app()

if __name__ == "__main__":
    import os

    from waitress import serve

    # threads 默认 16 (2026-05-23 提升, 原 4 在 list_sku_summary 慢端点
    # 期间会堆积 queue depth=10+, 导致 Coolify healthcheck 排队超时 → 误判
    # 部署失败). 27k SKU 列表慢请求 ~2-3s, 16 线程能扛并发健康检查 + 用户访问.
    serve(
        app,
        host=os.environ.get("LABEL_SYNC_HOST", "0.0.0.0"),
        port=int(os.environ.get("LABEL_SYNC_PORT", "5000")),
        threads=int(os.environ.get("LABEL_SYNC_THREADS", "16")),
    )
