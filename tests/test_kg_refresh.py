import _env  # noqa: F401

import unittest

from common import config, variable
from modules.kg import refresh_login as kg


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class KgRefreshTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        variable.use_cookie_pool = False
        config.write_config_batch({
            'module.kg.client.appid': '1005',
            'module.kg.user.userid': '1',
            'module.kg.user.token': 'OLD_TOKEN',
            'module.kg.user.mid': '123',
            'module.kg.user.refresh_login.enable': True,
            'module.kg.user.refresh_login.login_url': 'http://login.example/v4/login_by_token',
        })
        self.sign_calls = []
        self.aes_calls = []
        self.response = {'error_code': 0, 'data': {'userid': 2, 'token': 'NEW_TOKEN'}}
        self._orig = (kg.signRequest, kg.aes_sign)

        async def fake_sign_request(url, params, options):
            self.sign_calls.append((url, params, options))
            return FakeResponse(self.response)

        def fake_aes_sign(text, **kwargs):
            self.aes_calls.append(kwargs)
            return 'P3'

        kg.signRequest, kg.aes_sign = fake_sign_request, fake_aes_sign
        self.addCleanup(lambda: setattr(kg, 'signRequest', self._orig[0]))
        self.addCleanup(lambda: setattr(kg, 'aes_sign', self._orig[1]))

    async def test_single_account_success_writes_new_credentials(self):
        self.assertIsNone(await kg.refresh())
        self.assertEqual(config.read_config('module.kg.user.token'), 'NEW_TOKEN')
        self.assertEqual(config.read_config('module.kg.user.userid'), '2')
        url, params, options = self.sign_calls[0]
        self.assertEqual(url, 'http://login.example/v4/login_by_token')
        self.assertEqual(params['mid'], '123')
        self.assertEqual(params['appid'], '1005')
        self.assertEqual(options['json']['userid'], '1')
        self.assertEqual(self.aes_calls, [{}])  # 1005 使用默认的 aes 参数

    async def test_lite_client_uses_its_own_aes_parameters(self):
        config.write_config('module.kg.client.appid', '3116')
        await kg.refresh()
        self.assertEqual(self.aes_calls, [kg._LITE_AES])

    async def test_failure_and_unsupported_appid_return_false(self):
        self.response = {'error_code': 20001, 'data': None}
        self.assertIs(await kg.refresh(), False)
        self.assertEqual(config.read_config('module.kg.user.token'), 'OLD_TOKEN')
        config.write_config('module.kg.client.appid', '9999')
        self.sign_calls.clear()
        self.assertIs(await kg.refresh(), False)
        self.assertEqual(self.sign_calls, [])

    async def test_pool_account(self):
        config.write_config('module.cookiepool.kg', [
            {'userid': '7', 'token': 'POOL_OLD', 'mid': '', 'refresh_login': {
                'enable': True, 'login_url': 'http://pool.example/login'}},
            {'userid': '8', 'token': 'OTHER', 'refresh_login': {'enable': True, 'login_url': 'http://x'}},
        ])
        self.assertIsNone(await kg.refresh_login_for_pool(index=0))
        pool = config.read_config('module.cookiepool.kg')
        self.assertEqual(pool[0]['token'], 'NEW_TOKEN')
        self.assertEqual(pool[0]['userid'], '2')
        self.assertEqual(pool[1]['token'], 'OTHER')
        url, params, _ = self.sign_calls[0]
        self.assertEqual(url, 'http://pool.example/login')
        self.assertEqual(params['mid'], '123')  # 账号自身没有 mid 时回退到全局 mid
        self.assertIs(await kg.refresh_login_for_pool(index=9), False)


if __name__ == '__main__':
    unittest.main()
