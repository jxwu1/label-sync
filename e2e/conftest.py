"""E2E 浏览器烟雾测试 fixtures。

要点：
- 整个会话用一份沙箱目录隔离生产 input/output/transfer/attendance/monthly_summary/DB。
- Flask app 跑在守护线程里，端口 0 自动选；fixture 返回 base_url。
- 沙箱配置 + 认证 env 必须在 create_app() **之前**生效：init_auth 在 create_app 内
  执行，secret/seed 一旦 bake 就改不动；非 debug 时缺 FLASK_SECRET_KEY 会 fail-fast。
- /ui/* 由本测试 harness 直接 serve frontend/dist（构建产物 + SPA fallback + 同源
  Flask /api/*）。**这不是生产 Caddy/nginx 剥前缀反代的仿真**——剥前缀语义归部署 smoke。
  frontend/dist 被 gitignore：跑 /ui smoke 前必须先 `npm run build`（CI 有构建步骤；
  本地标准命令 = `npm run build` → `pytest e2e/`，不能声称裸 `pytest e2e/` 自包含）。
"""

import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = _REPO_ROOT / "frontend" / "dist"
DIST_INDEX = DIST_DIR / "index.html"

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


def _register_ui_static(app) -> None:
    """把 frontend/dist 挂到 /ui/*：实文件走 send_from_directory，其余前端路由 fallback
    index.html（Vue history 路由）。`/api/*` 等仍由原 Flask 蓝图处理——本规则只接 /ui 前缀。
    """
    from flask import send_from_directory

    def _serve_ui(subpath: str = ""):
        candidate = (DIST_DIR / subpath).resolve()
        # 实文件（资产 chunk）直接发；带防目录穿越校验
        if subpath and candidate.is_file() and (candidate == DIST_DIR / subpath):
            try:
                candidate.relative_to(DIST_DIR)
            except ValueError:
                return send_from_directory(DIST_DIR, "index.html")
            return send_from_directory(DIST_DIR, candidate.relative_to(DIST_DIR).as_posix())
        # 前端路由（无对应文件）→ SPA fallback
        return send_from_directory(DIST_DIR, "index.html")

    app.add_url_rule("/ui", "_e2e_ui_root", _serve_ui)
    app.add_url_rule("/ui/", "_e2e_ui_slash", _serve_ui)
    app.add_url_rule("/ui/<path:subpath>", "_e2e_ui_path", _serve_ui)


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

    # DB 隔离（必须早于任何 app 导入）：**强制覆盖**任何继承的 DATABASE_URL——从 dev.ps1
    # 环境跑时它会指向本地 PG，app/db.py `_effective_url` 认此 env，e2e 的 seed/写入会污染
    # 真实库（员工/假日/PDA）。这里钉到沙箱内一次性 sqlite，绝不碰真实库。
    os.environ["DATABASE_URL"] = "sqlite:///" + (sandbox / "e2e.db").as_posix()
    # 认证 env 也必须早于 create_app（init_auth 在内部 bake secret + seed admin）。
    os.environ.setdefault("FLASK_SECRET_KEY", "e2e-test-secret-key")
    os.environ.setdefault("UPLOAD_TOKEN", "e2e-test-upload-token")

    _build_sandbox(sandbox)

    # 沙箱就绪后再导入 server（其会触发 state / stockpile_db / route blueprint 加载）
    # 任何"在 conftest 顶层就 import server"的写法都会把生产路径 bake 进去
    if "server" in sys.modules:
        del sys.modules["server"]
    import server

    # 清掉可能已用继承 URL 建好的 engine 缓存（_build_sandbox 链式 import 时可能已建），
    # 确保引擎指向沙箱 sqlite，再建表 —— 显式 reset_engine + ensure_db。
    from app import db as app_db

    app_db.reset_engine()
    app_db.ensure_db()

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    from werkzeug.serving import make_server

    app = server.create_app(seed_auth=True, prewarm=False)
    _register_ui_static(app)
    httpd = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    # 等 /login 返回 200（无需鉴权，比 / 更直接——/ 未登录会 302），最多 5s
    deadline = time.time() + 5.0
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/login", timeout=1) as resp:
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


# === 登录态 + Playwright page 包装 ===


@pytest.fixture
def logged_in_page(live_server, page):
    """浏览器上下文用 seed admin（admin/admin）登录，session cookie 落到 context。

    `page.request` 与浏览器 context 共享 cookie jar：POST /login 后 page.goto 自带 session。
    """
    resp = page.request.post(
        live_server + "/login",
        form={"username": "admin", "password": "admin"},
    )
    assert resp.ok, f"e2e 登录失败: {resp.status} {resp.text()}"
    return page


@pytest.fixture
def page_with_console(logged_in_page):
    """已登录 page + 附加 .console_errors 列表（监听器在任何 goto 之前挂上）。

    依赖 logged_in_page，确保所有用此 fixture 的测试自动带登录态，不再撞登录墙。

    用法：
        def test_x(live_server, page_with_console):
            page = page_with_console
            page.goto(...)
            assert page.console_errors == []
    """
    page = logged_in_page
    errors: list[str] = []

    def on_console(msg) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", on_console)
    page.console_errors = errors  # type: ignore[attr-defined]
    return page
