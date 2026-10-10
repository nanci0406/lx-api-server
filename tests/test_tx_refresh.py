import _env  # noqa: F401

import unittest
import ujson as json

from common import Httpx, config, variable
from modules.tx import refresh_login as rl


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def ok_response(**data):
    base = {'musickey': 'W_X_NEW', 'musicid': 10086}
    base.update(data)
    return {'code': 0, 'req1': {'code': 0, 'data': base}}


class TxRefreshTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        variable.use_cookie_pool = False
        config.write_config_batch({
            'module.tx.user.qqmusic_key': 'W_X_OLD',
            'module.tx.user.uin': '10086',
            'module.tx.user.refresh_key': 'RK1',
            'module.tx.user.refresh_token': 'RT1',
            'module.tx.user.openid': 'OID1',
            'module.tx.user.access_token': '',
            'module.tx.user.unionid': 'UID1',
            'module.tx.user.refresh_login.enable': True,
        })
        self.requests = []
        self.responses = []
        self._orig = Httpx.AsyncRequest
        Httpx.AsyncRequest = self.fake_request
        self.addCleanup(setattr, Httpx, 'AsyncRequest', self._orig)

    async def fake_request(self, url, options=None):
        self.requests.append((url, json.loads(options['body'])))
        body = self.responses.pop(0)
        if callable(body):
            body = body()
        return FakeResponse(body)

    # ---- 请求构造 ----
    def test_wechat_request_carries_stored_credentials(self):
        url, payload = rl._build_request(config.read_config('module.tx.user'))
        param = payload['req1']['param']
        self.assertTrue(url.startswith('https://u.y.qq.com/'))
        self.assertEqual(param['musickey'], 'W_X_OLD')
        self.assertEqual(param['str_musicid'], '10086')
        self.assertEqual(param['refresh_key'], 'RK1')
        self.assertEqual(param['refresh_token'], 'RT1')
        self.assertEqual(param['openid'], 'OID1')
        self.assertEqual(param['unionid'], 'UID1')
        self.assertEqual(param['loginMode'], 2)

    def test_qq_request_only_sends_known_extras(self):
        user = {'qqmusic_key': 'Q_H_L_OLD', 'uin': '123', 'refresh_key': 'RK', 'refresh_token': '',
                'openid': '', 'access_token': 'AT'}
        url, payload = rl._build_request(user)
        param = payload['req1']['param']
        self.assertTrue(url.startswith('https://u6.y.qq.com/'))
        self.assertEqual(param['musicid'], 123)
        self.assertEqual(param['refresh_key'], 'RK')
        self.assertEqual(param['access_token'], 'AT')
        self.assertNotIn('refresh_token', param)
        self.assertNotIn('openid', param)
        self.assertNotIn('comm', payload)

    def test_invalid_accounts_are_rejected_without_a_request(self):
        self.assertIsNone(rl._build_request({'qqmusic_key': 'XYZ', 'uin': '1'}))
        self.assertIsNone(rl._build_request({'qqmusic_key': 'Q_H_L_X', 'uin': 'abc'}))
        self.assertIsNone(rl._build_request({'qqmusic_key': 'Q_H_L_X', 'uin': ''}))

    def test_mask_hides_secrets_everywhere(self):
        masked = rl._mask({'req1': {'data': {'musickey': 'W_X_SECRETVALUE', 'refresh_token': 'abcdefgh',
                                             'nick': 'visible', 'empty': ''}}, 'list': [{'openid': 'zzzzzzz'}]})
        data = masked['req1']['data']
        self.assertEqual(data['musickey'], 'W_X_***')
        self.assertEqual(data['refresh_token'], 'abcd***')
        self.assertEqual(data['nick'], 'visible')
        self.assertEqual(masked['list'][0]['openid'], 'zzzz***')

    # ---- 单账号刷新 ----
    async def test_success_persists_every_returned_field_and_next_refresh_uses_them(self):
        self.responses = [
            ok_response(refresh_key='RK2', refresh_token='RT2', access_token='AT2', openid=''),
            ok_response(musickey='W_X_NEWER', refresh_key='RK3'),
        ]
        self.assertIsNone(await rl.refresh())
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'W_X_NEW')
        self.assertEqual(config.read_config('module.tx.user.refresh_key'), 'RK2')
        self.assertEqual(config.read_config('module.tx.user.refresh_token'), 'RT2')
        self.assertEqual(config.read_config('module.tx.user.access_token'), 'AT2')
        self.assertEqual(config.read_config('module.tx.user.openid'), 'OID1')  # 响应为空时不覆盖已有值
        text = config.read_config_text()
        for expected in ('W_X_NEW', 'RK2', 'RT2', 'AT2'):
            self.assertIn(expected, text)

        await rl.refresh()
        second = self.requests[1][1]['req1']['param']
        self.assertEqual(second['musickey'], 'W_X_NEW')  # 第二轮用的是第一轮刷出来的新 key
        self.assertEqual(second['refresh_key'], 'RK2')
        self.assertEqual(second['refresh_token'], 'RT2')
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'W_X_NEWER')

    async def test_server_error_returns_false_and_keeps_config(self):
        self.responses = [{'code': 0, 'req1': {'code': 1000, 'data': {'musickey': 'W_X_SHOULD_NOT_BE_USED'}}}]
        self.assertIs(await rl.refresh(), False)
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'W_X_OLD')

    async def test_missing_new_key_returns_false(self):
        self.responses = [{'code': 0, 'req1': {'code': 0, 'data': {'musickey': ''}}},
                          {'code': 500}]
        self.assertIs(await rl.refresh(), False)
        self.assertIs(await rl.refresh(), False)  # 没有 req1 的异常响应
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'W_X_OLD')

    async def test_skips_when_disabled_or_unconfigured(self):
        config.write_config('module.tx.user.refresh_login.enable', False)
        self.assertIsNone(await rl.refresh())
        config.write_config('module.tx.user.refresh_login.enable', True)
        config.write_config('module.tx.user.qqmusic_key', '')
        self.assertIsNone(await rl.refresh())
        self.assertEqual(self.requests, [])

    async def test_result_is_discarded_if_key_was_changed_meanwhile(self):
        def admin_edits_key():
            config.write_config('module.tx.user.qqmusic_key', 'W_X_FROM_ADMIN')
            return ok_response(refresh_key='RK_FROM_OLD')
        self.responses = [admin_edits_key]
        self.assertIsNone(await rl.refresh())
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'W_X_FROM_ADMIN')
        self.assertEqual(config.read_config('module.tx.user.refresh_key'), 'RK1')

    # ---- cookie 池 ----
    async def test_pool_refresh_updates_only_that_account(self):
        config.write_config('module.cookiepool.tx', [
            {'qqmusic_key': 'Q_H_L_A', 'uin': '111', 'refresh_key': 'A_RK',
             'refresh_login': {'enable': True, 'interval': 100}},
            {'qqmusic_key': 'Q_H_L_B', 'uin': '222', 'refresh_login': {'enable': True, 'interval': 100}},
        ])
        self.responses = [ok_response(musickey='Q_H_L_A2', musicid=111, refresh_key='A_RK2')]
        self.assertIsNone(await rl.refresh_login_for_pool(index=0))
        pool = config.read_config('module.cookiepool.tx')
        self.assertEqual(pool[0]['qqmusic_key'], 'Q_H_L_A2')
        self.assertEqual(pool[0]['refresh_key'], 'A_RK2')
        self.assertEqual(pool[1]['qqmusic_key'], 'Q_H_L_B')
        sent = self.requests[0][1]['req1']['param']
        self.assertEqual(sent['musickey'], 'Q_H_L_A')
        self.assertEqual(sent['refresh_key'], 'A_RK')
        self.assertIn('Q_H_L_A2', config.read_config_text())

    async def test_pool_failure_and_bad_index(self):
        config.write_config('module.cookiepool.tx', [
            {'qqmusic_key': 'Q_H_L_A', 'uin': '111', 'refresh_login': {'enable': True}}])
        self.responses = [{'code': 0, 'req1': {'code': 2001}}]
        self.assertIs(await rl.refresh_login_for_pool(index=0), False)
        self.assertEqual(config.read_config('module.cookiepool.tx')[0]['qqmusic_key'], 'Q_H_L_A')
        self.assertIsNone(await rl.refresh_login_for_pool(index=5))
        self.assertEqual(len(self.requests), 1)


if __name__ == '__main__':
    unittest.main()
