import _env  # noqa: F401

import unittest
from unittest import mock

import ruamel.yaml as yaml_
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import modules
from common import config, db, default_config, gcsp, lx_script
from common.services import module_health, stats_service, users_service

REMOVED = ('mg', 'kw')


class RemovedSourcesTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_supported_sources(self):
        self.assertEqual(sorted(modules.SUPPORTED_SOURCES), ['kg', 'tx', 'wy'])
        for name in REMOVED:
            self.assertFalse(hasattr(modules, name))
            self.assertNotIn(name, modules.sourceExpirationTime)

    def test_default_config_has_no_removed_sources(self):
        default = yaml_.YAML().load(default_config.default)
        for name in REMOVED:
            self.assertNotIn(name, default['module'])
            self.assertNotIn(name, default['module']['cookiepool'])
            self.assertNotIn(name, default['common']['download_config']['quality'])

    def test_script_quality_drops_removed_sources_from_old_configs(self):
        old = {'kw': ['128k'], 'kg': ['128k', '320k'], 'tx': ['128k'], 'wy': ['128k'], 'mg': ['128k']}
        self.assertEqual(lx_script.supported_quality(old),
                         {'kg': ['128k', '320k'], 'tx': ['128k'], 'wy': ['128k']})
        self.assertEqual(lx_script.supported_quality(None), {})

    def test_health_only_tracks_supported_sources(self):
        self.assertEqual(sorted(module_health.SOURCES), ['kg', 'tx', 'wy'])
        self.assertEqual(sorted(module_health.REQUIRED_FIELDS), ['kg', 'tx', 'wy'])

    async def test_stale_health_rows_of_removed_sources_are_deleted(self):
        conn = db.get_connection()
        try:
            for name in REMOVED:
                conn.execute("INSERT OR REPLACE INTO module_health (source, status, detail, checked_at) "
                             "VALUES (?, 'misconfigured', 'old', 1)", (name,))
            conn.commit()
        finally:
            conn.close()

        async def fake_probe(source, force=False):
            return {'source': source, 'status': 'healthy', 'detail': 'ok'}

        with mock.patch.object(module_health, '_probe_source', new=fake_probe):
            await module_health.refresh_module_health()
        self.assertEqual(sorted(r['source'] for r in module_health.get_cached_module_health()),
                         ['kg', 'tx', 'wy'])

    def test_gcsp_platform_map(self):
        self.assertEqual(gcsp.pm, {'qq': 'tx', 'wyy': 'wy', 'kugou': 'kg'})


class ApiHandlerTest(unittest.IsolatedAsyncioTestCase):
    """通过 main.app 走一遍真实的请求处理流程(中间件、鉴权、统计)，不访问外部网络"""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        import main
        cls.main = main

    async def asyncSetUp(self):
        # main.app 在导入时就绑定了事件循环，而每个测试用例都有自己的循环，
        # 所以这里用同样的中间件和处理函数另建一个 Application
        app = web.Application(middlewares=[self.main.handle_before_request])
        app.router.add_get('/{method}/{source}/{songId}/{quality}', self.main.handle)
        app.router.add_get('/{method}/{source}/{songId}', self.main.handle)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        config.write_config_batch({'security.key.enable': True, 'module.tx.enable': False})
        self.addCleanup(config.write_config, 'module.tx.enable', True)

    async def test_removed_and_unknown_sources_are_rejected_before_auth_and_config_lookup(self):
        for source in REMOVED + ('whatever',):
            resp = await self.client.get(f'/url/{source}/123/128k')
            body = await resp.json()
            self.assertEqual(body['code'], 1, source)
        # 不会在配置里为这些名字凭空创建条目
        self.assertNotIn('whatever', config.read_config('module'))
        self.assertNotIn('mg', config.read_config('module'))

    async def test_missing_or_wrong_key_is_forbidden(self):
        self.assertEqual((await self.client.get('/info/tx/abc')).status, 403)
        resp = await self.client.get('/info/tx/abc', headers={'X-Request-User': 'nobody', 'X-Request-Key': 'x'})
        self.assertEqual(resp.status, 403)
        self.assertEqual((await resp.json())['msg'], 'key验证失败')

    async def test_disabled_platform_serves_no_method_at_all(self):
        users_service.create_user('disabled-user', 'disabled-key')
        self.addCleanup(lambda: [users_service.delete_user(u['id']) for u in users_service.list_users()
                                 if u['name'] == 'disabled-user'])
        headers = {'X-Request-User': 'disabled-user', 'X-Request-Key': 'disabled-key'}
        # info 不是 modules 里直接定义的方法，走的是 modules.other，以前会绕过平台开关
        for path in ('/info/tx/abc', '/lyric/tx/abc', '/url/tx/abc/128k'):
            resp = await self.client.get(path, headers=headers)
            self.assertEqual(resp.status, 404, path)
            self.assertEqual((await resp.json())['msg'], '此平台已停止服务', path)

    async def test_valid_key_is_accepted_and_the_request_is_recorded(self):
        users_service.create_user('api-user', 'api-key-for-test')
        headers = {'X-Request-User': 'api-user', 'X-Request-Key': 'api-key-for-test'}
        resp = await self.client.get('/url/tx/abc/128k', headers=headers)
        self.assertEqual(resp.status, 404)  # tx 已被测试关闭，所以不会真的去请求外部接口
        self.assertEqual((await resp.json())['msg'], '此平台已停止服务')
        rows = [r for r in stats_service.get_recent_logs(100) if r['username'] == 'api-user']
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['source'], rows[0]['method'], rows[0]['success']), ('tx', 'url', 0))
        user = [u for u in users_service.list_users() if u['name'] == 'api-user'][0]
        self.assertIsNotNone(user['last_used_at'])

        users_service.delete_user(user['id'])

    async def test_module_error_results_are_recorded_as_failures(self):
        users_service.create_user('result-user', 'result-key-123')
        self.addCleanup(lambda: [users_service.delete_user(u['id']) for u in users_service.list_users()
                                 if u['name'] == 'result-user'])
        config.write_config('module.tx.enable', True)
        headers = {'X-Request-User': 'result-user', 'X-Request-Key': 'result-key-123'}
        results = [{'code': 2, 'msg': '无版权', 'data': None}, {'code': 0, 'msg': 'success', 'data': 'https://x/a.mp3'}]
        with mock.patch.object(modules, 'url', new=mock.AsyncMock(side_effect=results)):
            await self.client.get('/url/tx/result1/128k', headers=headers)
            await self.client.get('/url/tx/result2/128k', headers=headers)
        rows = [r for r in stats_service.get_recent_logs(100) if r['username'] == 'result-user']
        self.assertEqual(sorted((r['song_id'], r['success'], r['error_message']) for r in rows),
                         [('result1', 0, '无版权'), ('result2', 1, None)])


if __name__ == '__main__':
    unittest.main()
