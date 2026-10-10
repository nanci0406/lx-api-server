import _env  # noqa: F401

import base64
import os
import re
import time
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import modules
from common import config, db, scheduler, variable
from common.services import admin_auth, module_health, stats_service, users_service
from modules.tx import login as qq_login
from webui import api_admin, config_schema, routes

PASSWORD = _env.ADMIN_PASSWORD
USERNAME = _env.ADMIN_USERNAME
COOKIE = admin_auth.COOKIE_NAME


class WebUiCase(unittest.IsolatedAsyncioTestCase):
    """启动只包含 Web 界面路由的应用；self.cookies 是一个已登录的管理员会话"""

    login_first = True

    @classmethod
    def setUpClass(cls):
        db.init_db()

    async def asyncSetUp(self):
        admin_auth._login_failures.clear()
        variable.admin_sessions.clear()
        config.write_config('security.admin_origin_check', True)
        app = web.Application()
        routes.register_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.origin = f'http://{self.client.host}:{self.client.port}'
        self.cookies = await self.new_session() if self.login_first else None

    async def login(self, password=PASSWORD, headers=None):
        return await self.client.post('/api/admin/login', json={'username': USERNAME, 'password': password},
                                      headers=headers)

    async def new_session(self):
        resp = await self.login()
        self.assertEqual(resp.status, 200)
        token = resp.cookies[COOKIE].value
        # 客户端会自动保存 Cookie；清掉它，才能区分"带 Cookie"和"匿名"的请求
        self.client.session.cookie_jar.clear()
        return {COOKIE: token}

    async def call(self, method, path, body=None, cookies='admin', headers=None):
        """发起 JSON 请求，返回 (状态码, 响应 JSON)"""
        kwargs = {'json': body} if body is not None else {}
        resp = await self.client.request(method, path, cookies=self.cookies if cookies == 'admin' else cookies,
                                         headers=headers, **kwargs)
        return resp.status, await resp.json()

    def set_config(self, key, value):
        old = config.read_config(key)
        config.write_config(key, value)
        self.addCleanup(config.write_config, key, old)


# ---------------------------------------------------------------------------
# 登录、会话、CSRF
# ---------------------------------------------------------------------------

class AuthApiTest(WebUiCase):
    login_first = False

    async def test_login_sets_a_strict_http_only_cookie(self):
        resp = await self.login()
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())['data'], {'username': USERNAME})
        cookie = resp.cookies[COOKIE]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(cookie['path'], '/')
        self.assertFalse(cookie['secure'])  # 纯 HTTP 访问

    async def test_cookie_is_secure_when_declared_https(self):
        self.set_config('common.ssl_info.is_https', True)
        resp = await self.login()
        self.assertTrue(resp.cookies[COOKIE]['secure'])

    async def test_login_requires_a_json_body(self):
        resp = await self.client.post('/api/admin/login', data={'username': USERNAME, 'password': PASSWORD})
        self.assertEqual(resp.status, 400)
        self.assertNotIn(COOKIE, resp.cookies)
        status, _ = await self.call('POST', '/api/admin/login', {'username': USERNAME}, cookies=None)
        self.assertEqual(status, 400)

    async def test_wrong_password_then_rate_limited(self):
        for _ in range(admin_auth.LOGIN_MAX_FAILURES):
            resp = await self.login('wrong')
            self.assertEqual(resp.status, 401)
            self.assertEqual((await resp.json())['msg'], '用户名或密码错误')
        self.assertEqual((await self.login('wrong')).status, 429)
        # 被限制期间，即使密码正确也不放行
        self.assertEqual((await self.login()).status, 429)

    async def test_successful_login_resets_failure_count(self):
        for _ in range(admin_auth.LOGIN_MAX_FAILURES - 1):
            await self.login('wrong')
        self.assertEqual((await self.login()).status, 200)
        for _ in range(admin_auth.LOGIN_MAX_FAILURES - 1):
            self.assertEqual((await self.login('wrong')).status, 401)

    async def test_login_checks_the_origin(self):
        self.assertEqual((await self.login(headers={'Origin': 'http://evil.example'})).status, 403)

    async def test_me_reports_the_session_and_other_devices(self):
        status, body = await self.call('GET', '/api/admin/me', cookies=None)
        self.assertEqual((status, body['code']), (401, 401))
        first = await self.new_session()
        await self.new_session()
        status, body = await self.call('GET', '/api/admin/me', cookies=first)
        self.assertEqual(status, 200)
        me = body['data']
        self.assertEqual(me['username'], USERNAME)
        self.assertEqual(me['other_sessions'], 1)
        self.assertIsNotNone(me['session_started_at'])
        self.assertIsNotNone(me['created_at'])

    async def test_logout_ends_the_session(self):
        cookies = await self.new_session()
        resp = await self.client.post('/api/admin/logout', cookies=cookies)
        self.assertEqual(resp.status, 200)
        status, _ = await self.call('GET', '/api/admin/me', cookies=cookies)
        self.assertEqual(status, 401)

    async def test_every_admin_endpoint_requires_a_session(self):
        endpoints = [
            ('GET', '/api/admin/me'), ('GET', '/api/admin/overview'), ('GET', '/api/admin/config'),
            ('PUT', '/api/admin/config'), ('GET', '/api/admin/config/raw'), ('PUT', '/api/admin/config/raw'),
            ('GET', '/api/admin/users'), ('POST', '/api/admin/users'), ('PATCH', '/api/admin/users/1'),
            ('DELETE', '/api/admin/users/1'), ('POST', '/api/admin/users/1/reset-key'), ('GET', '/api/admin/stats'),
            ('GET', '/api/admin/stats/logs'), ('GET', '/api/admin/health'), ('POST', '/api/admin/health/refresh'),
            ('POST', '/api/admin/tasks/x/run'), ('POST', '/api/admin/account/password'),
            ('POST', '/api/admin/account/logout-others'), ('POST', '/api/admin/qqlogin/qr'),
            ('POST', '/api/admin/qqlogin/phone/send'), ('POST', '/api/admin/qqlogin/phone/verify'),
            ('GET', '/api/admin/qqlogin/x'), ('POST', '/api/admin/qqlogin/x/cancel'),
            ('POST', '/api/admin/qqlogin/x/apply'),
        ]
        for method, path in endpoints:
            status, body = await self.call(method, path, {}, cookies=None)
            # 接口只返回 JSON 401，不跳转到登录页，否则前端拿到的是 HTML
            self.assertEqual((status, body['code']), (401, 401), f'{method} {path}')

    async def test_write_requests_check_the_origin(self):
        cookies = await self.new_session()

        async def put(headers):
            status, _ = await self.call('PUT', '/api/admin/config', {'values': {}}, cookies=cookies, headers=headers)
            return status
        self.assertEqual(await put({'Origin': 'http://evil.example'}), 403)
        self.assertEqual(await put({'Referer': 'http://evil.example/page'}), 403)
        self.assertEqual(await put({'Origin': 'null'}), 403)
        # 通过来源校验后才会检查请求内容(这里因为没有修改而返回 400)
        self.assertEqual(await put({'Origin': self.origin}), 400)
        self.assertEqual(await put(None), 400)
        self.assertEqual(await put({'Origin': 'https://music.example.com', 'X-Forwarded-Host': 'music.example.com'}), 400)
        # 读接口不做来源校验
        status, _ = await self.call('GET', '/api/admin/config', cookies=cookies, headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 200)

    async def test_origin_check_can_be_disabled(self):
        self.set_config('security.admin_origin_check', False)
        cookies = await self.new_session()
        status, _ = await self.call('PUT', '/api/admin/config', {'values': {}}, cookies=cookies,
                                    headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 400)

    async def test_write_requests_need_json(self):
        cookies = await self.new_session()
        resp = await self.client.post('/api/admin/users', data={'name': 'form-user'}, cookies=cookies)
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())['msg'], '请求格式错误，需要 JSON')
        resp = await self.client.post('/api/admin/users', data='[1]', cookies=cookies,
                                      headers={'Content-Type': 'application/json'})
        self.assertEqual(resp.status, 400)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def _fields(payload):
    return {f['key']: f for section in payload['data']['sections'] for f in section['fields']}


