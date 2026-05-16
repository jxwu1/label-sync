import socket

from flask import Flask

import monthly_summary_service
from app.repositories import stockpile_db
import storage_service
from app.config import CONFIG
from routes import register_routes
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
