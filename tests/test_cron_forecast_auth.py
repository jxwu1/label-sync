"""forecast/refresh 鉴权契约回归.

2026-06-05 发现: forecast-cron 容器的 curl 不带 X-Upload-Token, 被
auth.before_request 302 重定向到 /login, 而 curl -fsS 不跟跳转也不报错 ->
每天预测刷新静默空转. 修复是给 cron 注入并携带 token. 这里锁住两端契约:
  - 无 token -> 302 到登录页 (复现原 bug 的拦截路径)
  - 带非空 token -> 直达 handler 执行刷新 (cron 修复后的路径)

端点自身无鉴权, 完全依赖 before_request; test_routes_analytics 只挂裸蓝图、
不接 init_auth, 覆盖不到这层, 故单列本文件用整 app(create_app) 测.
"""

import os
from unittest.mock import patch

from server import create_app


def _client():
    app = create_app(seed_auth=False, prewarm=False)
    app.config["TESTING"] = True
    return app.test_client()


def test_forecast_refresh_without_token_is_redirected_to_login():
    resp = _client().post("/analytics/forecast/refresh")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_forecast_refresh_with_correct_token_reaches_handler():
    client = _client()
    stats = {"n_total": 0, "n_written": 0, "n_skipped": 0}

    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        with (
            patch("app.services.forecast.refresh_forecast_output", return_value=stats) as m_refresh,
            patch("app.services.analytics.refresh_sku_summary") as m_summary,
        ):
            resp = client.post(
                "/analytics/forecast/refresh",
                headers={"X-Upload-Token": "secret_token_abc"},
            )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    m_refresh.assert_called_once()
    m_summary.assert_called_once()


def test_forecast_refresh_wrong_token_rejected():
    # 错 token 必须响亮 401 (不是 302): cron 的 curl -fsS 对 3xx 不算失败,
    # 302 会让错 token / 缺配静默成功, 复现 #5 静默空转.
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().post(
            "/analytics/forecast/refresh",
            headers={"X-Upload-Token": "wrong"},
        )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_token_present_but_server_unconfigured_is_500():
    # web 容器没注入 UPLOAD_TOKEN 时, cron 带 token 请求 -> 500 (响亮), 而非静默放行/302.
    os.environ.pop("UPLOAD_TOKEN", None)
    resp = _client().post(
        "/analytics/forecast/refresh",
        headers={"X-Upload-Token": "whatever"},
    )

    assert resp.status_code == 500
    assert resp.get_json()["ok"] is False


# 第1期⑤: backtest/refresh 全量重任务. 鉴权契约(全局 before_request 闸):
#   没带 token (浏览器) -> 302 登录; 带 token 但错 -> 401(响亮); 正确 token / 登录 session -> 直达.
def test_backtest_refresh_without_token_is_redirected_to_login():
    resp = _client().post("/analytics/backtest/refresh")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_backtest_refresh_wrong_token_rejected():
    # 非空但错误 token -> 响亮 401 (不绕过登录, 也不 302; curl -fsS 会失败).
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().post(
            "/analytics/backtest/refresh",
            headers={"X-Upload-Token": "wrong"},
        )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_wrong_token_does_not_bypass_login_on_undecorated_route():
    # [High] 回归: 任意非空 token 曾能全局绕过登录. 现在【未加 decorator 的普通端点】
    # 带错误 token 也必须被 before_request 响亮拦下(401), 既不进 handler 也不静默放行.
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().get(
            "/analytics/backtest/dashboard",
            headers={"X-Upload-Token": "wrong"},
        )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 401


def test_backtest_refresh_with_correct_token_reaches_handler():
    client = _client()

    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        with patch("app.services.backtest.run_backtest_all_skus", return_value=99) as m_run:
            resp = client.post(
                "/analytics/backtest/refresh",
                headers={"X-Upload-Token": "secret_token_abc"},
            )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    m_run.assert_called_once()
    # 固定跑 forecast 实际使用的 EmpiricalQuantile / base_demand
    _, kwargs = m_run.call_args
    assert kwargs["model_name"] == "EmpiricalQuantile"
    assert kwargs["view"] == "base_demand"


def test_scrape_heartbeat_without_token_redirected_to_login():
    resp = _client().post("/analytics/scrape/heartbeat")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_scrape_heartbeat_wrong_token_rejected():
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().post(
            "/analytics/scrape/heartbeat",
            headers={"X-Upload-Token": "wrong"},
        )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_scrape_heartbeat_server_unconfigured_is_500():
    os.environ.pop("UPLOAD_TOKEN", None)
    resp = _client().post(
        "/analytics/scrape/heartbeat",
        headers={"X-Upload-Token": "whatever"},
    )

    assert resp.status_code == 500
    assert resp.get_json()["ok"] is False