class ConfigApiTest(WebUiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.reloads = []
        patcher = mock.patch.object(config, 'hot_reload_config', side_effect=lambda: self.reloads.append(1))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_secrets_are_masked(self):
        self.set_config('module.tx.user.qqmusic_key', 'W_X_SUPER_SECRET_9876')
        self.set_config('module.tx.user.refresh_key', '')
        resp = await self.client.get('/api/admin/config', cookies=self.cookies)
        text = await resp.text()
        self.assertNotIn('SUPER_SECRET', text)
        fields = _fields(await resp.json())
        self.assertEqual(fields['module.tx.user.qqmusic_key']['value'], {'set': True, 'preview': '9876'})
        self.assertEqual(fields['module.tx.user.refresh_key']['value'], {'set': False, 'preview': ''})
        # 依赖关系一起下发给前端
        self.assertEqual(fields['common.proxy.http_value']['depends'], 'common.proxy.enable')

    async def test_save_validates_everything_before_writing(self):
        self.set_config('module.tx.user.refresh_key', 'before')
        status, body = await self.call('PUT', '/api/admin/config', {'values': {
            'common.log_length_limit': 10,
            'module.tx.user.refresh_login.interval': 'abc',
            'no.such.key': 1,
            'module.tx.user.refresh_key': 'after',
        }})
        self.assertEqual(status, 400)
        self.assertEqual(set(body['data']['errors']), {
            'common.log_length_limit', 'module.tx.user.refresh_login.interval', 'no.such.key'})
        self.assertEqual(body['data']['errors']['common.log_length_limit'], '不能小于 50')
        self.assertNotIn('after', config.read_config_text())  # 有一项出错，整次保存都不写入
        self.assertEqual(self.reloads, [])

    async def test_save_converts_writes_and_hot_reloads(self):
        self.set_config('common.parse_log_retention_days', 30)
        self.set_config('common.hosts', ['0.0.0.0'])
        status, body = await self.call('PUT', '/api/admin/config', {'values': {
            'common.parse_log_retention_days': '45',
            'common.hosts': ['0.0.0.0', ' :: ', '0.0.0.0'],
        }})
        self.assertEqual(status, 200)
        data = body['data']
        self.assertEqual(set(data['saved']), {'common.parse_log_retention_days', 'common.hosts'})
        self.assertEqual(data['restart_required'], ['监听地址'])
        self.assertIsNone(data['reload_error'])
        self.assertEqual(self.reloads, [1])
        self.assertEqual(config.read_config('common.parse_log_retention_days'), 45)
        self.assertEqual(list(config.read_config('common.hosts')), ['0.0.0.0', '::'])
        self.assertEqual(_fields(body)['common.parse_log_retention_days']['value'], 45)

    async def test_reload_errors_are_reported_after_saving(self):
        self.set_config('common.log_length_limit', 500)
        with mock.patch.object(config, 'hot_reload_config', side_effect=RuntimeError('boom')):
            status, body = await self.call('PUT', '/api/admin/config', {'values': {'common.log_length_limit': 600}})
        self.assertEqual(status, 200)
        self.assertEqual(body['data']['reload_error'], 'boom')
        self.assertEqual(config.read_config('common.log_length_limit'), 600)

    async def test_secret_null_keeps_and_empty_string_clears(self):
        self.set_config('module.tx.user.qqmusic_key', 'KEEP_ME_123456')
        self.set_config('module.tx.user.uin', '1')
        status, _ = await self.call('PUT', '/api/admin/config', {'values': {
            'module.tx.user.qqmusic_key': None, 'module.tx.user.uin': '42'}})
        self.assertEqual(status, 200)
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'KEEP_ME_123456')
        self.assertEqual(config.read_config('module.tx.user.uin'), '42')
        status, _ = await self.call('PUT', '/api/admin/config', {'values': {'module.tx.user.qqmusic_key': None}})
        self.assertEqual(status, 400)  # 只有"未修改"的密钥，等于没有修改
        status, _ = await self.call('PUT', '/api/admin/config', {'values': {'module.tx.user.qqmusic_key': ''}})
        self.assertEqual(status, 200)
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), '')

    async def test_raw_config_round_trip(self):
        original = config.read_config_text()
        self.addCleanup(config.write_config_text, original)
        status, body = await self.call('GET', '/api/admin/config/raw')
        self.assertEqual((status, body['data']['content']), (200, original))

        for content, message in (('common: [unclosed', 'YAML 格式错误'), ('just text', '三个部分'),
                                 ('common: {}\nsecurity: {}\n', '三个部分'), ('   ', '不能为空')):
            status, body = await self.call('PUT', '/api/admin/config/raw', {'content': content})
            self.assertEqual(status, 400, content)
            self.assertIn(message, body['msg'])
        self.assertEqual(config.read_config_text(), original)

        changed = original.replace('log_length_limit:', 'log_length_limit: 777 #', 1)
        self.assertNotEqual(changed, original)
        status, body = await self.call('PUT', '/api/admin/config/raw', {'content': changed})
        self.assertEqual(status, 200)
        self.assertEqual(body['data']['content'], changed)
        self.assertEqual(config.read_config_text(), changed)
        with open('./config/config.yml.bak', encoding='utf-8') as f:
            self.assertEqual(f.read(), original)

    async def test_raw_config_is_restored_when_it_cannot_be_loaded(self):
        original = config.read_config_text()
        self.addCleanup(config.write_config_text, original)
        changed = original + '\n# broken on purpose\n'
        calls = []

        def reload_once_fails():
            calls.append(1)
            if len(calls) == 1:
                raise ValueError('bad value')
        with mock.patch.object(config, 'hot_reload_config', side_effect=reload_once_fails):
            status, body = await self.call('PUT', '/api/admin/config/raw', {'content': changed})
        self.assertEqual(status, 400)
        self.assertIn('已恢复原配置', body['msg'])
        self.assertEqual(config.read_config_text(), original)
        self.assertEqual(len(calls), 2)  # 恢复后重新加载一次原配置


