import _env  # noqa: F401

import hashlib
import unittest
from unittest import mock

from common import db, variable
from common.services import admin_auth


class FakeRequest:
    def __init__(self, token=None):
        self.cookies = {admin_auth.COOKIE_NAME: token} if token else {}


class PasswordHashTest(unittest.TestCase):
    def test_hash_is_salted_and_verifies(self):
        first = db.hash_password('s3cret-pass')
        second = db.hash_password('s3cret-pass')
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith(('scrypt$', 'pbkdf2$')))
        self.assertEqual(db.verify_password('s3cret-pass', first), (True, False))
        self.assertEqual(db.verify_password('wrong', first), (False, False))

    def test_legacy_sha256_still_verifies_and_asks_for_upgrade(self):
        legacy = hashlib.sha256(b'old-pass').hexdigest()
        self.assertEqual(db.verify_password('old-pass', legacy), (True, True))
        self.assertEqual(db.verify_password('nope', legacy), (False, False))

    def test_garbage_hashes_do_not_raise(self):
        for stored in ('', None, 'scrypt$bad', 'pbkdf2$x$y$z', 'é' * 10):
            self.assertEqual(db.verify_password('x', stored), (False, False))

    def test_pbkdf2_fallback_format_verifies(self):
        with mock.patch.object(db.hashlib, 'scrypt', side_effect=ValueError('no scrypt'), create=True):
            stored = db.hash_password('fallback-pass')
        self.assertTrue(stored.startswith('pbkdf2$'))
        self.assertEqual(db.verify_password('fallback-pass', stored), (True, False))


class AuthenticateAdminTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_default_admin_from_environment_can_log_in(self):
        self.assertTrue(admin_auth.authenticate_admin(_env.ADMIN_USERNAME, _env.ADMIN_PASSWORD))
        self.assertFalse(admin_auth.authenticate_admin(_env.ADMIN_USERNAME, 'wrong'))
        self.assertFalse(admin_auth.authenticate_admin('nobody', _env.ADMIN_PASSWORD))

    def test_login_records_time_and_upgrades_legacy_hash(self):
        conn = db.get_connection()
        try:
            conn.execute('INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, 0)',
                         ('legacy', hashlib.sha256(b'legacy-pass').hexdigest()))
            conn.commit()
        finally:
            conn.close()
        self.assertTrue(admin_auth.authenticate_admin('legacy', 'legacy-pass'))
        conn = db.get_connection()
        try:
            row = conn.execute('SELECT password_hash, last_login_at FROM admins WHERE username = ?',
                               ('legacy',)).fetchone()
        finally:
            conn.close()
        self.assertTrue(row['password_hash'].startswith(('scrypt$', 'pbkdf2$')))
        self.assertIsNotNone(row['last_login_at'])
        self.assertTrue(admin_auth.authenticate_admin('legacy', 'legacy-pass'))  # 升级后仍可登录

    def test_update_password_rules(self):
        conn = db.get_connection()
        try:
            conn.execute('INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, 0)',
                         ('pwuser', db.hash_password('first-password')))
            conn.commit()
            admin_id = conn.execute('SELECT id FROM admins WHERE username = ?', ('pwuser',)).fetchone()['id']
        finally:
            conn.close()
        with self.assertRaises(ValueError):
            admin_auth.update_admin_password(admin_id, '   ')
        with self.assertRaises(ValueError):
            admin_auth.update_admin_password(admin_id, 'short')
        with self.assertRaises(ValueError):
            admin_auth.update_admin_password(999999, 'long-enough-password')
        self.assertEqual(admin_auth.update_admin_password(admin_id, 'a-new-password'), 'pwuser')
        self.assertTrue(admin_auth.authenticate_admin('pwuser', 'a-new-password'))
        self.assertFalse(admin_auth.authenticate_admin('pwuser', 'first-password'))


