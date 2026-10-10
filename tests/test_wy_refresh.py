import _env  # noqa: F401

import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from common import Httpx, config, variable
from common.exceptions import FailedException
from modules.wy import refresh_login as wy

FUTURE = 'Expires=Fri, 01-Jan-2100 00:00:00 GMT'
PAST = 'Expires=Thu, 01-Jan-1970 00:00:00 GMT'


class FakeResponse:
    def __init__(self, body, set_cookies=()):
        self.body = body
        self.set_cookies = list(set_cookies)

    def json(self):
        return self.body


class ParseSetCookieTest(unittest.TestCase):
    def test_keeps_valid_cookies(self):
        parsed = wy.parseSetCookie([
            f'MUSIC_U=0034abc==;Version=1;Max-Age=15552000;{FUTURE};Path=/;HTTPOnly',
            f'__csrf=csrf123; Max-Age=1296010; {FUTURE}; Path=/',
            'NMTID=00O; Path=/',
        ])
        self.assertEqual(parsed, {'MUSIC_U': '0034abc==', '__csrf': 'csrf123', 'NMTID': '00O'})

    def test_ignores_deleted_empty_and_expired_cookies(self):
        parsed = wy.parseSetCookie([
            f'MUSIC_SNS=; Max-Age=0; {PAST}; Path=/',  # 被服务端删除
            'MUSIC_R_T=zzz; Max-Age=0; Path=/',
            f'MUSIC_A_T=old; {PAST}; Path=/',  # 没有 Max-Age，只有已过期的 Expires
            'EMPTY=; Path=/',
            'garbage line without equals',
            '',
            f'KEEP=1; {FUTURE}',
        ])
        self.assertEqual(parsed, {'KEEP': '1'})

    def test_rfc_style_expires_and_none(self):
        self.assertEqual(wy.parseSetCookie(['A=1; Expires=Sun, 06 Nov 2095 08:49:37 GMT']), {'A': '1'})
        self.assertEqual(wy.parseSetCookie(['A=1; Expires=Sun, 06 Nov 1994 08:49:37 GMT']), {})
        self.assertEqual(wy.parseSetCookie(None), {})
        self.assertEqual(wy.parseSetCookie(['A=1; Expires=not a date']), {'A': '1'})

    def test_merge_keeps_unrelated_cookies_and_order(self):
        merged = wy.mergeCookies('os=pc; MUSIC_U=old; appver=2.10; __csrf=c1',
                                 {'MUSIC_U': 'new', 'NMTID': 'x'})
        self.assertEqual(merged, 'os=pc; MUSIC_U=new; appver=2.10; __csrf=c1; NMTID=x')
        self.assertEqual(wy.mergeCookies('a=b=c', {}), 'a=b=c')


class WyRefreshTest(unittest.IsolatedAsyncioTestCase):
    OLD = 'os=pc; appver=2.10.13; MUSIC_U=OLD_TOKEN; __csrf=csrf_old'

    def setUp(self):
        variable.use_cookie_pool = False
        config.write_config('module.wy.user.cookie', self.OLD)
        self.requests = []
        self.response = FakeResponse({'code': 200}, [f'MUSIC_U=NEW_TOKEN; Max-Age=1000; {FUTURE}; Path=/',
                                                      f'MUSIC_SNS=; Max-Age=0; {PAST}'])
        self._orig = Httpx.AsyncRequest
        Httpx.AsyncRequest = self.fake_request
        self.addCleanup(setattr, Httpx, 'AsyncRequest', self._orig)

    async def fake_request(self, url, options=None):
        self.requests.append((url, options))
        response = self.response
        if callable(response):
            response = response()
        return response

    async def test_new_cookie_is_written_back_and_other_pairs_are_kept(self):
        self.assertIsNone(await wy.refresh())
        self.assertEqual(config.read_config('module.wy.user.cookie'),
                         'os=pc; appver=2.10.13; MUSIC_U=NEW_TOKEN; __csrf=csrf_old')
        self.assertIn('MUSIC_U=NEW_TOKEN', config.read_config_text())
        url, options = self.requests[0]
        self.assertTrue(url.endswith('/eapi/login/token/refresh'))
        self.assertIn('MUSIC_U=OLD_TOKEN', options['headers']['Cookie'])  # 请求带的是刷新前的凭证

    async def test_next_refresh_uses_the_new_token(self):
        await wy.refresh()
        await wy.refresh()
        self.assertIn('MUSIC_U=NEW_TOKEN', self.requests[1][1]['headers']['Cookie'])

    async def test_no_new_cookie_leaves_config_untouched(self):
        self.response = FakeResponse({'code': 200}, [])
        self.assertIsNone(await wy.refresh())
        self.assertEqual(config.read_config('module.wy.user.cookie'), self.OLD)

    async def test_error_code_raises_even_when_code_is_an_int(self):
        self.response = FakeResponse({'code': 301})
        with self.assertRaises(FailedException) as ctx:
            await wy.refresh()
        self.assertIn('301', str(ctx.exception))
        self.assertEqual(config.read_config('module.wy.user.cookie'), self.OLD)

    async def test_skips_without_cookie(self):
        config.write_config('module.wy.user.cookie', '')
        self.assertIsNone(await wy.refresh())
        self.assertEqual(self.requests, [])

    async def test_result_is_discarded_if_cookie_was_changed_meanwhile(self):
        def admin_edits_cookie():
            config.write_config('module.wy.user.cookie', 'MUSIC_U=FROM_ADMIN')
            return FakeResponse({'code': 200}, [f'MUSIC_U=NEW_TOKEN; Max-Age=1000'])
        self.response = admin_edits_cookie
        self.assertIsNone(await wy.refresh())
        self.assertEqual(config.read_config('module.wy.user.cookie'), 'MUSIC_U=FROM_ADMIN')

    async def test_pool_account(self):
        config.write_config('module.cookiepool.wy', [
            {'cookie': 'MUSIC_U=POOL_OLD; os=pc', 'refresh_login': {'enable': True}},
            {'cookie': 'MUSIC_U=OTHER'},
        ])
        self.assertIsNone(await wy.refresh(index=0))
        pool = config.read_config('module.cookiepool.wy')
        self.assertEqual(pool[0]['cookie'], 'MUSIC_U=NEW_TOKEN; os=pc')
        self.assertEqual(pool[1]['cookie'], 'MUSIC_U=OTHER')
        self.assertIn('MUSIC_U=POOL_OLD', self.requests[0][1]['headers']['Cookie'])
        self.assertIsNone(await wy.refresh(index=7))  # 下标不存在：跳过
        self.assertEqual(len(self.requests), 1)


class SetCookieRoundTripTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_set_cookie_headers_survive_the_http_client(self):
        async def handler(request):
            response = web.json_response({'code': 200})
            response.headers.add('Set-Cookie', 'MUSIC_U=first; Path=/')
            response.headers.add('Set-Cookie', '__csrf=second; Path=/')
            return response

        app = web.Application()
        app.router.add_get('/', handler)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        session = aiohttp.ClientSession()
        self.addAsyncCleanup(session.close)
        original = variable.aioSession
        variable.aioSession = session
        self.addCleanup(setattr, variable, 'aioSession', original)
        resp = await Httpx.AsyncRequest(str(server.make_url('/')))
        self.assertEqual(resp.json(), {'code': 200})
        self.assertEqual(sorted(resp.set_cookies), ['MUSIC_U=first; Path=/', '__csrf=second; Path=/'])


if __name__ == '__main__':
    unittest.main()
