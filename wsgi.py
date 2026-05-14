"""WSGI 入口 (生产部署用).

Docker / waitress / gunicorn 都通过这里加载 Flask app.
开发仍可以直接 `python server.py`.
"""
from server import app  # noqa: F401

if __name__ == "__main__":
    import os

    from waitress import serve

    serve(
        app,
        host=os.environ.get("LABEL_SYNC_HOST", "0.0.0.0"),
        port=int(os.environ.get("LABEL_SYNC_PORT", "5000")),
        threads=int(os.environ.get("LABEL_SYNC_THREADS", "4")),
    )