class LoginLimiterTest(unittest.TestCase):
    def setUp(self):
        admin_auth._login_failures.clear()

    def test_blocks_after_max_failures_and_expires(self):
        ip = '1.2.3.4'
        for i in range(admin_auth.LOGIN_MAX_FAILURES):
            self.assertFalse(admin_auth.login_blocked(ip, now=1000 + i))
            admin_auth.record_login_failure(ip, now=1000 + i)
        self.assertTrue(admin_auth.login_blocked(ip, now=1100))
        self.assertFalse(admin_auth.login_blocked('5.6.7.8', now=1100))
        self.assertFalse(admin_auth.login_blocked(ip, now=1000 + admin_auth.LOGIN_WINDOW_SECONDS + 10))

    def test_success_clears_failures_and_old_records_are_purged(self):
        admin_auth.record_login_failure('a', now=1000)
        admin_auth.record_login_failure('b', now=1000 + admin_auth.LOGIN_WINDOW_SECONDS + 1)
        self.assertNotIn('a', admin_auth._login_failures)  # 过期记录在下一次记录时被清掉
        admin_auth.clear_login_failures('b')
        self.assertNotIn('b', admin_auth._login_failures)


class SessionTest(unittest.TestCase):
    def setUp(self):
        variable.admin_sessions.clear()

    def test_session_roundtrip_and_destroy(self):
        token = admin_auth.create_session('admin')
        self.assertEqual(admin_auth.get_session(FakeRequest(token))['username'], 'admin')
        admin_auth.destroy_session(FakeRequest(token))
        self.assertIsNone(admin_auth.get_session(FakeRequest(token)))
        self.assertIsNone(admin_auth.get_session(FakeRequest()))

    def test_idle_and_absolute_expiry(self):
        with mock.patch.object(admin_auth.time, 'time', return_value=10_000):
            token = admin_auth.create_session('admin')
        with mock.patch.object(admin_auth.time, 'time', return_value=10_000 + admin_auth.SESSION_IDLE_SECONDS - 1):
            self.assertIsNotNone(admin_auth.get_session(FakeRequest(token)))  # 访问后顺延空闲时间
        with mock.patch.object(admin_auth.time, 'time', return_value=10_000 + 2 * admin_auth.SESSION_IDLE_SECONDS):
            self.assertIsNone(admin_auth.get_session(FakeRequest(token)))
        self.assertNotIn(token, variable.admin_sessions)

        with mock.patch.object(admin_auth.time, 'time', return_value=50_000):
            token = admin_auth.create_session('admin')
        # 一直有访问，但超过绝对有效期
        step = admin_auth.SESSION_IDLE_SECONDS - 1
        now = 50_000
        while now - 50_000 <= admin_auth.SESSION_MAX_SECONDS:
            now += step
            with mock.patch.object(admin_auth.time, 'time', return_value=now):
                session = admin_auth.get_session(FakeRequest(token))
            if now - 50_000 > admin_auth.SESSION_MAX_SECONDS:
                self.assertIsNone(session)
            else:
                self.assertIsNotNone(session)

    def test_creating_a_session_purges_expired_ones(self):
        with mock.patch.object(admin_auth.time, 'time', return_value=1000):
            old = admin_auth.create_session('admin')
        with mock.patch.object(admin_auth.time, 'time', return_value=1000 + admin_auth.SESSION_MAX_SECONDS + 1):
            admin_auth.create_session('admin')
        self.assertNotIn(old, variable.admin_sessions)

    def test_destroy_other_sessions_keeps_only_requested_one(self):
        keep = admin_auth.create_session('admin')
        other = admin_auth.create_session('admin')
        someone_else = admin_auth.create_session('bob')
        admin_auth.destroy_other_sessions('admin', keep)
        self.assertIn(keep, variable.admin_sessions)
        self.assertNotIn(other, variable.admin_sessions)
        self.assertIn(someone_else, variable.admin_sessions)


if __name__ == '__main__':
    unittest.main()
