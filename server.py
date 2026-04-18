import socket

from flask import Flask

import storage_service
from config import CONFIG
from routes import register_routes
from state import INPUT_DIR, OUTPUT_DIR, TRANSFER_DIR


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(CONFIG.templates_dir))

    for folder in (INPUT_DIR, OUTPUT_DIR, TRANSFER_DIR, CONFIG.trash_dir):
        folder.mkdir(exist_ok=True)

    storage_service.startup_cleanup()
    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "127.0.0.1"
    print(f"\n服务已启动，A机浏览器访问：http://{ip}:{CONFIG.port}\n")
    app.run(host=CONFIG.host, port=CONFIG.port, debug=CONFIG.debug)
