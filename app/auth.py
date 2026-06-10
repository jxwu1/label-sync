"""Flask-Login 初始化 + 登录/注销路由 + seed 首用户."""

import os
import secrets
from functools import wraps

import bcrypt
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from app.config import CONFIG
from app.models import SystemSetting, User, get_session

login_manager = LoginManager()
login_manager.login_view = "auth.login"

# 仅本地 debug 回退用; 生产缺 FLASK_SECRET_KEY 会 fail-fast, 不会落到这个值.
_DEV_SECRET = "label-sync-dev-secret-change-in-prod"


def _resolve_secret_key(debug: bool) -> str:
    """Flask session secret. 优先 env; 本地 debug 回退 dev 默认; 生产缺失则拒启.

    生产用固定/可猜 secret 会让登录 session cookie 可伪造, 故 fail-fast.
    """
    env_secret = os.environ.get("FLASK_SECRET_KEY")
    if env_secret:
        return env_secret
    if debug:
        return _DEV_SECRET
    raise RuntimeError(
        "FLASK_SECRET_KEY 未注入: 生产拒绝使用可伪造的默认 secret. 请在部署环境(Coolify) "
        '注入一个随机值, 例如 `python -c "import secrets; print(secrets.token_hex(32))"`.'
    )


bp = Blueprint("auth", __name__)


def cache_control_header(path: str, content_type: str | None) -> str | None:
    """决定响应的 Cache-Control。

    - HTML：完全不缓存（页面必须每次拿最新）。
    - 静态 JS/CSS：允许缓存但每次向服务器校验（no-cache → ETag/304）。部署新版后
      浏览器自动取到新文件，无需手动强刷；未变则回 304 几乎零开销。ES 模块内部
      import 的子文件同样走这条，挂标签版号覆盖不到的它也覆盖。
    """
    if content_type and "text/html" in content_type:
        return "no-store, no-cache, must-revalidate, max-age=0"
    if path.startswith("/static/"):
        return "no-cache"
    return None


def require_role(role: str):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                abort(401)
            if getattr(current_user, "role", None) != role:
                abort(403)
            return fn(*args, **kwargs)

        return wrapped

    return deco


def require_upload_token(fn):
    """重任务 / mutation 端点鉴权: 强制 X-Upload-Token 与 env UPLOAD_TOKEN 常时间相等.

    before_request 已是全局登录闸(正确 token 或 session 才放行), 本装饰器是叠加的
    端点级闸: 这些 cron/破坏性端点【只认 token, 不接受纯 session】—— 即便已登录
    admin 也必须带正确 token 才能触发 (防浏览器 session/XSS 误触发全量 backtest/删数据).
    cron 端点与破坏性端点共用此装饰器, 取代各端点内联重复的 compare_digest 块.
    缺 env -> 500(服务器配置错); token 不匹配/缺失 -> 401.
    """

    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = os.environ.get("UPLOAD_TOKEN", "")
        if not expected:
            return jsonify({"ok": False, "msg": "服务器 UPLOAD_TOKEN 未配置"}), 500
        provided = request.headers.get("X-Upload-Token", "")
        if not secrets.compare_digest(provided, expected):
            return jsonify({"ok": False, "msg": "无效或缺失 X-Upload-Token"}), 401
        return fn(*args, **kwargs)

    return wrapped


def init_auth(app, *, seed_users: bool = True):
    app.secret_key = app.secret_key or _resolve_secret_key(CONFIG.debug)
    login_manager.init_app(app)
    app.register_blueprint(bp)
    if seed_users:
        _seed_admin()
        _seed_scanner()

    @app.before_request
    def _require_login():
        if request.endpoint and request.endpoint.startswith("auth."):
            return
        if request.endpoint == "static":
            return
        # 全局鉴权闸. 带 X-Upload-Token 的是 API/cron 客户端(无 session): 正确->放行;
        # 错误->401; 服务端没配 UPLOAD_TOKEN->500. 一律【不重定向】—— cron 的 curl -fsS
        # 对 3xx 不算失败, 用 302 会让错 token / 缺配静默成功(复现 #5 静默空转), 故必须是
        # 响亮的 4xx/5xx. 只有【完全没带 token】的浏览器请求才走下面的登录重定向.
        token = request.headers.get("X-Upload-Token")
        if token:
            expected = os.environ.get("UPLOAD_TOKEN", "")
            if not expected:
                return jsonify({"ok": False, "msg": "服务器 UPLOAD_TOKEN 未配置"}), 500
            if secrets.compare_digest(token, expected):
                return
            return jsonify({"ok": False, "msg": "无效 X-Upload-Token"}), 401
        if current_user.is_authenticated and getattr(current_user, "role", "admin") == "scanner":
            ep = request.endpoint or ""
            if not (ep.startswith("pda.") or ep.startswith("auth.") or ep == "static"):
                return redirect(url_for("pda.scan_page"))
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))

    @app.after_request
    def _apply_cache_control(response):
        cc = cache_control_header(request.path or "", response.content_type)
        if cc:
            response.headers["Cache-Control"] = cc
        return response


@login_manager.user_loader
def _load_user(user_id: str) -> User | None:
    with get_session() as s:
        return s.get(User, int(user_id))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _seed_scanner():
    with get_session() as s:
        if s.query(User).filter_by(role="scanner").count() > 0:
            return
        pw = os.environ.get("PDA_SEED_PASSWORD") or secrets.token_urlsafe(12)
        s.add(
            User(
                username="pda",
                password_hash=hash_password(pw),
                display_name="PDA 扫描",
                theme="light",
                role="scanner",
            )
        )
        print(
            f"[pda-seed] 已创建扫描账号 'pda'，初始密码: {pw}（请在系统管理里尽快修改）", flush=True
        )


def _seed_admin():
    with get_session() as s:
        if s.query(User).count() > 0:
            return
        admin = User(
            username="admin",
            password_hash=hash_password("admin"),
            display_name="管理员",
            theme="dark",
            role="admin",
        )
        s.add(admin)
        defaults = {
            "cn_exchange_rate_rmb_per_eur": "7.8",
            "cn_shipping_rate_rmb_per_m3": "1000.0",
            "retail_to_wholesale_ratio": "2.0",
        }
        for k, v in defaults.items():
            if not s.get(SystemSetting, k):
                s.add(SystemSetting(key=k, value=v, updated_by="seed"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    from flask import jsonify

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        if not user or not check_password(password, user.password_hash):
            return jsonify(ok=False, error="用户名或密码错误"), 401
        login_user(user, remember=True)
        theme = user.theme
        s.expunge(user)

    next_url = request.args.get("next") or url_for("pages_tasks.index")
    return jsonify(ok=True, theme=theme, next=next_url)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
