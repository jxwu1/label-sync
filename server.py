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
    # 本地 debug 时模板改动即时生效，不必重启（生产 debug=False，模板缓存照旧）。
    app.config["TEMPLATES_AUTO_RELOAD"] = CONFIG.debug

    # 运行时目录：startup_cleanup 会无条件遍历 INPUT/TRANSFER，故一并建全；
    # parents=True 让全新数据目录（LABEL_SYNC_DATA_DIR 指向不存在路径时）也能起。
    for folder in (INPUT_DIR, OUTPUT_DIR, CONFIG.trash_dir, TRANSFER_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    storage_service.startup_cleanup()
    stockpile_db.ensure_db()
    monthly_summary_service.cleanup_expired()
    from app.auth import init_auth

    init_auth(app)
    register_routes(app)

    # 2026-05-23: 预热避免冷启动首请求 30s+ 等待.
    # 2026-06-03: 改 prewarm_sku_summary —— 物化表空/过期则重建落表, 否则只暖缓存.
    # 后台线程跑, 不阻塞 app 启动 (waitress 立即 accept 请求, 几秒后表/缓存填好).
    import threading

    def _prewarm_cache():
        try:
            from app.services import analytics

            analytics.prewarm_sku_summary()
        except Exception:
            import logging

            logging.exception("sku_summary prewarm 失败")

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
