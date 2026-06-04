"""幂等 scanner seed 测试：_seed_scanner() 调两次只建一条记录。"""

import unittest

import app.auth as auth_mod
import app.models as models_mod


class SeedScannerTests(unittest.TestCase):
    # DB 隔离由 conftest autouse 提供（tmp sqlite，经 app.db engine）。

    def _scanner_count(self):
        with models_mod.get_session() as s:
            return s.query(models_mod.User).filter_by(role="scanner").count()

    def test_seed_creates_one_scanner(self):
        auth_mod._seed_scanner()
        self.assertEqual(self._scanner_count(), 1)

    def test_seed_idempotent(self):
        auth_mod._seed_scanner()
        auth_mod._seed_scanner()
        self.assertEqual(self._scanner_count(), 1)

    def test_seed_username_and_role(self):
        auth_mod._seed_scanner()
        with models_mod.get_session() as s:
            u = s.query(models_mod.User).filter_by(role="scanner").one()
        self.assertEqual(u.username, "pda")
        self.assertEqual(u.role, "scanner")

    def test_seed_skips_when_scanner_already_exists(self):
        """如果已有 scanner（非 pda），不应再新建。"""
        with models_mod.get_session() as s:
            s.add(
                models_mod.User(
                    username="other_scanner",
                    password_hash=auth_mod.hash_password("x"),
                    display_name="Other",
                    theme="light",
                    role="scanner",
                )
            )
        auth_mod._seed_scanner()
        self.assertEqual(self._scanner_count(), 1)


if __name__ == "__main__":
    unittest.main()
