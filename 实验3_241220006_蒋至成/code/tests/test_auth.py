"""账号注册、密码存储与登录锁定测试。"""

# pylint: disable=missing-function-docstring

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from takeout.container import Container
from takeout.errors import AccountLockedError, AuthError, ConflictError, ValidationError
from takeout.utils import now


class AuthTest(unittest.TestCase):
    """REQ-001、REQ-016 的账号安全测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.app = Container(Path(self._tmp.name) / "auth.db")
        self.auth = self.app.auth

    def tearDown(self) -> None:
        self.app.close()
        self._tmp.cleanup()

    def test_register_and_duplicate_phone(self) -> None:
        user = self.auth.register_customer("13700000001", "abc123", "地址")
        self.assertEqual(user.phone, "13700000001")
        with self.assertRaises(ConflictError):
            self.auth.register_customer("13700000001", "abc123")

    def test_password_is_hashed(self) -> None:
        self.auth.register_customer("13700000002", "secret123")
        user = self.app.users.get_by_phone("13700000002")
        self.assertNotEqual(user.password_hash, "secret123")
        self.assertTrue(user.password_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.verify_password("secret123"))
        self.assertFalse(user.verify_password("wrong"))

    def test_validate_phone_and_password(self) -> None:
        with self.assertRaises(ValidationError):
            self.auth.register_customer("123", "abc123")
        with self.assertRaises(ValidationError):
            self.auth.register_customer("13700000003", "123")

    def test_account_locks_after_five_failures(self) -> None:
        self.auth.register_customer("13700000004", "right123")
        for _ in range(4):
            with self.assertRaises(AuthError):
                self.auth.login("13700000004", "wrong")
        with self.assertRaises(AccountLockedError):
            self.auth.login("13700000004", "wrong")
        with self.assertRaises(AccountLockedError):
            self.auth.login("13700000004", "right123")
        later = now() + timedelta(minutes=11)
        token = self.auth.login("13700000004", "right123", moment=later)
        self.assertEqual(token.session.phone, "13700000004")

    def test_merchant_registration_creates_pending_shop(self) -> None:
        user = self.auth.register_merchant(
            "13700000005", "abc123", "新店铺", "LIC-002"
        )
        self.assertIsNotNone(user.shop_id)
        shop = self.app.shops.get(user.shop_id)
        self.assertEqual(str(shop.status), "待审核")

    def test_login_returns_resolvable_token(self) -> None:
        self.auth.register_customer("13700000006", "abc123")
        token = self.auth.login("13700000006", "abc123")
        session = self.auth.resolve(token.value)
        self.assertEqual(session.role.value, "顾客")
        self.auth.logout(token.value)
        with self.assertRaises(AuthError):
            self.auth.resolve(token.value)
