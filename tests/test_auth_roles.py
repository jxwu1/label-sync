import unittest
from unittest import mock

from werkzeug.exceptions import Forbidden, Unauthorized

import app.auth as authmod


class _U:
    def __init__(self, role, auth=True):
        self.role = role
        self.is_authenticated = auth


class RequireRoleTests(unittest.TestCase):
    def _wrapped(self):
        @authmod.require_role("admin")
        def _view():
            return "ok"

        return _view

    def test_admin_allowed(self):
        with mock.patch.object(authmod, "current_user", _U("admin")):
            self.assertEqual(self._wrapped()(), "ok")

    def test_scanner_forbidden(self):
        with mock.patch.object(authmod, "current_user", _U("scanner")):
            with self.assertRaises(Forbidden):
                self._wrapped()()

    def test_anon_unauthorized(self):
        with mock.patch.object(authmod, "current_user", _U("admin", auth=False)):
            with self.assertRaises(Unauthorized):
                self._wrapped()()


class CacheControlHeaderTests(unittest.TestCase):
    def test_html_is_no_store(self):
        cc = authmod.cache_control_header("/", "text/html; charset=utf-8")
        self.assertIn("no-store", cc)

    def test_static_revalidates(self):
        # 静态资源：no-cache（每次向服务器校验，部署后免强刷），非 no-store（仍可 304）
        self.assertEqual(
            authmod.cache_control_header("/static/js/index.js", "application/javascript"),
            "no-cache",
        )

    def test_static_covers_imported_submodule(self):
        # ES 模块内部 import 的子文件也走静态路径 → 同样 no-cache
        self.assertEqual(
            authmod.cache_control_header("/static/js/shared.js", "text/javascript"),
            "no-cache",
        )

    def test_other_responses_untouched(self):
        self.assertIsNone(authmod.cache_control_header("/admin/api/x", "application/json"))