class ConfigSchemaTest(unittest.TestCase):
    def test_every_field_exists_in_the_default_config(self):
        for key in config_schema.FIELDS:
            self.assertIsNotNone(config.read_default_config(key), key)

    def test_depends_point_to_an_earlier_switch_in_the_same_section(self):
        for section in config_schema.SECTIONS:
            keys = [f['key'] for f in section['fields']]
            for f in section['fields']:
                if 'depends' in f:
                    parent = config_schema.FIELDS[f['depends']]
                    self.assertEqual(parent['type'], 'bool', f['key'])
                    self.assertLess(keys.index(parent['key']), keys.index(f['key']), f['key'])

    def test_convert(self):
        fields = config_schema.FIELDS
        convert = config_schema.convert
        error = config_schema.ValidationError
        self.assertEqual(convert(fields['common.log_length_limit'], ' 80 '), 80)
        for bad in ('', 'x', 1.5, True, 49, 100001):
            with self.assertRaises(error, msg=repr(bad)):
                convert(fields['common.log_length_limit'], bad)
        self.assertEqual(convert(fields['security.rate_limit.ip'], '0.5'), 0.5)
        self.assertEqual(convert(fields['security.rate_limit.ip'], 2.0), 2)
        for bad in ('nan', 'inf', '1e999', -1):
            with self.assertRaises(error, msg=repr(bad)):
                convert(fields['security.rate_limit.ip'], bad)
        with self.assertRaises(error):
            convert(fields['common.proxy.enable'], 'true')
        with self.assertRaises(error):
            convert(fields['common.download_config.name'], 'a\nb')
        self.assertEqual(convert(fields['common.download_config.name'], '  name '), 'name')
        self.assertEqual(convert(fields['common.download_config.updateMsg'], ' keep\n'), ' keep\n')
        with self.assertRaises(error):
            convert(fields['module.tx.user.login_type'], '3')
        self.assertEqual(convert(fields['common.download_config.quality.tx'], ['flac', '128k', 'flac']),
                         ['128k', 'flac'])
        with self.assertRaises(error):
            convert(fields['common.download_config.quality.tx'], ['sky'])
        self.assertEqual(convert(fields['common.ports'], [9763, '80', 9763]), [9763, 80])
        with self.assertRaises(error):
            convert(fields['common.ports'], [70000])
        with self.assertRaises(error):
            convert(fields['common.hosts'], ['a b'])

    def test_secret_preview_only_reveals_the_tail_of_long_values(self):
        self.assertEqual(config_schema.secret_preview('short'), {'set': True, 'preview': ''})
        self.assertEqual(config_schema.secret_preview('0123456789'), {'set': True, 'preview': '6789'})
        self.assertEqual(config_schema.secret_preview(None), {'set': False, 'preview': ''})


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------

