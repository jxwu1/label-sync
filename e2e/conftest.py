"""E2E 浏览器烟雾测试 fixtures。

要点：
- 整个会话用一份沙箱目录隔离生产 input/output/transfer/attendance/monthly_summary/DB。
- Flask app 跑在守护线程里，端口 0 自动选；fixture 返回 base_url。
- 沙箱配置必须在导入 server / state / 各 service 之前生效，否则模块顶层
  常量（INPUT_DIR / DB_PATH / _ATTENDANCE_DIR ...）会被永久 bake 到生产路径。
"""

import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

# === 沙箱配置（必须早于任何 server / service 导入） ===


def _build_sandbox(root: Path) -> None:
    """在 root 下建出生产代码会用到的子目录，并把全局常量重定向过去。

    生产代码用两套定位方式：
    1. CONFIG.base_dir 派生（input / output / transfer / archive / stockpile.db）
       → 改 CONFIG.base_dir 即可一次性重定向
    2. Path(__file__).parent 派生（attendance/, monthly_summary/）
       → 必须直接 monkeypatch 服务模块里的常量
    """
    for name in ("input", "output", "transfer", "archive", "attendance", "monthly_summary"):
        (root / name).mkdir(parents=True, exist_ok=True)

    # CONFIG 是 frozen dataclass，绕过 __setattr__ 改 base_dir
    from app import config

    object.__setattr__(config.CONFIG, "base_dir", root)

    # 服务模块里 hardcoded 路径
    from app.services import attendance as attendance_service
    from app.services import monthly_summary as monthly_summary_service
    attendance_service._ATTENDANCE_DIR = root / "attendance"
    monthly_summary_service._SUMMARY_DIR = root / "monthly_summary"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def live_server(tmp_path_factory) -> str:
    """启动 Flask app 在 daemon 线程上，返回 base_url（http://127.0.0.1:<port>）。"""
    sandbox = tmp_path_factory.mktemp("e2e_sandbox")
    _build_sandbox(sandbox)

    # 沙箱就绪后再导入 server（其会触发 state / stockpile_db / route blueprint 加载）
    # 任何"在 conftest 顶层就 import server"的写法都会把生产路径 bake 进去
    if "server" in sys.modules:
        del sys.modules["server"]
    import server

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    from werkzeug.serving import make_server

    httpd = make_server("127.0.0.1", port, server.app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    # 等 / 返回 200，最多 5s
    deadline = time.time() + 5.0
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/", timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception as exc:
            last_err = exc
            time.sleep(0.1)
    else:
        httpd.shutdown()
        raise RuntimeError(f"Flask 启动 5s 内未就绪：{last_err}")

    yield base_url

    httpd.shutdown()


# === Playwright page 包装：自动收集 console 错误 ===


@pytest.fixture
def page_with_console(page):
    """page fixture 增强：附加 .console_errors 列表。

    用法：
        def test_x(page_with_console):
            page = page_with_console
            page.goto(...)
            ...
            assert page.console_errors == []
    """
    errors: list[str] = []

    def on_console(msg) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", on_console)
    page.console_errors = errors  # type: ignore[attr-defined]
    return page
