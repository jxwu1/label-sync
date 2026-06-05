"""forecast/refresh 鉴权契约回归.

2026-06-05 发现: forecast-cron 容器的 curl 不带 X-Upload-Token, 被
auth.before_request 302 重定向到 /login, 而 curl -fsS 不跟跳转也不报错 ->
每天预测刷新静默空转. 修复是给 cron 注入并携带 token. 这里锁住两端契约:
  - 无 token -> 302 到登录页 (复现原 bug 的拦截路径)
  - 带非空 token -> 直达 handler 执行刷新 (cron 修复后的路径)

端点自身无鉴权, 完全依赖 before_request; test_routes_analytics 只挂裸蓝图、
不接 init_auth, 覆盖不到这层, 故单列本文件用整 app(create_app) 测.
"""

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


def test_forecast_refresh_with_nonempty_token_reaches_handler():
    client = _client()
    stats = {"n_total": 0, "n_written": 0, "n_skipped": 0}

    with (
        patch("app.services.forecast.refresh_forecast_output", return_value=stats) as m_refresh,
        patch("app.services.analytics.refresh_sku_summary") as m_summary,
    ):
        resp = client.post(
            "/analytics/forecast/refresh",
            headers={"X-Upload-Token": "any-nonempty-value"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    m_refresh.assert_called_once()
    m_summary.assert_called_once()