class UsersApiTest(WebUiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.addCleanup(lambda: [users_service.delete_user(u['id']) for u in users_service.list_users()
                                 if u['name'].startswith('webui-')])

    async def create(self, name, api_key=None):
        body = {'name': name}
        if api_key is not None:
            body['api_key'] = api_key
        return await self.call('POST', '/api/admin/users', body)

    async def test_create_validates_and_rejects_duplicates(self):
        status, body = await self.create('webui-alice')
        self.assertEqual(status, 201)
        alice = body['data']
        self.assertEqual((alice['name'], alice['enabled'], alice['total']), ('webui-alice', 1, 0))
        self.assertRegex(alice['api_key'], r'^[A-Za-z0-9_-]{24}$')  # 自动生成

        status, body = await self.create('webui-alice')
        self.assertEqual((status, body['msg']), (409, '用户名已存在'))
        status, body = await self.create('webui-bob', alice['api_key'])
        self.assertEqual((status, body['msg']), (409, '这个 Key 已被其他用户使用'))
        for name, key in (('', None), ('webui bad', None), ('x' * 33, None), ('webui-ok', 'short'),
                          ('webui-ok', 'has space'), ('webui-ok', 'k' * 65)):
            status, _ = await self.create(name, key)
            self.assertEqual(status, 400, (name, key))
        status, body = await self.create('webui-bob', 'bob-key-123')
        self.assertEqual((status, body['data']['api_key']), (201, 'bob-key-123'))

    async def test_enable_reset_key_and_delete(self):
        _, body = await self.create('webui-carol', 'carol-key-1')
        carol = body['data']
        await self.create('webui-dave', 'dave-key-1')
        path = f"/api/admin/users/{carol['id']}"

        status, body = await self.call('PATCH', path, {'enabled': False})
        self.assertEqual((status, body['data']['enabled']), (200, 0))
        self.assertIsNone(users_service.get_user_by_name_and_key('webui-carol', 'carol-key-1'))
        status, _ = await self.call('PATCH', path, {'enabled': 'no'})
        self.assertEqual(status, 400)
        await self.call('PATCH', path, {'enabled': True})

        status, body = await self.call('POST', path + '/reset-key', {})
        new_key = body['data']['api_key']
        self.assertEqual(status, 200)
        self.assertNotEqual(new_key, 'carol-key-1')
        self.assertIsNotNone(users_service.get_user_by_name_and_key('webui-carol', new_key))
        status, _ = await self.call('POST', path + '/reset-key', {'api_key': 'dave-key-1'})
        self.assertEqual(status, 409)
        status, body = await self.call('POST', path + '/reset-key', {'api_key': new_key})
        self.assertEqual(status, 200)  # 换成自己现在的 Key 不算冲突

        status, _ = await self.call('DELETE', path)
        self.assertEqual(status, 200)
        for method, target in (('PATCH', path), ('DELETE', path), ('PATCH', '/api/admin/users/abc')):
            status, _ = await self.call(method, target, {'enabled': True})
            self.assertEqual(status, 404, target)

    async def test_list_includes_usage(self):
        _, body = await self.create('webui-erin', 'erin-key-1')
        erin = body['data']
        user = {'id': erin['id'], 'name': erin['name']}
        stats_service.record_parse(user, 'tx', 'url', '1', '128k', True, None, '127.0.0.1')
        stats_service.record_parse(user, 'kg', 'url', '2', '128k', False, 'oops', '127.0.0.1')
        self.set_config('common.allow_download_script', True)
        status, body = await self.call('GET', '/api/admin/users')
        self.assertEqual(status, 200)
        row = [u for u in body['data']['users'] if u['id'] == erin['id']][0]
        self.assertEqual((row['total'], row['success_count']), (2, 1))
        self.assertTrue(body['data']['script_enabled'])


# ---------------------------------------------------------------------------
# 概览与统计
# ---------------------------------------------------------------------------

class StatsApiTest(WebUiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        user = {'id': None, 'name': 'webui-stats'}
        stats_service.record_parse(user, 'tx', 'url', 'a', '128k', True, None, '1.1.1.1')
        stats_service.record_parse(user, 'tx', 'url', 'b', '320k', True, None, '1.1.1.1')
        stats_service.record_parse(user, 'kg', 'url', 'c', '128k', False, '无版权', '1.1.1.1')

        def cleanup():
            conn = db.get_connection()
            try:
                conn.execute("DELETE FROM parse_logs WHERE username = 'webui-stats'")
                conn.commit()
            finally:
                conn.close()
        self.addCleanup(cleanup)

    async def test_overview_and_ranges(self):
        status, body = await self.call('GET', '/api/admin/stats?days=7')
        self.assertEqual(status, 200)
        data = body['data']
        self.assertEqual(data['days'], 7)
        self.assertEqual(len(data['daily']), 7)
        self.assertGreaterEqual(data['daily'][-1]['total'], 3)
        self.assertEqual(data['totals']['total'], data['totals']['success'] + data['totals']['failure'])
        mine = [row for row in data['by_user'] if row['username'] == 'webui-stats'][0]
        self.assertEqual((mine['total'], mine['success']), (3, 2))
        self.assertIn('QQ 音乐', [row['name'] for row in data['by_source']])
        for query, days in (('days=30', 30), ('days=1', 1), ('days=5', 7), ('days=x', 7)):
            _, body = await self.call('GET', f'/api/admin/stats?{query}')
            self.assertEqual((body['data']['days'], len(body['data']['daily'])), (days, days), query)

    async def test_logs_filters_and_paging(self):
        base = '/api/admin/stats/logs?username=webui-stats'
        _, body = await self.call('GET', base)
        self.assertEqual(body['data']['total'], 3)
        self.assertEqual([row['song_id'] for row in body['data']['logs']], ['c', 'b', 'a'])  # 新的在前
        _, body = await self.call('GET', base + '&result=failure')
        self.assertEqual([(row['source'], row['error_message']) for row in body['data']['logs']], [('kg', '无版权')])
        _, body = await self.call('GET', base + '&source=tx&result=success&limit=1&offset=1')
        self.assertEqual((body['data']['total'], [row['song_id'] for row in body['data']['logs']]), (2, ['a']))
        status, _ = await self.call('GET', base + '&limit=abc')
        self.assertEqual(status, 400)

    async def test_dashboard_overview(self):
        status, body = await self.call('GET', '/api/admin/overview')
        self.assertEqual(status, 200)
        data = body['data']
        self.assertEqual(data['username'], USERNAME)
        self.assertEqual(len(data['daily']), 7)
        self.assertGreaterEqual(data['today']['total'], 3)
        self.assertLessEqual(len(data['recent']), 6)
        self.assertEqual(set(data['tasks']), {'total', 'failing'})


# ---------------------------------------------------------------------------
# 模块状态与定时任务
# ---------------------------------------------------------------------------

class HealthApiTest(WebUiCase):
    def put_health(self, source, status, detail, admin_detail=None):
        conn = db.get_connection()
        try:
            conn.execute(
                'INSERT INTO module_health (source, status, detail, checked_at, admin_detail) VALUES (?, ?, ?, 1, ?) '
                'ON CONFLICT(source) DO UPDATE SET status = excluded.status, detail = excluded.detail, '
                'admin_detail = excluded.admin_detail', (source, status, detail, admin_detail))
            conn.commit()
        finally:
            conn.close()

    async def test_admin_detail_is_only_visible_to_admins(self):
        self.put_health('tx', 'degraded', '账号登录状态异常', 'qqmusic_refresh_login 已连续失败 3 次')
        self.put_health('kg', 'disabled', '已关闭')
        self.put_health('wy', 'healthy', '探测成功(200)')
        _, body = await self.call('GET', '/api/public/status', cookies=None)
        public = body['data']['modules']
        self.assertEqual([row['source'] for row in public], ['tx', 'wy'])  # 关闭的平台不展示，按固定顺序
        self.assertTrue(all('admin_detail' not in row for row in public))
        _, body = await self.call('GET', '/api/admin/health')
        tx = [row for row in body['data']['modules'] if row['source'] == 'tx'][0]
        self.assertEqual((tx['name'], tx['admin_detail']), ('QQ 音乐', 'qqmusic_refresh_login 已连续失败 3 次'))

    async def test_refresh_forces_a_new_check(self):
        calls = []

        async def fake_refresh(force=False):
            calls.append(force)
        with mock.patch.object(module_health, 'refresh_module_health', side_effect=fake_refresh):
            status, body = await self.call('POST', '/api/admin/health/refresh', {})
        self.assertEqual((status, calls), (200, [True]))
        self.assertIn('modules', body['data'])
        self.assertIn('tasks', body['data'])

    async def test_run_task_now(self):
        async def job():
            pass
        scheduler.append('webui_test_task', job, 3600)
        self.addCleanup(lambda: scheduler.tasks.__setitem__(
            slice(None), [t for t in scheduler.tasks if t.name != 'webui_test_task']))
        task = [t for t in scheduler.tasks if t.name == 'webui_test_task'][0]
        task.state.next_run = time.time() + 3600

        _, body = await self.call('GET', '/api/admin/health')
        row = [t for t in body['data']['tasks'] if t['name'] == 'webui_test_task'][0]
        self.assertEqual((row['label'], row['interval']), ('webui_test_task', 3600))

        status, _ = await self.call('POST', '/api/admin/tasks/webui_test_task/run', {})
        self.assertEqual(status, 200)
        self.assertEqual(task.state.next_run, 0)
        self.assertTrue(task.check_available())
        task.state.running = True
        status, _ = await self.call('POST', '/api/admin/tasks/webui_test_task/run', {})
        self.assertEqual(status, 409)
        task.state.running = False
        status, _ = await self.call('POST', '/api/admin/tasks/no_such_task/run', {})
        self.assertEqual(status, 404)

    def test_task_labels(self):
        self.assertEqual(api_admin.task_label('qqmusic_refresh_login'), 'QQ 音乐 · 刷新登录')
        self.assertEqual(api_admin.task_label('qqmusic_refresh_login_pooled_0'), 'QQ 音乐 · 刷新登录(账号池 #1)')
        self.assertEqual(api_admin.task_label('kgmusic_refresh_login_pooled_2'), '酷狗 · 刷新登录(账号池 #3)')
        self.assertEqual(api_admin.task_label('kugou_lite_sign_in_12345'), '酷狗概念版 · 签到')
        self.assertEqual(api_admin.task_label('something_else'), 'something_else')


# ---------------------------------------------------------------------------
# 管理员账号
# ---------------------------------------------------------------------------

class AccountApiTest(WebUiCase):
    def restore_password(self):
        admin_auth.update_admin_password(admin_auth.get_admin(USERNAME)['id'], PASSWORD)

    async def test_change_password(self):
        other = await self.new_session()
        url = '/api/admin/account/password'
        for body, message in (({'current': 'wrong', 'new': 'whatever-123'}, '当前密码不正确'),
                              ({'current': PASSWORD, 'new': PASSWORD}, '不能和当前密码相同'),
                              ({'current': PASSWORD, 'new': 'short'}, '至少需要')):
            status, resp = await self.call('POST', url, body)
            self.assertEqual(status, 400)
            self.assertIn(message, resp['msg'])

        self.addCleanup(self.restore_password)
        status, _ = await self.call('POST', url, {'current': PASSWORD, 'new': 'brand-new-password'})
        self.assertEqual(status, 200)
        self.assertEqual((await self.call('GET', '/api/admin/me'))[0], 200)  # 当前会话保留
        self.assertEqual((await self.call('GET', '/api/admin/me', cookies=other))[0], 401)  # 其他会话退出
        self.assertEqual((await self.login('brand-new-password')).status, 200)
        self.assertEqual((await self.login()).status, 401)

    async def test_wrong_current_password_is_rate_limited(self):
        for _ in range(admin_auth.LOGIN_MAX_FAILURES):
            await self.call('POST', '/api/admin/account/password', {'current': 'wrong', 'new': 'whatever-123'})
        status, _ = await self.call('POST', '/api/admin/account/password', {'current': PASSWORD, 'new': 'x' * 12})
        self.assertEqual(status, 429)
        self.assertTrue(admin_auth.check_password(USERNAME, PASSWORD))  # 没有被修改

    async def test_logout_other_devices(self):
        first = await self.new_session()
        second = await self.new_session()
        status, body = await self.call('POST', '/api/admin/account/logout-others', {})
        self.assertEqual((status, body['data']['closed']), (200, 2))
        for cookies in (first, second):
            self.assertEqual((await self.call('GET', '/api/admin/me', cookies=cookies))[0], 401)
        self.assertEqual((await self.call('GET', '/api/admin/me'))[0], 200)


# ---------------------------------------------------------------------------
# QQ 音乐登录
# ---------------------------------------------------------------------------

class QqLoginApiTest(WebUiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        qq_login._sessions.clear()

    def patch(self, name, **kwargs):
        patcher = mock.patch.object(qq_login, name, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def done_session(self, owner=USERNAME):
        ls = qq_login.LoginSession('qq', owner)
        ls.credential = qq_login.credential_from_login(
            0, {'musickey': 'Q_H_L_ROUTE', 'musicid': 4242, 'refresh_key': 'RK'}, 2)
        ls.finish('done', '登录成功')
        qq_login._sessions[ls.id] = ls
        return ls

    async def test_post_endpoints_check_the_origin(self):
        status, _ = await self.call('POST', '/api/admin/qqlogin/qr', {'kind': 'qq'},
                                    headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)

    async def test_qr_start_returns_a_data_url_and_status_is_owner_bound(self):
        async def fake_start(kind, owner):
            ls = qq_login.LoginSession(kind, owner)
            ls.image, ls.mimetype = b'\x89PNG-bytes', 'image/png'
            qq_login._sessions[ls.id] = ls
            return ls
        self.patch('start_qr', new=fake_start)
        status, body = await self.call('POST', '/api/admin/qqlogin/qr', {'kind': 'qq'})
        data = body['data']
        self.assertEqual(status, 200)
        self.assertTrue(data['image'].startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(data['image'].split(',', 1)[1]), b'\x89PNG-bytes')
        self.assertEqual(data['expires_in'], qq_login.QR_TIMEOUT)

        _, status_body = await self.call('GET', f"/api/admin/qqlogin/{data['id']}")
        self.assertEqual(status_body['data']['state'], 'scan')
        qq_login._sessions[data['id']].owner = 'someone-else'
        status, _ = await self.call('GET', f"/api/admin/qqlogin/{data['id']}")
        self.assertEqual(status, 404)

    async def test_qr_start_errors_are_reported_as_json(self):
        async def failing(kind, owner):
            raise qq_login.LoginError('同时进行的扫码登录太多，请稍后再试')
        self.patch('start_qr', new=failing)
        status, body = await self.call('POST', '/api/admin/qqlogin/qr', {'kind': 'qq'})
        self.assertEqual((status, body['msg']), (400, '同时进行的扫码登录太多，请稍后再试'))

    async def test_status_never_contains_the_credential(self):
        ls = self.done_session()
        text = await (await self.client.get(f'/api/admin/qqlogin/{ls.id}', cookies=self.cookies)).text()
        self.assertIn('4242', text)
        self.assertNotIn('Q_H_L_ROUTE', text)
        self.assertNotIn('"RK"', text)

    async def test_phone_send_only_exposes_trusted_captcha_urls(self):
        results = iter([
            {'state': 'captcha', 'url': 'https://captcha.qq.com/x'},
            {'state': 'captcha', 'url': 'javascript:alert(1)'},
            {'state': 'captcha', 'url': 'https://evil.example/qq.com'},
            {'state': 'sent'},
        ])

        async def fake_send(owner, phone, country_code='86'):
            return dict(next(results))
        self.patch('phone_send', new=fake_send)
        urls = []
        for _ in range(3):
            _, body = await self.call('POST', '/api/admin/qqlogin/phone/send', {'phone': '13800138000'})
            urls.append(body['data']['url'])
        self.assertEqual(urls, ['https://captcha.qq.com/x', '', ''])
        _, body = await self.call('POST', '/api/admin/qqlogin/phone/send', {'phone': '13800138000'})
        self.assertEqual(body['data'], {'state': 'sent', 'cooldown': qq_login.SMS_COOLDOWN})

    async def test_phone_verify_creates_a_result_session(self):
        async def fake_verify(owner, phone, code, country_code='86'):
            self.assertEqual((owner, phone, code, country_code), (USERNAME, '13800138000', '123456', '86'))
            return self.done_session(owner)
        self.patch('phone_verify', new=fake_verify)
        _, body = await self.call('POST', '/api/admin/qqlogin/phone/verify', {
            'phone': '13800138000', 'code': '123456', 'country_code': '86'})
        self.assertEqual((body['data']['state'], body['data']['account']['uin']), ('done', '4242'))

    async def test_apply_saves_the_credential_and_reloads_the_config(self):
        for key in ('module.tx.user.qqmusic_key', 'module.tx.user.uin', 'module.tx.user.refresh_key',
                    'module.tx.user.refresh_login.enable'):
            self.set_config(key, config.read_config(key))
        ls = self.done_session()
        reloads = []
        with mock.patch.object(config, 'hot_reload_config', side_effect=lambda: reloads.append(1)):
            status, body = await self.call('POST', f'/api/admin/qqlogin/{ls.id}/apply',
                                           {'target': 'main', 'enable_refresh': True})
        self.assertEqual(status, 200)
        self.assertIn('主账号', body['data']['note'])
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'Q_H_L_ROUTE')
        self.assertEqual(config.read_config('module.tx.user.uin'), '4242')
        self.assertTrue(config.read_config('module.tx.user.refresh_login.enable'))
        self.assertEqual(reloads, [1])
        # 凭证已写入配置，会话里不再保留，也不能重复保存
        status, _ = await self.call('POST', f'/api/admin/qqlogin/{ls.id}/apply', {'target': 'main'})
        self.assertEqual(status, 400)

    async def test_apply_validates_session_owner_and_target(self):
        ls = self.done_session()
        status, _ = await self.call('POST', f'/api/admin/qqlogin/{ls.id}/apply', {'target': 'nowhere'})
        self.assertEqual(status, 400)
        ls.owner = 'someone-else'
        status, _ = await self.call('POST', f'/api/admin/qqlogin/{ls.id}/apply', {'target': 'main'})
        self.assertEqual(status, 404)
        status, _ = await self.call('POST', '/api/admin/qqlogin/nope/apply', {'target': 'main'})
        self.assertEqual(status, 404)

    async def test_cancel(self):
        ls = qq_login.LoginSession('qq', USERNAME)
        qq_login._sessions[ls.id] = ls
        status, body = await self.call('POST', f'/api/admin/qqlogin/{ls.id}/cancel', {})
        self.assertEqual((status, body['code']), (200, 0))
        self.assertEqual(ls.state, 'cancelled')


# ---------------------------------------------------------------------------
# 公开首页的接口
# ---------------------------------------------------------------------------

class PublicApiTest(WebUiCase):
    login_first = False

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.set_config('security.key.enable', True)
        users_service.create_user('webui-public', 'public-key-1')
        self.addCleanup(lambda: [users_service.delete_user(u['id']) for u in users_service.list_users()
                                 if u['name'] == 'webui-public'])
        self.addCleanup(self.delete_logs)

    def delete_logs(self):
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM parse_logs WHERE song_id LIKE 'webui%'")
            conn.commit()
        finally:
            conn.close()

    def logs(self):
        conn = db.get_connection()
        try:
            return [dict(row) for row in conn.execute(
                "SELECT username, success, error_message FROM parse_logs WHERE song_id LIKE 'webui%' ORDER BY id")]
        finally:
            conn.close()

    async def resolve(self, **overrides):
        body = dict({'source': 'tx', 'song_id': 'webui001', 'quality': '320k',
                     'username': 'webui-public', 'key': 'public-key-1'}, **overrides)
        return await self.call('POST', '/api/public/resolve', body, cookies=None)

    async def test_status(self):
        self.set_config('module.kg.enable', False)
        _, body = await self.call('GET', '/api/public/status', cookies=None)
        data = body['data']
        self.assertEqual([s['id'] for s in data['sources']], ['tx', 'wy'])
        self.assertEqual(data['sources'][0]['qualities'], config_schema.QUALITY_OPTIONS['tx'])
        self.assertTrue(data['key_required'])

    async def test_resolve_validates_the_request(self):
        self.set_config('module.kg.enable', False)
        for overrides, message in (({'source': 'mg'}, '不支持的平台'), ({'source': 'kg'}, '不支持的平台'),
                                   ({'quality': 'sky'}, '不支持的音质'), ({'song_id': '../x'}, '歌曲 ID'),
                                   ({'song_id': ''}, '歌曲 ID'), ({'key': ''}, '请输入用户名和 Key')):
            status, body = await self.resolve(**overrides)
            self.assertEqual(status, 400, overrides)
            self.assertIn(message, body['msg'])

    async def test_bad_keys_are_rate_limited(self):
        for _ in range(admin_auth.LOGIN_MAX_FAILURES):
            status, _ = await self.resolve(key='bad-key')
            self.assertEqual(status, 403)
        status, _ = await self.resolve()
        self.assertEqual(status, 429)

    async def test_resolve_success_and_failures_are_recorded(self):
        result = {'code': 0, 'data': 'https://cdn.example/song.mp3',
                  'extra': {'cache': True, 'quality': {'result': '128k'}, 'expire': {'time': 1234}}}
        with mock.patch.object(modules, 'url', new=mock.AsyncMock(return_value=result)) as url:
            status, body = await self.resolve()
        self.assertEqual(status, 200)
        self.assertEqual(body['data'], {'url': 'https://cdn.example/song.mp3', 'quality': '128k', 'cached': True,
                                        'expire_at': 1234})
        url.assert_awaited_once_with('tx', 'webui001', '320k', {})

        with mock.patch.object(modules, 'url', new=mock.AsyncMock(return_value={'code': 2, 'msg': '无版权'})):
            status, body = await self.resolve(song_id='webui002')
        self.assertEqual((status, body['msg']), (400, '无版权'))
        with mock.patch.object(modules, 'url', new=mock.AsyncMock(side_effect=RuntimeError('secret detail'))):
            status, body = await self.resolve(song_id='webui003')
        self.assertEqual((status, body['msg']), (400, '解析失败，请稍后再试'))
        self.assertEqual(self.logs(), [
            {'username': 'webui-public', 'success': 1, 'error_message': None},
            {'username': 'webui-public', 'success': 0, 'error_message': '无版权'},
            {'username': 'webui-public', 'success': 0, 'error_message': '内部错误'},
        ])

    async def test_no_key_needed_when_key_auth_is_off(self):
        self.set_config('security.key.enable', False)
        result = {'code': 0, 'data': 'https://cdn.example/a.mp3'}
        with mock.patch.object(modules, 'url', new=mock.AsyncMock(return_value=result)):
            status, body = await self.resolve(username='', key='')
        self.assertEqual((status, body['data']['url']), (200, 'https://cdn.example/a.mp3'))
        self.assertEqual(self.logs()[-1]['username'], None)


# ---------------------------------------------------------------------------
# 页面、静态文件、响应头
# ---------------------------------------------------------------------------

class PagesTest(WebUiCase):
    login_first = False

    async def test_pages_are_spa_shells_with_security_headers(self):
        for path, script in (('/', 'public.js'), ('/admin', 'admin.js'), ('/admin/users', 'admin.js'),
                             ('/admin/config/whatever', 'admin.js')):
            resp = await self.client.get(path, allow_redirects=False)
            self.assertEqual(resp.status, 200, path)  # 未登录也不跳转，由前端显示登录页
            text = await resp.text()
            self.assertIn(f'src="/static/js/{script}"', text)
            self.assertNotIn('style=', text)  # CSP 不允许内联样式
            headers = resp.headers
            self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertEqual(headers['X-Frame-Options'], 'DENY')
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(headers['Cache-Control'], 'no-store')

    async def test_static_files(self):
        for path, content_type in (('/static/css/app.css', 'text/css'), ('/static/js/admin.js', 'javascript'),
                                   ('/static/img/logo.svg', 'image/svg+xml')):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 200, path)
            self.assertIn(content_type, resp.headers['Content-Type'])
            self.assertEqual(resp.headers['Cache-Control'], 'no-cache')
            self.assertEqual(resp.headers['X-Content-Type-Options'], 'nosniff')
        for path in ('/static/missing.js', '/static/../api_admin.py', '/static/%2e%2e/api_admin.py', '/static/'):
            self.assertIn((await self.client.get(path)).status, (403, 404), path)

    async def test_api_responses_are_not_cached(self):
        for path in ('/api/public/status', '/api/admin/me'):
            resp = await self.client.get(path)
            self.assertEqual(resp.headers['Cache-Control'], 'no-store', path)
            self.assertEqual(resp.headers['Content-Type'], 'application/json; charset=utf-8')

    def test_every_js_import_resolves(self):
        js_root = os.path.join(routes.STATIC_DIR, 'js')
        pattern = re.compile(r"""(?:import|from)\s*\(?\s*['"](\.{1,2}/[^'"]+)['"]""")
        count = 0
        for folder, _, files in os.walk(js_root):
            for name in files:
                path = os.path.join(folder, name)
                with open(path, encoding='utf-8') as f:
                    for target in pattern.findall(f.read()):
                        count += 1
                        self.assertTrue(os.path.isfile(os.path.normpath(os.path.join(folder, target))),
                                        f'{name} -> {target}')
        self.assertGreater(count, 10)


class RateLimitExemptionTest(unittest.TestCase):
    def test_only_parse_requests_are_rate_limited(self):
        import main
        for path in ('/', '/static/js/admin.js', '/admin', '/admin/users', '/api/admin/me', '/api/public/status'):
            self.assertTrue(main._is_webui_request(path), path)
        for path in ('/api/public/resolve', '/url/tx/1/128k', '/script', '/info/tx/1'):
            self.assertFalse(main._is_webui_request(path), path)


if __name__ == '__main__':
    unittest.main()
