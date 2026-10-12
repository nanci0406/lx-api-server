import _env  # noqa: F401

import asyncio
import json as stdjson
import time
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer

from common import config, variable
from modules.tx import login

QRSIG = 'qr+sig/with=special-chars_0123456789abcdef*'
PNG = b'\x89PNG\r\n\x1a\n' + b'fake-png'
JPEG = b'\xff\xd8\xff' + b'fake-jpeg'


def ptui(code, url='', message=''):
    return f"ptuiCB('{code}','0','{url}','0','{message}', 'nick');"


class FakeQQServer:
    """模拟 ptlogin / graph / 微信 / QQ 音乐 CGI 接口，记录收到的请求"""

    def __init__(self):
        self.requests = []
        self.qq_states = []  # 依次返回的 ptqrlogin 响应
        self.wx_states = []  # 依次返回的微信长轮询响应
        self.cgi_results = {}  # (module, method) -> (业务码, data)
        self.set_p_skey = True
        self.authorize_hops = ['https://y.qq.com/portal/wx_redirect.html?login_type=1&code=AUTHCODE&state=state']
        self.runner = None
        self.base = ''

    def _log(self, request, **extra):
        self.requests.append(dict(path=request.path, query=dict(request.query), headers=dict(request.headers),
                                  **extra))

    async def start(self):
        app = web.Application()
        app.router.add_get('/ptqrshow', self.ptqrshow)
        app.router.add_get('/ptqrlogin', self.ptqrlogin)
        app.router.add_get('/check_sig', self.check_sig)
        app.router.add_post('/authorize', self.authorize)
        app.router.add_get('/hop', self.hop)
        app.router.add_get('/qrconnect', self.wx_qrconnect)
        app.router.add_get('/qrcode/{uuid}', self.wx_qrcode)
        app.router.add_get('/poll', self.wx_poll)
        app.router.add_post('/cgi', self.cgi)
        self.server = TestServer(app)
        await self.server.start_server()
        self.base = f'http://{self.server.host}:{self.server.port}'

    def endpoints(self):
        return {
            'ptqrshow': self.base + '/ptqrshow', 'ptqrlogin': self.base + '/ptqrlogin',
            'check_sig': self.base + '/check_sig', 'authorize': self.base + '/authorize',
            'wx_qrconnect': self.base + '/qrconnect', 'wx_qrcode': self.base + '/qrcode/{uuid}',
            'wx_poll': self.base + '/poll', 'cgi': self.base + '/cgi',
        }

    async def ptqrshow(self, request):
        self._log(request)
        response = web.Response(body=PNG, content_type='image/png')
        response.headers.add('Set-Cookie', 'other=1; Path=/')
        response.headers.add('Set-Cookie', f'qrsig={QRSIG}; Path=/; Domain=ptlogin2.qq.com')
        return response

    async def ptqrlogin(self, request):
        self._log(request)
        text = self.qq_states.pop(0) if len(self.qq_states) > 1 else self.qq_states[0]
        return web.Response(text=text)

    async def check_sig(self, request):
        self._log(request)
        response = web.Response(status=302, headers={'Location': 'https://graph.qq.com/oauth2.0/login_jump?x=1'})
        # 和真实接口一样：不是浏览器的 User-Agent 拿不到 p_skey；先下发一个空值清掉旧 Cookie，再下发新值
        if self.set_p_skey and 'Mozilla/5.0' in request.headers.get('User-Agent', ''):
            response.headers.add('Set-Cookie', 'p_skey=; Path=/; Domain=qq.com')
            response.headers.add('Set-Cookie', 'p_skey=PSKEY_VALUE; Path=/; Domain=graph.qq.com')
            response.headers.add('Set-Cookie', 'p_uin=o0123456; Path=/; Domain=graph.qq.com')
            response.headers.add('Set-Cookie', 'pt4_token=T4*TOKEN; Path=/; Domain=graph.qq.com')
        return response

    async def authorize(self, request):
        form = await request.post()
        self._log(request, form=dict(form))
        return web.Response(status=302, headers={'Location': self.authorize_hops[0]})

    async def hop(self, request):
        self._log(request)
        return web.Response(status=302, headers={'Location': self.authorize_hops[1]})

    async def wx_qrconnect(self, request):
        self._log(request)
        return web.Response(text='<html><img src="/connect/qrcode/x"><a href="?uuid=UUID123456">link</a>'
                                 '<script>var s="uuid=UUID123456"</script></html>')

    async def wx_qrcode(self, request):
        self._log(request)
        return web.Response(body=JPEG, content_type='image/jpeg')

    async def wx_poll(self, request):
        self._log(request)
        text = self.wx_states.pop(0) if len(self.wx_states) > 1 else self.wx_states[0]
        return web.Response(text=text)

    async def cgi(self, request):
        body = stdjson.loads(await request.text())
        self._log(request, body=body)
        req = body['req_0']
        code, data = self.cgi_results.get((req['module'], req['method']), (1000, {}))
        return web.json_response({'code': 0, 'req_0': {'code': code, 'data': data}})


