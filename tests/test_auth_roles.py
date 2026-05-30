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
