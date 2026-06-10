"""alerts/check 鉴权契约 (镜像 test_cron_forecast_auth.py 的 4 态矩阵)。

无 token → 302 /login; 错 token → 401; 缺 env 且带 token → 500; 正确 token → 200。
"""

import os
from unittest.mock import patch

from server import create_app


def _client():
    app = create_app(seed_auth=False, prewarm=False)
    app.config["TESTING"] = True
    return app.test_client()


def test_alerts_check_without_token_redirected_to_login():
    resp = _client().post("/analytics/alerts/check")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_alerts_check_wrong_token_401():
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().post("/analytics/alerts/check", headers={"X-Upload-Token": "wrong"})
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)
    assert resp.status_code == 401


def test_alerts_check_token_present_but_server_unconfigured_500():
    os.environ.pop("UPLOAD_TOKEN", None)
    resp = _client().post("/analytics/alerts/check", headers={"X-Upload-Token": "whatever"})
    assert resp.status_code == 500


def test_alerts_check_correct_token_200_shape():
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    payload = {"ok": True, "alerts": [], "sent": False, "suppressed_reason": None}
    try:
        with patch("app.services.alerts.run_alerts_check", return_value=payload) as m:
            resp = _client().post(
                "/analytics/alerts/check", headers={"X-Upload-Token": "secret_token_abc"}
            )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"ok", "alerts", "sent", "suppressed_reason"}
    m.assert_called_once()