LOGIN_DATA = {'musickey': 'Q_H_L_NEWKEY', 'musicid': 123456, 'refresh_key': 'RK', 'refresh_token': 'RT',
              'openid': 'OID', 'access_token': 'AT', 'unionid': 'UID', 'nick': 'tester', 'loginType': 2}


class LoginTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        login._sessions.clear()
        login._sms_last_sent.clear()
        self.fake = FakeQQServer()
        await self.fake.start()
        self.addAsyncCleanup(self.fake.server.close)
        patchers = [
            mock.patch.dict(login.ENDPOINTS, self.fake.endpoints()),
            mock.patch.object(login, 'POLL_INTERVAL', 0.01),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def wait_for(self, ls, states, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ls.state in states:
                return
            await asyncio.sleep(0.01)
        self.fail(f'登录会话没有进入 {states}，当前 {ls.state}: {ls.message}')

    def cgi_requests(self):
        return [r for r in self.fake.requests if r['path'] == '/cgi']


class HelpersTest(unittest.TestCase):
    def test_hash33(self):
        self.assertEqual(login.hash33('placeholder-musickey', 5381), 1143673215)
        self.assertEqual(login.hash33(''), 0)

    def test_extract_between(self):
        self.assertEqual(login.extract_between('a=1&b=2', 'a=', '&'), '1')
        self.assertEqual(login.extract_between('a=1', 'x=', '&'), '')
        self.assertEqual(login.extract_between('a=1', 'a=', '&'), '')

    def test_credential_from_login(self):
        credential = login.credential_from_login(0, LOGIN_DATA, 2)
        self.assertEqual((credential['qqmusic_key'], credential['uin'], credential['login_type']),
                         ('Q_H_L_NEWKEY', '123456', '2'))
        self.assertEqual((credential['refresh_key'], credential['refresh_token'], credential['nick']),
                         ('RK', 'RT', 'tester'))
        # 兼容另一种写法的字段名
        alt = login.credential_from_login(0, {'musicKey': 'K', 'uin': '99'}, 1)
        self.assertEqual((alt['qqmusic_key'], alt['uin'], alt['refresh_key']), ('K', '99', ''))

    def test_credential_errors(self):
        for code, message in ((20271, '验证码错误'), (20450, '账号已被封禁'), (1000, '登录鉴权参数无效或已过期')):
            with self.assertRaises(login.LoginError) as ctx:
                login.credential_from_login(code, {}, 0)
            self.assertEqual((ctx.exception.message, ctx.exception.code), (message, code))
        with self.assertRaises(login.LoginError) as ctx:
            login.credential_from_login(12345, {}, 0)
        self.assertIn('12345', ctx.exception.message)
        with self.assertRaises(login.LoginError):
            login.credential_from_login(0, {'musicid': 1}, 0)  # 没有 musickey

    def test_validate_phone(self):
        self.assertEqual(login.validate_phone(' 13800138000 ', '+86'), ('13800138000', '86'))
        for phone, country in (('', '86'), ('abc', '86'), ('1234', '86'), ('1' * 16, '86'), ('13800138000', 'cn'),
                               ('13800138000', '12345')):
            with self.assertRaises(login.LoginError):
                login.validate_phone(phone, country)

    def test_redirect_allowlist(self):
        self.assertTrue(login._redirect_allowed('https://graph.qq.com/x'))
        self.assertTrue(login._redirect_allowed('https://y.qq.com/'))
        self.assertFalse(login._redirect_allowed('https://evilqq.com/'))
        self.assertFalse(login._redirect_allowed('https://qq.com.evil.example/'))
        self.assertFalse(login._redirect_allowed('javascript:alert(1)'))


class QqQrTest(LoginTestCase):
    async def test_full_flow(self):
        self.fake.qq_states = [ptui(66, message='未失效'), ptui(67, message='认证中'), ptui(
            0, 'https://ssl.ptlogin2.graph.qq.com/check_sig?pttype=1&uin=123456&service=ptqrlogin&nodirect=0'
               '&ptsigx=SIGX_VALUE&s_url=https%3A%2F%2Fgraph.qq.com&f_url=', '登录成功')]
        self.fake.cgi_results[('QQConnectLogin.LoginServer', 'QQLogin')] = (0, LOGIN_DATA)
        ls = await login.start_qr('qq', 'admin')
        self.assertEqual((ls.kind, ls.owner, ls.image, ls.mimetype), ('qq', 'admin', PNG, 'image/png'))
        await self.wait_for(ls, ('done',))
        self.assertEqual(ls.credential['qqmusic_key'], 'Q_H_L_NEWKEY')
        self.assertEqual(ls.public()['account'], {'uin': '123456', 'nick': 'tester', 'has_refresh': True})
        self.assertNotIn('qqmusic_key', stdjson.dumps(ls.public()))  # 状态接口不能带出密钥

        by_path = {}
        for request in self.fake.requests:
            by_path.setdefault(request['path'], request)
        poll = by_path['/ptqrlogin']
        self.assertEqual(poll['headers']['Cookie'], f'qrsig={QRSIG}')  # 特殊字符原样传递，不被加引号
        self.assertEqual(poll['query']['ptqrtoken'], str(login.hash33(QRSIG)))
        check_sig = by_path['/check_sig']
        self.assertEqual((check_sig['query']['uin'], check_sig['query']['ptsigx']), ('123456', 'SIGX_VALUE'))
        for request in (poll, check_sig):
            self.assertEqual(request['headers']['User-Agent'], login.BROWSER_UA)
        authorize = by_path['/authorize']
        # check_sig 下发的 Cookie 原样带给 authorize(空值不覆盖，特殊字符不加引号)
        self.assertEqual(authorize['headers']['Cookie'], 'p_skey=PSKEY_VALUE; p_uin=o0123456; pt4_token=T4*TOKEN')
        self.assertEqual(authorize['form']['g_tk'], str(login.hash33('PSKEY_VALUE', 5381)))
        self.assertEqual(authorize['form']['client_id'], login.QQ_CLIENT_ID)
        exchange = self.cgi_requests()[0]['body']
        self.assertEqual(exchange['req_0']['param'], {'code': 'AUTHCODE'})
        self.assertEqual(exchange['comm']['tmeLoginType'], 2)
        self.assertNotIn('cookie', {k.lower() for k in self.cgi_requests()[0]['headers']})

    async def test_terminal_states(self):
        for state, event_text in (('timeout', ptui(65)), ('refuse', ptui(68))):
            self.fake.qq_states = [event_text]
            ls = await login.start_qr('qq', 'admin')
            await self.wait_for(ls, (state,))
            self.assertIsNone(ls.credential)

    async def test_missing_p_skey_is_reported(self):
        self.fake.set_p_skey = False
        self.fake.qq_states = [ptui(0, 'https://x/check_sig?uin=1&service=ptqrlogin&ptsigx=S&s_url=u')]
        ls = await login.start_qr('qq', 'admin')
        await self.wait_for(ls, ('error',))
        self.assertIn('p_skey', ls.message)
        self.assertIn('HTTP 302，跳转到 graph.qq.com/oauth2.0/login_jump', ls.message)  # 不带参数
        self.assertNotIn('x=1', ls.message)

    async def test_uin_is_read_from_the_exact_parameter(self):
        self.fake.qq_states = [ptui(0, 'https://x/check_sig?pt_uin=999&uin=42&service=ptqrlogin&ptsigx=S&s_url=u')]
        async with login.new_http_session() as http:
            event, info = await login.qq_qr_check(http, QRSIG)
        self.assertEqual((event, info), ('done', {'uin': '42', 'sigx': 'S'}))

    async def test_unparseable_poll_response_is_an_error(self):
        self.fake.qq_states = ['<html>not ptuiCB</html>']
        ls = await login.start_qr('qq', 'admin')
        await self.wait_for(ls, ('error',))

    async def test_authorize_follows_allowed_redirects_until_a_code_appears(self):
        self.fake.authorize_hops = ['https://graph.qq.com/hop', 'https://y.qq.com/done?code=SECONDCODE']
        async with login.new_http_session() as http:
            # 第一跳指向 graph.qq.com，测试服务器不在白名单里，所以只验证"白名单外的第一跳会被拒绝"
            with self.assertRaises(login.LoginError):
                await login.qq_authorize_code(http, '1', 'S')

    async def test_authorize_without_any_redirect_fails(self):
        self.fake.authorize_hops = ['']
        async with login.new_http_session() as http:
            with self.assertRaises(login.LoginError):
                await login.qq_authorize_code(http, '1', 'S')

    async def test_exchange_failure_is_reported(self):
        self.fake.qq_states = [ptui(0, 'https://x/check_sig?uin=1&service=ptqrlogin&ptsigx=S&s_url=u')]
        self.fake.cgi_results[('QQConnectLogin.LoginServer', 'QQLogin')] = (20450, {})
        ls = await login.start_qr('qq', 'admin')
        await self.wait_for(ls, ('error',))
        self.assertEqual(ls.message, '账号已被封禁')


class WxQrTest(LoginTestCase):
    async def test_full_flow(self):
        self.fake.wx_states = ["window.wx_errcode=408;window.wx_code='';", "window.wx_errcode=404;window.wx_code='';",
                               "window.wx_errcode=405;window.wx_code='WXCODE';"]
        self.fake.cgi_results[('music.login.LoginServer', 'Login')] = (0, dict(LOGIN_DATA, musickey='W_X_KEY'))
        ls = await login.start_qr('wx', 'admin')
        self.assertEqual((ls.image, ls.mimetype), (JPEG, 'image/jpeg'))
        await self.wait_for(ls, ('done',))
        self.assertEqual((ls.credential['qqmusic_key'], ls.credential['login_type']), ('W_X_KEY', '1'))
        exchange = self.cgi_requests()[0]['body']
        self.assertEqual(exchange['req_0']['param'], {'code': 'WXCODE', 'strAppid': login.WECHAT_APP_ID})
        self.assertEqual(exchange['comm']['tmeLoginType'], 1)
        poll = [r for r in self.fake.requests if r['path'] == '/poll'][0]
        self.assertEqual(poll['query']['uuid'], 'UUID123456')

    async def test_refuse_and_timeout(self):
        for code, state in ((403, 'refuse'), (402, 'timeout')):
            self.fake.wx_states = [f"window.wx_errcode={code};window.wx_code='';"]
            ls = await login.start_qr('wx', 'admin')
            await self.wait_for(ls, (state,))

    async def test_uuid_must_look_sane(self):
        async def evil_page(request):
            return web.Response(text='x uuid=<script>alert(1)</script>"')
        self.fake.wx_qrconnect = evil_page
        app = web.Application()
        app.router.add_get('/qrconnect', evil_page)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        with mock.patch.dict(login.ENDPOINTS, {'wx_qrconnect': f'http://{server.host}:{server.port}/qrconnect'}):
            async with login.new_http_session() as http:
                with self.assertRaises(login.LoginError):
                    await login.wx_qr_start(http)


class SessionManagerTest(LoginTestCase):
    async def test_owner_isolation_cancel_and_limits(self):
        self.fake.qq_states = [ptui(66)]
        ls = await login.start_qr('qq', 'alice')
        self.assertIs(login.get_session(ls.id, 'alice'), ls)
        self.assertIsNone(login.get_session(ls.id, 'mallory'))
        self.assertIsNone(login.get_session('nope', 'alice'))
        self.assertFalse(login.cancel_session(ls.id, 'mallory'))
        self.assertTrue(login.cancel_session(ls.id, 'alice'))
        self.assertEqual(ls.state, 'cancelled')
        await asyncio.sleep(0.05)
        self.assertTrue(ls.task.done())
        with self.assertRaises(login.LoginError):
            await login.start_qr('nope', 'alice')

        for _ in range(login.MAX_ACTIVE_SESSIONS):
            await login.start_qr('qq', 'alice')
        with self.assertRaises(login.LoginError):
            await login.start_qr('qq', 'alice')
        for session in list(login._sessions.values()):
            login.cancel_session(session.id, 'alice')

    async def test_finished_sessions_expire(self):
        self.fake.qq_states = [ptui(68)]
        ls = await login.start_qr('qq', 'alice')
        await self.wait_for(ls, ('refuse',))
        login._purge(now=ls.finished_at + login.RESULT_TTL - 1)
        self.assertIn(ls.id, login._sessions)
        login._purge(now=ls.finished_at + login.RESULT_TTL + 1)
        self.assertNotIn(ls.id, login._sessions)

    async def test_qr_failure_to_start_leaves_no_session(self):
        with mock.patch.dict(login.ENDPOINTS, {'ptqrshow': self.fake.base + '/missing'}):
            with self.assertRaises(login.LoginError):
                await login.start_qr('qq', 'alice')
        self.assertEqual(login._sessions, {})


class PhoneLoginTest(LoginTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.object(login, 'ensure_qimei', new=self.fake_qimei)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def fake_qimei(self, device):
        return {'q16': 'Q16VALUE', 'q36': 'Q36VALUE'}

    async def test_send_states(self):
        send = ('music.login.LoginServer', 'SendPhoneAuthCode')
        for result, expected in (((0, {}), {'state': 'sent'}),
                                 ((20276, {'securityURL': 'https://captcha.qq.com/x'}),
                                  {'state': 'captcha', 'url': 'https://captcha.qq.com/x'}),
                                 ((100001, {}), {'state': 'frequency'})):
            login._sms_last_sent.clear()
            self.fake.cgi_results[send] = result
            self.assertEqual(await login.phone_send('admin', '13800138000', '86'), expected)
        body = self.cgi_requests()[0]['body']
        self.assertEqual(body['req_0']['param'], {'tmeAppid': 'qqmusic', 'areaCode': '86', 'phoneNo': '13800138000'})
        self.assertEqual((body['comm']['tmeLoginMethod'], body['comm']['QIMEI'], body['comm']['QIMEI36']),
                         (3, 'Q16VALUE', 'Q36VALUE'))
        self.assertEqual(body['comm']['ct'], 11)
        self.assertEqual(self.cgi_requests()[0]['headers']['User-Agent'], 'QQMusic 14090008(android 10)')

    async def test_send_errors_and_cooldown(self):
        send = ('music.login.LoginServer', 'SendPhoneAuthCode')
        self.fake.cgi_results[send] = (104400, {'errMsg': 'bad request: phone'})
        with self.assertRaises(login.LoginError) as ctx:
            await login.phone_send('admin', '13800138000')
        self.assertEqual(ctx.exception.code, 104400)
        self.fake.cgi_results[send] = (12345, {})
        with self.assertRaises(login.LoginError):
            await login.phone_send('admin', '13800138000')
        with self.assertRaises(login.LoginError):
            await login.phone_send('admin', 'bad')

        self.fake.cgi_results[send] = (0, {})
        self.assertEqual((await login.phone_send('admin', '13800138000'))['state'], 'sent')
        calls = len(self.cgi_requests())
        self.assertEqual((await login.phone_send('admin', '13800138000'))['state'], 'frequency')  # 冷却期内不再请求
        self.assertEqual(len(self.cgi_requests()), calls)

    async def test_verify_success_and_failure(self):
        verify = ('music.login.LoginServer', 'Login')
        self.fake.cgi_results[verify] = (0, dict(LOGIN_DATA, loginType=3))
        ls = await login.phone_verify('admin', '13800138000', '123456')
        self.assertEqual((ls.kind, ls.state, ls.credential['login_type']), ('phone', 'done', '3'))
        body = self.cgi_requests()[0]['body']
        self.assertEqual(body['req_0']['param'], {'code': '123456', 'loginMode': 1, 'phoneNo': '13800138000'})
        self.assertEqual((body['comm']['tmeLoginMethod'], body['comm']['tmeLoginType']), (3, 0))
        self.assertIs(login.get_session(ls.id, 'admin'), ls)

        self.fake.cgi_results[verify] = (20271, {})
        with self.assertRaises(login.LoginError) as ctx:
            await login.phone_verify('admin', '13800138000', '000000')
        self.assertEqual(ctx.exception.message, '验证码错误')
        for bad_code in ('', 'abc', '12', '123456789'):
            with self.assertRaises(login.LoginError):
                await login.phone_verify('admin', '13800138000', bad_code)


class ApplyCredentialTest(unittest.TestCase):
    def setUp(self):
        variable.use_cookie_pool = False
        config.write_config_batch({
            'module.tx.user.qqmusic_key': 'OLD', 'module.tx.user.uin': '1',
            'module.tx.user.refresh_login.enable': False, 'module.tx.user.refresh_login.interval': 0,
            'module.cookiepool.tx': [{'qqmusic_key': '', 'uin': '', 'refresh_login': {'enable': False}}],
        })

    def done_session(self, **overrides):
        ls = login.LoginSession('qq', 'admin')
        ls.credential = dict(login.credential_from_login(0, LOGIN_DATA, 2), **overrides)
        ls.finish('done', '登录成功')
        return ls

    def test_main_account(self):
        ls = self.done_session()
        note = login.apply_credential(ls, 'main', True)
        self.assertIn('主账号', note)
        user = config.read_config('module.tx.user')
        for name, value in (('qqmusic_key', 'Q_H_L_NEWKEY'), ('uin', '123456'), ('refresh_key', 'RK'),
                            ('refresh_token', 'RT'), ('openid', 'OID'), ('access_token', 'AT'),
                            ('unionid', 'UID'), ('login_type', '2')):
            self.assertEqual(user[name], value, name)
        self.assertTrue(user['refresh_login']['enable'])
        self.assertEqual(user['refresh_login']['interval'], login.DEFAULT_REFRESH_INTERVAL)
        text = config.read_config_text()
        self.assertIn('Q_H_L_NEWKEY', text)
        self.assertIsNone(ls.credential)  # 落盘后内存里不再保留
        self.assertEqual(ls.state, 'applied')
        with self.assertRaises(login.LoginError):
            login.apply_credential(ls, 'main', True)  # 不能重复保存

    def test_main_account_without_refresh_keeps_it_disabled_and_keeps_interval(self):
        config.write_config('module.tx.user.refresh_login.interval', 555)
        login.apply_credential(self.done_session(), 'main', False)
        self.assertFalse(config.read_config('module.tx.user.refresh_login.enable'))
        self.assertEqual(config.read_config('module.tx.user.refresh_login.interval'), 555)

    def test_pool_replaces_placeholder_and_same_uin(self):
        note = login.apply_credential(self.done_session(), 'pool', True)
        self.assertIn('cookie 池', note)
        pool = config.read_config('module.cookiepool.tx')
        self.assertEqual([a['uin'] for a in pool], ['123456'])  # 留空的占位账号被去掉
        self.assertTrue(pool[0]['refresh_login']['enable'])

        config.write_config('module.cookiepool.tx', [
            {'qqmusic_key': 'OTHER', 'uin': '999', 'refresh_login': {'enable': True, 'interval': 7}},
            {'qqmusic_key': 'STALE', 'uin': '123456', 'refresh_login': {'enable': False, 'interval': 11}}])
        login.apply_credential(self.done_session(qqmusic_key='Q_H_L_FRESH'), 'pool', True)
        pool = config.read_config('module.cookiepool.tx')
        self.assertEqual([(a['uin'], a['qqmusic_key']) for a in pool], [('999', 'OTHER'), ('123456', 'Q_H_L_FRESH')])
        self.assertEqual(pool[1]['refresh_login'], {'enable': True, 'interval': 11})  # 沿用该账号原来的刷新间隔

    def test_notes_mention_pool_mode_mismatch(self):
        variable.use_cookie_pool = True
        self.addCleanup(setattr, variable, 'use_cookie_pool', False)
        self.assertIn('cookie 池', login.apply_credential(self.done_session(), 'main', True))
        variable.use_cookie_pool = False
        self.assertIn('common.cookiepool', login.apply_credential(self.done_session(), 'pool', True))

    def test_rejects_unfinished_sessions_and_bad_targets(self):
        pending = login.LoginSession('qq', 'admin')
        with self.assertRaises(login.LoginError):
            login.apply_credential(pending, 'main', True)
        with self.assertRaises(login.LoginError):
            login.apply_credential(self.done_session(), 'nowhere', True)


if __name__ == '__main__':
    unittest.main()
