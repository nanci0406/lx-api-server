import _env  # noqa: F401

import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from common import config, db, variable
from common.services import admin_auth
from webui import routes

PASSWORD = _env.ADMIN_PASSWORD
USERNAME = _env.ADMIN_USERNAME


class WebUiTest(unittest.IsolatedAsyncioTestCase):
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

    async def login(self, password=PASSWORD, headers=None):
        return await self.client.post('/admin/login', data={'username': USERNAME, 'password': password},
                                      allow_redirects=False, headers=headers)

    async def session_cookie(self):
        resp = await self.login()
        self.assertEqual(resp.status, 302)
        # 客户端会自动保存 Cookie；清掉它，才能区分"带 Cookie"和"匿名"的请求
        self.client.session.cookie_jar.clear()
        return {admin_auth.COOKIE_NAME: resp.cookies[admin_auth.COOKIE_NAME].value}

    # ---- 登录 ----
    async def test_login_success_sets_http_only_cookie(self):
        resp = await self.login()
        self.assertEqual(resp.status, 302)
        cookie = resp.cookies[admin_auth.COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertFalse(cookie['secure'])  # 纯 HTTP 访问

    async def test_cookie_is_secure_when_declared_https(self):
        config.write_config('common.ssl_info.is_https', True)
        self.addCleanup(config.write_config, 'common.ssl_info.is_https', False)
        resp = await self.login()
        self.assertTrue(resp.cookies[admin_auth.COOKIE_NAME]['secure'])

    async def test_wrong_password_then_rate_limited(self):
        for _ in range(admin_auth.LOGIN_MAX_FAILURES):
            self.assertEqual((await self.login('wrong')).status, 403)
        self.assertEqual((await self.login('wrong')).status, 429)
        # 被限制期间，即使密码正确也不放行
        self.assertEqual((await self.login()).status, 429)

    async def test_successful_login_resets_failure_count(self):
        for _ in range(admin_auth.LOGIN_MAX_FAILURES - 1):
            await self.login('wrong')
        self.assertEqual((await self.login()).status, 302)
        for _ in range(admin_auth.LOGIN_MAX_FAILURES - 1):
            self.assertEqual((await self.login('wrong')).status, 403)

    # ---- 退出 / 带副作用的 GET ----
    async def test_logout_requires_post(self):
        cookies = await self.session_cookie()
        resp = await self.client.get('/admin/logout', cookies=cookies, allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers['Location'], '/admin')
        self.assertEqual((await self.client.get('/admin', cookies=cookies, allow_redirects=False)).status, 200)

        resp = await self.client.post('/admin/logout', cookies=cookies, allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers['Location'], '/admin/login')
        resp = await self.client.get('/admin', cookies=cookies, allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.headers['Location'], '/admin/login')

    async def test_old_get_urls_only_redirect(self):
        cookies = await self.session_cookie()
        for path, target in (('/admin/config/reload', '/admin/config'), ('/admin/health/refresh', '/admin/health')):
            resp = await self.client.get(path, cookies=cookies, allow_redirects=False)
            self.assertEqual(resp.status, 302)
            self.assertEqual(resp.headers['Location'], target)

    async def test_pages_use_post_forms_for_actions(self):
        cookies = await self.session_cookie()
        for path, action in (('/admin', '/admin/logout'), ('/admin/config', '/admin/config/reload'),
                             ('/admin/health', '/admin/health/refresh')):
            text = await (await self.client.get(path, cookies=cookies)).text()
            self.assertIn(f'<form method="post" action="{action}">', text, path)
            self.assertNotIn(f'href="{action}"', text, path)

    # ---- 来源校验 ----
    async def test_cross_origin_post_is_rejected(self):
        cookies = await self.session_cookie()
        data = {'section_title': 'no-such-section'}
        evil = await self.client.post('/admin/config', data=data, cookies=cookies,
                                      headers={'Origin': 'http://evil.example'})
        self.assertEqual(evil.status, 403)
        evil_referer = await self.client.post('/admin/config', data=data, cookies=cookies,
                                              headers={'Referer': 'http://evil.example/page'})
        self.assertEqual(evil_referer.status, 403)
        same = await self.client.post('/admin/config', data=data, cookies=cookies, headers={'Origin': self.origin})
        self.assertEqual(same.status, 200)
        no_header = await self.client.post('/admin/config', data=data, cookies=cookies)
        self.assertEqual(no_header.status, 200)
        proxied = await self.client.post('/admin/config', data=data, cookies=cookies,
                                         headers={'Origin': 'https://music.example.com',
                                                  'X-Forwarded-Host': 'music.example.com'})
        self.assertEqual(proxied.status, 200)

    async def test_origin_check_can_be_disabled(self):
        config.write_config('security.admin_origin_check', False)
        cookies = await self.session_cookie()
        resp = await self.client.post('/admin/config', data={'section_title': 'x'}, cookies=cookies,
                                      headers={'Origin': 'http://evil.example'})
        self.assertEqual(resp.status, 200)

    async def test_login_post_also_checks_origin(self):
        resp = await self.login(headers={'Origin': 'http://evil.example'})
        self.assertEqual(resp.status, 403)

    # ---- 健康状态里的管理员详情 ----
    async def test_admin_detail_is_only_visible_to_admins(self):
        conn = db.get_connection()
        try:
            conn.execute(
                'INSERT INTO module_health (source, status, detail, checked_at, admin_detail) '
                "VALUES ('tx', 'degraded', '账号登录状态异常', 1, 'qqmusic_refresh_login 已连续失败 3 次') "
                'ON CONFLICT(source) DO UPDATE SET status = excluded.status, detail = excluded.detail, '
                'admin_detail = excluded.admin_detail')
            conn.commit()
        finally:
            conn.close()
        cookies = await self.session_cookie()

        public = await (await self.client.get('/api/webui/module-health?scope=public')).json()
        anonymous = await (await self.client.get('/api/webui/module-health')).json()
        admin = await (await self.client.get('/api/webui/module-health', cookies=cookies)).json()
        for payload in (public, anonymous):
            self.assertTrue(payload['data'])
            self.assertTrue(all('admin_detail' not in row for row in payload['data']))
        self.assertTrue(any(row.get('admin_detail') for row in admin['data']))

        home = await (await self.client.get('/')).text()
        self.assertNotIn('qqmusic_refresh_login', home)
        admin_page = await (await self.client.get('/admin/health', cookies=cookies)).text()
        self.assertIn('qqmusic_refresh_login 已连续失败 3 次', admin_page)

    # ---- 配置保存 ----
    async def test_config_save_is_all_or_nothing_and_does_not_touch_memory_without_reload(self):
        cookies = await self.session_cookie()
        config.write_config('module.tx.user.refresh_login.interval', 111)
        config.write_config('module.tx.user.refresh_key', 'before')
        data = {
            'section_title': 'QQ 自动登录',
            'module.tx.user.refresh_login.enable': 'false',
            'module.tx.user.refresh_login.interval': 'not-a-number',  # 无法解析为整数
            'module.tx.user.refresh_key': 'after',
        }
        resp = await self.client.post('/admin/config', data=data, cookies=cookies)
        self.assertIn('保存失败', await resp.text())
        self.assertNotIn('after', config.read_config_text())  # 一项出错，整个分组都不写入

        data['module.tx.user.refresh_login.interval'] = '222'
        resp = await self.client.post('/admin/config', data=data, cookies=cookies)
        self.assertIn('已保存到配置文件', await resp.text())
        self.assertIn('after', config.read_config_text())
        self.assertEqual(config.read_config('module.tx.user.refresh_key'), 'before')  # 仅保存：内存不变
        config.reload_config()
        self.assertEqual(config.read_config('module.tx.user.refresh_key'), 'after')

    # ---- 修改密码 ----
    async def test_password_change_validates_and_keeps_current_session_only(self):
        cookies = await self.session_cookie()
        other = await self.session_cookie()
        self.assertNotEqual(cookies, other)
        conn = db.get_connection()
        try:
            admin_id = conn.execute('SELECT id FROM admins WHERE username = ?', (USERNAME,)).fetchone()['id']
        finally:
            conn.close()

        short = await self.client.post('/admin/admins/password', cookies=cookies, data={
            'admin_id': admin_id, 'new_password': 'short', 'confirm_password': 'short'})
        self.assertIn('至少需要', await short.text())

        new_password = 'brand-new-password'
        try:
            ok = await self.client.post('/admin/admins/password', cookies=cookies, data={
                'admin_id': admin_id, 'new_password': new_password, 'confirm_password': new_password})
            self.assertIn('密码已更新', await ok.text())
            self.assertEqual((await self.client.get('/admin', cookies=cookies, allow_redirects=False)).status, 200)
            self.assertEqual((await self.client.get('/admin', cookies=other, allow_redirects=False)).status, 302)
        finally:
            admin_auth.update_admin_password(admin_id, PASSWORD)

    # ---- 公开下载页的 key 校验限速 ----
    async def test_download_link_rate_limits_bad_keys(self):
        form = {'username': 'nobody', 'key': 'bad', 'source': 'tx', 'song_id': '1', 'quality': '128k'}
        for _ in range(admin_auth.LOGIN_MAX_FAILURES):
            self.assertEqual((await self.client.post('/download-link', data=form)).status, 403)
        self.assertEqual((await self.client.post('/download-link', data=form)).status, 429)


if __name__ == '__main__':
    unittest.main()
