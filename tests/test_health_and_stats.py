import _env  # noqa: F401

import asyncio
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

from common import Httpx, config, db, scheduler
from common.services import module_health, stats_service
from modules.tx import credential


class FakeHttpResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class CredentialTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        credential._cache.clear()
        self.calls = []
        self.codes = {}
        self._orig = Httpx.AsyncRequest
        Httpx.AsyncRequest = self.fake_request
        self.addCleanup(setattr, Httpx, 'AsyncRequest', self._orig)
        config.write_config_batch({'module.tx.user.qqmusic_key': 'W_X_CRED', 'module.tx.user.uin': '555'})

    async def fake_request(self, url, options=None):
        self.calls.append(options['body'])
        return FakeHttpResponse(body={'code': 0, 'req': {'code': self.codes.get('code', 0)}})

    async def test_code_mapping(self):
        user = {'qqmusic_key': 'W_X_CRED', 'uin': '555'}
        for code, expected in ((0, 'valid'), (1000, 'invalid'), (104401, 'invalid'), (104400, 'invalid'),
                               (2001, 'unknown')):
            self.codes['code'] = code
            self.assertEqual(await credential.check_account(user), expected)

    async def test_login_type_follows_the_same_rules_as_refresh(self):
        import ujson
        cases = (({'qqmusic_key': 'PHONEKEY', 'uin': '1', 'login_type': '1'}, '1'),
                 ({'qqmusic_key': 'PHONEKEY', 'uin': '1', 'login_type': '2'}, '2'),
                 ({'qqmusic_key': 'W_X_K', 'uin': '1', 'login_type': '2'}, '2'),  # login_type 优先于前缀
                 ({'qqmusic_key': 'W_X_K', 'uin': '1'}, '1'),
                 ({'qqmusic_key': 'Q_H_L_K', 'uin': '1', 'login_type': ''}, '2'),
                 ({'qqmusic_key': 'PHONEKEY', 'uin': '1', 'login_type': '0'}, '0'),
                 ({'qqmusic_key': 'PHONEKEY', 'uin': '1'}, '0'))
        for user, expected in cases:
            self.calls.clear()
            await credential.check_account(user)
            self.assertEqual(ujson.loads(self.calls[0])['comm']['tmeLoginType'], expected, user)

    async def test_results_are_cached_per_key_and_force_bypasses(self):
        self.codes['code'] = 1000
        first = await credential.check_all()
        self.assertEqual(first, {'total': 1, 'valid': 0, 'invalid': 1, 'unknown': 0})
        await credential.check_all()
        self.assertEqual(len(self.calls), 1)
        await credential.check_all(force=True)
        self.assertEqual(len(self.calls), 2)
        # 刷新登录换了新 key 之后要重新检查
        config.write_config('module.tx.user.qqmusic_key', 'W_X_CRED_2')
        self.codes['code'] = 0
        self.assertEqual((await credential.check_all())['valid'], 1)
        self.assertEqual(len(self.calls), 3)

    async def test_unknown_results_are_not_cached(self):
        self.codes['code'] = 2001
        self.assertEqual((await credential.check_all())['unknown'], 1)
        await credential.check_all()
        self.assertEqual(len(self.calls), 2)

    async def test_network_errors_count_as_unknown(self):
        async def boom(url, options=None):
            raise OSError('network down')
        Httpx.AsyncRequest = boom
        self.assertEqual((await credential.check_all())['unknown'], 1)


class ProbeSourceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        scheduler.clear()
        scheduler._states.clear()
        self.addCleanup(scheduler.clear)
        config.write_config_batch({
            'module.tx.enable': True,
            'module.tx.user.qqmusic_key': 'W_X_PROBE',
            'module.tx.user.uin': '777',
        })
        self._orig = Httpx.AsyncRequest
        Httpx.AsyncRequest = self.fake_request
        self.addCleanup(setattr, Httpx, 'AsyncRequest', self._orig)
        self.summary = {'total': 1, 'valid': 1, 'invalid': 0, 'unknown': 0}
        patcher = mock.patch.object(credential, 'check_all', new=self.fake_check_all)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def fake_request(self, url, options=None):
        return FakeHttpResponse(200)

    async def fake_check_all(self, force=False):
        return self.summary

    def add_failing_task(self, name='qqmusic_refresh_login'):
        async def fn():
            return False
        scheduler.append(name, fn, 86400)
        state = scheduler.tasks[-1].state
        state.consecutive_failures = 3
        state.last_failure_at = time.time()
        state.next_run = time.time() + 300
        state.last_error = '任务返回失败'

    async def test_healthy(self):
        result = await module_health._probe_source('tx')
        self.assertEqual(result['status'], 'healthy')
        self.assertNotIn('admin_detail', result)

    async def test_failing_refresh_task_degrades_module_with_generic_public_detail(self):
        self.add_failing_task()
        result = await module_health._probe_source('tx')
        self.assertEqual(result['status'], 'degraded')
        self.assertNotIn('qqmusic', result['detail'])  # 公开信息里不含任务名等细节
        self.assertIn('qqmusic_refresh_login', result['admin_detail'])
        self.assertIn('连续失败 3 次', result['admin_detail'])

    async def test_other_sources_tasks_do_not_affect_tx(self):
        self.add_failing_task('wy_refresh_login')
        self.assertEqual((await module_health._probe_source('tx'))['status'], 'healthy')

    async def test_invalid_credential_degrades_module(self):
        self.summary = {'total': 2, 'valid': 1, 'invalid': 1, 'unknown': 0}
        result = await module_health._probe_source('tx')
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(result['detail'], '账号登录状态异常')
        self.assertIn('1/2', result['admin_detail'])

    async def test_credential_check_crash_is_ignored(self):
        async def crash(force=False):
            raise RuntimeError('x')
        with mock.patch.object(credential, 'check_all', new=crash):
            self.assertEqual((await module_health._probe_source('tx'))['status'], 'healthy')

    async def test_disabled_and_misconfigured_and_unreachable(self):
        config.write_config('module.tx.enable', False)
        self.assertEqual((await module_health._probe_source('tx'))['status'], 'disabled')
        config.write_config_batch({'module.tx.enable': True, 'module.tx.user.qqmusic_key': ''})
        result = await module_health._probe_source('tx')
        self.assertEqual(result['status'], 'misconfigured')
        self.assertIn('qqmusic_key', result['detail'])
        config.write_config('module.tx.user.qqmusic_key', 'W_X_PROBE')

        async def down(url, options=None):
            raise OSError('unreachable')
        Httpx.AsyncRequest = down
        self.assertEqual((await module_health._probe_source('tx'))['status'], 'degraded')


class HealthStorageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        os.remove(path)
        self.path = path
        patcher = mock.patch.object(db, 'DB_PATH', path)
        patcher.start()
        self.addCleanup(patcher.stop)
        for suffix in ('', '-wal', '-shm'):
            self.addCleanup(lambda s=suffix: os.path.exists(path + s) and os.remove(path + s))

    def test_old_schema_gets_admin_detail_column(self):
        conn = sqlite3.connect(self.path)
        conn.execute('CREATE TABLE module_health (source TEXT PRIMARY KEY, status TEXT NOT NULL, '
                     'detail TEXT, checked_at INTEGER NOT NULL)')
        conn.execute("INSERT INTO module_health VALUES ('tx', 'healthy', 'old row', 1)")
        conn.commit()
        conn.close()
        db.init_db()
        db.init_db()  # 重复初始化不应报错
        rows = module_health.get_cached_module_health()
        self.assertEqual(rows[0]['detail'], 'old row')
        self.assertIsNone(rows[0]['admin_detail'])

    async def test_refresh_stores_admin_detail(self):
        db.init_db()

        async def fake_probe(source, force=False):
            if source == 'tx':
                return {'source': 'tx', 'status': 'degraded', 'detail': 'public', 'admin_detail': 'secret info'}
            return {'source': source, 'status': 'healthy', 'detail': 'ok'}

        with mock.patch.object(module_health, '_probe_source', new=fake_probe):
            await module_health.refresh_module_health(force=True)
        rows = {row['source']: row for row in module_health.get_cached_module_health()}
        self.assertEqual(rows['tx']['admin_detail'], 'secret info')
        self.assertIsNone(rows['kg']['admin_detail'])


class StatsTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    async def test_db_thread_is_not_the_event_loop_thread(self):
        name = await db.run_in_db_thread(lambda: threading.current_thread().name)
        self.assertTrue(name.startswith('app-db'))
        self.assertNotEqual(name, threading.current_thread().name)

    async def test_record_parse_async_writes_and_swallows_errors(self):
        user = {'id': None, 'name': 'stats-user'}
        await stats_service.record_parse_async(user, 'tx', 'url', 'song1', '128k', True, None, '1.1.1.1')
        rows = [r for r in stats_service.get_recent_logs(50) if r['username'] == 'stats-user']
        self.assertEqual(len(rows), 1)

        async def broken(*args):
            raise sqlite3.OperationalError('database is locked')
        with mock.patch.object(db, 'run_in_db_thread', new=broken):
            await stats_service.record_parse_async(user, 'tx', 'url', 'song2', '128k', True, None, '1.1.1.1')

    def test_cleanup_removes_only_old_rows(self):
        conn = db.get_connection()
        try:
            now = int(time.time())
            conn.executemany(
                'INSERT INTO parse_logs (username, source, method, song_id, quality, success, created_at) '
                "VALUES ('cleanup-user', 'tx', 'url', ?, '128k', 1, ?)",
                [('old', now - 40 * 86400), ('new', now - 86400)])
            conn.commit()
        finally:
            conn.close()
        self.assertGreaterEqual(stats_service.cleanup_old_logs(30), 1)
        remaining = [r['song_id'] for r in stats_service.get_recent_logs(500) if r['username'] == 'cleanup-user']
        self.assertEqual(remaining, ['new'])

    def test_cleanup_task_is_registered_unless_disabled(self):
        scheduler.clear()
        self.addCleanup(scheduler.clear)
        config.write_config('common.parse_log_retention_days', 30)
        stats_service.register_tasks()
        self.assertIn('parse_logs_cleanup', [t.name for t in scheduler.tasks])
        scheduler.clear()
        config.write_config('common.parse_log_retention_days', 0)
        stats_service.register_tasks()
        self.assertEqual(scheduler.tasks, [])
        config.write_config('common.parse_log_retention_days', 30)


if __name__ == '__main__':
    unittest.main()
