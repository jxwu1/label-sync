import socket

from flask import Flask

from app.services import monthly_summary as monthly_summary_service
from app.repositories import stockpile_db
from app.services import storage as storage_service
from app.config import CONFIG
from app.routes import register_routes
from app.state import INPUT_DIR, OUTPUT_DIR, TRANSFER_DIR


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(CONFIG.templates_dir))

    dirs = [INPUT_DIR, OUTPUT_DIR, CONFIG.trash_dir]
    if CONFIG.enable_transfer:
        dirs.append(TRANSFER_DIR)
    for folder in dirs:
        folder.mkdir(exist_ok=True)

    storage_service.startup_cleanup()
    stockpile_db.ensure_db()
    monthly_summary_service.cleanup_expired()
    register_routes(app)

    # 2026-05-23: 预热 list_sku_summary 缓存避免冷启动首请求 30s+ 等待.
    # 后台线程跑, 不阻塞 app 启动 (waitress 立即 accept 请求, 几秒后缓存填好).
    import threading

    def _prewarm_cache():
        try:
            from app.services import analytics
            analytics.list_sku_summary()
        except Exception:
            import logging
            logging.exception("list_sku_summary prewarm 失败")

    threading.Thread(target=_prewarm_cache, daemon=True, name="cache-prewarm").start()

    return app


app = create_app()


if __name__ == "__main__":
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "127.0.0.1"
    mode = "双端" if CONFIG.enable_transfer else "单端"
    print(f"\n服务已启动（{mode}模式），浏览器访问：http://{ip}:{CONFIG.port}\n")
    app.run(host=CONFIG.host, port=CONFIG.port, debug=CONFIG.debug)
