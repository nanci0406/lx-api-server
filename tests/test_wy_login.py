import _env  # noqa: F401

import asyncio
import json
import re
import sys
import unittest
from binascii import unhexlify
from unittest import mock

from Crypto.Cipher import AES

from common import Httpx, config, login_session, variable
from common.exceptions import FailedException
from modules.wy import client
from modules.wy import login
from modules.wy import refresh_login as wy_refresh

FUTURE = 'Expires=Fri, 01-Jan-2100 00:00:00 GMT'


def decrypt_eapi(form):
    """解开 eapi 请求体，返回 (接口路径, 参数)"""
    data = AES.new(b'e82ckenh8dichen8', AES.MODE_ECB).decrypt(unhexlify(form['params']))
    data = data[:-data[-1]].decode()
    path, text, _ = data.split('-36cd479b6b5-')
    return path, json.loads(text)


class FakeResponse:
    def __init__(self, body, set_cookies=()):
        self.body = body
        self.set_cookies = list(set_cookies)

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeNetease:
    """按接口路径返回预设的响应，记录收到的请求(已解密)"""

    def __init__(self):
        self.requests = []
        self.routes = {}  # 路径 -> 响应列表(依次返回，最后一个重复使用)

    def on(self, path, *responses):
        self.routes[path] = list(responses)

    async def __call__(self, url, options=None):
        path, params = decrypt_eapi(options['form'])
        self.requests.append({'url': url, 'path': path, 'params': params, 'headers': options['headers']})
        queue = self.routes[path]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def calls(self, path):
        return [r for r in self.requests if r['path'] == path]


def cookie_header(request):
    return dict(part.split('=', 1) for part in request['headers']['Cookie'].split('; '))


class WyLoginTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        login_session._sessions.clear()
        variable.use_cookie_pool = False
        self.fake = FakeNetease()
        self.fake.on('/api/login/qrcode/unikey', FakeResponse({'code': 200, 'unikey': 'UNIKEY-1'}))
        self.fake.on('/api/nuser/account/get',
                     FakeResponse({'code': 200, 'account': {'id': 42}, 'profile': {'userId': 42, 'nickname': 'Neo'}}))
        for patcher in (mock.patch.object(Httpx, 'AsyncRequest', new=self.fake),
                        mock.patch.object(login, 'POLL_INTERVAL', 0.01)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(login_session._sessions.clear)

    async def wait_for(self, ls, states, timeout=3):
        for _ in range(int(timeout / 0.01)):
            if ls.state in states:
                return
            await asyncio.sleep(0.01)
        self.fail(f'状态一直是 {ls.state}')

    def done_responses(self, *set_cookies):
        self.fake.on('/api/login/qrcode/client/login',
                     FakeResponse({'code': 801, 'message': '等待扫码'}),
                     FakeResponse({'code': 802, 'message': '授权中', 'nickname': 'Scanner'}),
                     FakeResponse({'code': 803, 'message': '授权登陆成功'}, set_cookies or [
                         f'MUSIC_U=NEW_U; Max-Age=15552000; {FUTURE}; Path=/; HTTPOnly',
                         f'__csrf=CSRF1; Max-Age=1296010; {FUTURE}; Path=/',
                         'MUSIC_SNS=; Max-Age=0; Path=/',
                     ]))


class WyQrLoginTest(WyLoginTestCase):
    async def test_full_flow(self):
        self.done_responses()
        ls = await login.start_qr('admin')
        self.assertEqual((ls.kind, ls.platform, ls.mimetype), ('wy', 'wy', 'image/svg+xml'))
        self.assertIn(b'<svg', ls.image)
        await self.wait_for(ls, ('done',))

        cookie = client.parse_cookie(ls.credential['cookie'])
        self.assertEqual((cookie['MUSIC_U'], cookie['__csrf'], cookie['os']), ('NEW_U', 'CSRF1', 'pc'))
        self.assertNotIn('MUSIC_SNS', cookie)  # 被删除的 Cookie 不保存
        self.assertRegex(cookie['deviceId'], r'^[0-9A-F]{52}$')
        self.assertEqual(ls.public()['account'], {'uin': '42', 'nick': 'Neo', 'has_refresh': True})
        self.assertNotIn('NEW_U', json.dumps(ls.public()))  # 状态接口不能带出凭证

        unikey = self.fake.calls('/api/login/qrcode/unikey')[0]
        self.assertEqual(unikey['url'], 'https://interface.music.163.com/eapi/login/qrcode/unikey')
        self.assertEqual(unikey['params']['type'], 3)
        self.assertEqual(unikey['headers']['User-Agent'], client.EAPI_UA)
        checks = self.fake.calls('/api/login/qrcode/client/login')
        self.assertEqual({c['params']['key'] for c in checks}, {'UNIKEY-1'})
        # 整个登录用同一台"设备"，保存下来的 deviceId 也是它
        devices = {cookie_header(r)['deviceId'] for r in self.fake.requests}
        self.assertEqual(devices, {cookie['deviceId']})
        account = self.fake.calls('/api/nuser/account/get')[0]
        self.assertEqual(account['params']['header']['MUSIC_U'], 'NEW_U')

    async def test_scanner_nickname_is_shown_while_waiting_for_confirmation(self):
        self.fake.on('/api/login/qrcode/client/login', FakeResponse({'code': 802, 'nickname': 'Scanner'}))
        ls = await login.start_qr('admin')
        await self.wait_for(ls, ('conf',))
        await asyncio.sleep(0.05)
        self.assertEqual((ls.state, ls.message), ('conf', 'Scanner'))
        login_session.cancel_session(ls.id, 'admin')
        self.assertEqual(ls.state, 'cancelled')

    async def test_expired_qr(self):
        self.fake.on('/api/login/qrcode/client/login', FakeResponse({'code': 800, 'message': '二维码不存在或已过期'}))
        ls = await login.start_qr('admin')
        await self.wait_for(ls, ('timeout',))
        self.assertIsNone(ls.credential)

    async def test_risk_control_and_bad_responses_are_errors(self):
        for response, message in ((FakeResponse({'code': 8821, 'message': '需要行为验证码验证'}), '安全验证'),
                                  (FakeResponse(ValueError('not json')), '无法识别'),
                                  (FakeResponse({'code': 803}, []), 'MUSIC_U')):
            self.fake.on('/api/login/qrcode/client/login', response)
            ls = await login.start_qr('admin')
            await self.wait_for(ls, ('error',))
            self.assertIn(message, ls.message)

    async def test_account_lookup_failure_is_an_error(self):
        self.done_responses()
        self.fake.on('/api/nuser/account/get', FakeResponse({'code': 200, 'account': None, 'profile': None}))
        ls = await login.start_qr('admin')
        await self.wait_for(ls, ('error',))
        self.assertIn('账号信息', ls.message)
        self.assertIsNone(ls.credential)

    async def test_start_failure_registers_no_session(self):
        self.fake.on('/api/login/qrcode/unikey', FakeResponse({'code': -460, 'message': 'Cheating'}))
        with self.assertRaises(login.LoginError) as ctx:
            await login.start_qr('admin')
        self.assertIn('-460', ctx.exception.message)
        self.assertEqual(login_session._sessions, {})

    async def test_sessions_belong_to_their_owner(self):
        self.done_responses()
        ls = await login.start_qr('admin')
        self.assertIs(login_session.get_session(ls.id, 'admin'), ls)
        self.assertIsNone(login_session.get_session(ls.id, 'someone-else'))
        self.assertFalse(login_session.cancel_session(ls.id, 'someone-else'))


class WyApplyTest(WyLoginTestCase):
    def setUp(self):
        for key in ('module.wy.user.cookie', 'module.wy.user.refresh_login', 'module.cookiepool.wy'):
            self.addCleanup(config.write_config, key, config.read_config(key))

    def done_session(self, uid='42', cookie='MUSIC_U=NEW_U; os=pc'):
        ls = login.LoginSession('wy', 'admin')
        ls.credential = {'cookie': cookie, 'uin': uid, 'nick': 'Neo', 'has_refresh': True}
        ls.finish('done', '登录成功')
        return ls

    def test_save_as_main_account(self):
        config.write_config('module.wy.user.refresh_login', {'enable': False, 'interval': 0})
        ls = self.done_session()
        note = login.apply_credential(ls, 'main', True)
        self.assertIn('主账号', note)
        self.assertEqual(config.read_config('module.wy.user.cookie'), 'MUSIC_U=NEW_U; os=pc')
        self.assertTrue(config.read_config('module.wy.user.refresh_login.enable'))
        self.assertEqual(config.read_config('module.wy.user.refresh_login.interval'), login.DEFAULT_REFRESH_INTERVAL)
        self.assertEqual((ls.state, ls.credential), ('applied', None))
        with self.assertRaises(login.LoginError):
            login.apply_credential(ls, 'main', True)  # 不能重复保存

    def test_pool_replaces_the_same_account_and_drops_placeholders(self):
        config.write_config('module.cookiepool.wy', [
            {'cookie': '', 'refresh_login': {'enable': False, 'interval': 86400}},  # 默认配置里的占位
            {'cookie': 'MUSIC_U=OLD42', 'uid': '42', 'refresh_login': {'enable': False, 'interval': 3600}},
            {'cookie': 'MUSIC_U=OTHER'},
        ])
        note = login.apply_credential(self.done_session(), 'pool', True)
        self.assertIn('共 2 个账号', note)
        pool = config.read_config('module.cookiepool.wy')
        self.assertEqual([a['cookie'] for a in pool], ['MUSIC_U=NEW_U; os=pc', 'MUSIC_U=OTHER'])
        self.assertEqual(dict(pool[0]['refresh_login']), {'enable': True, 'interval': 3600})  # 保留原来的间隔
        login.apply_credential(self.done_session(uid='7', cookie='MUSIC_U=SEVEN'), 'pool', False)
        pool = config.read_config('module.cookiepool.wy')
        self.assertEqual((pool[-1]['uid'], pool[-1]['refresh_login']['enable']), ('7', False))

    def test_rejects_unfinished_sessions_and_unknown_targets(self):
        pending = login.LoginSession('wy', 'admin')
        with self.assertRaises(login.LoginError):
            login.apply_credential(pending, 'main', True)
        with self.assertRaises(login.LoginError):
            login.apply_credential(self.done_session(), 'nowhere', True)


class WyRefreshRequestTest(unittest.IsolatedAsyncioTestCase):
    """刷新登录的请求参数按 NeteaseCloudMusicApi 的方式填写"""

    def setUp(self):
        variable.use_cookie_pool = False
        self.addCleanup(config.write_config, 'module.wy.user.cookie', config.read_config('module.wy.user.cookie'))
        self.fake = FakeNetease()
        self.fake.on('/api/login/token/refresh', FakeResponse({'code': 200}, [f'MUSIC_U=FRESH; {FUTURE}']))
        patcher = mock.patch.object(Httpx, 'AsyncRequest', new=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_browser_cookie_gets_pc_client_defaults(self):
        config.write_config('module.wy.user.cookie', 'MUSIC_U=WEB_U; __csrf=C1')  # 从浏览器复制的 cookie
        await wy_refresh.refresh()
        request = self.fake.requests[0]
        self.assertEqual(request['url'], 'https://interface.music.163.com/eapi/login/token/refresh')
        self.assertEqual(request['headers']['User-Agent'], client.EAPI_UA)
        header = request['params']['header']
        self.assertEqual((header['os'], header['appver'], header['channel']), ('pc', '3.1.17.204416', 'netease'))
        self.assertEqual((header['MUSIC_U'], header['__csrf']), ('WEB_U', 'C1'))
        self.assertRegex(header['deviceId'], r'^[0-9A-F]{52}$')
        self.assertRegex(header['requestId'], r'^\d{13}_\d{4}$')
        self.assertEqual(cookie_header(request)['deviceId'], header['deviceId'])
        self.assertEqual(config.read_config('module.wy.user.cookie'), 'MUSIC_U=FRESH; __csrf=C1')

    async def test_saved_device_is_reused(self):
        config.write_config('module.wy.user.cookie', 'MUSIC_U=U; os=iPhone OS; deviceId=DEV1')
        await wy_refresh.refresh()
        header = self.fake.requests[0]['params']['header']
        self.assertEqual((header['os'], header['deviceId'], header['appver']), ('iPhone OS', 'DEV1', '9.0.90'))
        self.assertIn('os=iPhone%20OS', self.fake.requests[0]['headers']['Cookie'])  # 和 encodeURIComponent 一致

    async def test_expired_token_explains_what_to_do(self):
        config.write_config('module.wy.user.cookie', 'MUSIC_U=DEAD')
        self.fake.on('/api/login/token/refresh', FakeResponse({'code': 301}))
        with self.assertRaises(FailedException) as ctx:
            await wy_refresh.refresh()
        self.assertIn('code: 301', str(ctx.exception))
        self.assertIn('重新登录', str(ctx.exception))

    async def test_cookie_without_music_u_is_rejected_without_a_request(self):
        config.write_config('module.wy.user.cookie', 'NMTID=abc; os=pc')
        with self.assertRaises(FailedException) as ctx:
            await wy_refresh.refresh()
        self.assertIn('MUSIC_U', str(ctx.exception))
        self.assertEqual(self.fake.requests, [])


class QrImageTest(unittest.TestCase):
    def test_svg_has_a_white_background_and_encodes_the_login_url(self):
        image = login.qr_svg(login.QR_CONTENT.format(key='abc')).decode()
        self.assertTrue(image.lstrip().startswith('<?xml'))
        self.assertTrue(re.search(r'fill="(white|#fff|#ffffff)"', image, re.I))

    def test_missing_qrcode_dependency_is_a_clear_error(self):
        # 升级后没有安装新依赖：服务照常启动，只有扫码登录提示安装
        with mock.patch.dict(sys.modules, {'qrcode': None, 'qrcode.image.svg': None}):
            with self.assertRaises(login.LoginError) as ctx:
                login.qr_svg('x')
        self.assertIn('pip install', ctx.exception.message)


if __name__ == '__main__':
    unittest.main()
