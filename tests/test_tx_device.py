import _env  # noqa: F401

import base64
import json as stdjson
import os
import tempfile
import time
import unittest
from unittest import mock

from Crypto.Cipher import AES

from common import Httpx
from modules.tx import device, qimei


class DeviceTest(unittest.TestCase):
    def test_imei_has_valid_shape(self):
        for _ in range(20):
            imei = device.random_imei()
            self.assertEqual((len(imei), imei.isdigit()), (15, True))

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'nested', 'device.json')
            first = device.load_device(path)  # 文件不存在：生成并保存
            self.assertTrue(os.path.exists(path))
            first.qimei = {'q16': 'a', 'q36': 'b'}
            first.qimei_time = 123
            device.save_device(first, path)
            second = device.load_device(path)
            self.assertEqual((second.android_id, second.open_udid, second.qimei, second.qimei_time),
                             (first.android_id, first.open_udid, {'q16': 'a', 'q36': 'b'}, 123))
            self.assertEqual(second.version.sdk, 29)

    def test_corrupt_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'device.json')
            with open(path, 'w') as f:
                f.write('{not json')
            self.assertTrue(device.load_device(path).android_id)
            stdjson.load(open(path))  # 已被新文件覆盖

    def test_qimei_freshness(self):
        d = device.Device()
        self.assertFalse(d.qimei_fresh())
        d.qimei, d.qimei_time = {'q16': '', 'q36': 'x'}, int(time.time())
        self.assertTrue(d.qimei_fresh())
        d.qimei_time -= device.QIMEI_CACHE_SECONDS + 1
        self.assertFalse(d.qimei_fresh())


class QimeiTest(unittest.IsolatedAsyncioTestCase):
    def test_aes_uses_the_key_as_iv_with_pkcs7_padding(self):
        key = b'0123456789abcdef'
        encrypted = qimei.aes_encrypt(key, b'hello world')
        self.assertEqual(len(encrypted), 16)
        plain = AES.new(key, AES.MODE_CBC, key).decrypt(encrypted)
        self.assertEqual(plain, b'hello world' + bytes([5]) * 5)
        self.assertEqual(len(qimei.aes_encrypt(key, b'x' * 16)), 32)  # 整块时也要补一整块

    def test_rsa_output_size(self):
        self.assertEqual(len(qimei.rsa_encrypt(b'0123456789abcdef')), 128)

    def test_payload_describes_the_device(self):
        d = device.Device()
        payload = qimei.build_payload(d)
        self.assertEqual((payload['androidId'], payload['imei'], payload['model']), (d.android_id, d.imei, d.model))
        self.assertEqual(payload['osVersion'], f'Android {d.version.release},level {d.version.sdk}')
        self.assertEqual(len(payload['beaconIdSrc'].split(';')), 41)  # 40 项，末尾有一个分号
        self.assertEqual(stdjson.loads(payload['reserved'])['dv'], d.device)

    async def test_fetch_builds_the_signed_request_and_parses_the_answer(self):
        calls = []

        async def fake_request(url, options=None):
            calls.append((url, options))

            class Resp:
                content = stdjson.dumps({'data': stdjson.dumps({'data': {'q16': 'Q16', 'q36': 'Q36'}})}).encode()
            return Resp()

        with mock.patch.object(Httpx, 'AsyncRequest', new=fake_request):
            result = await qimei.fetch_qimei(device.Device())
        self.assertEqual(result, {'q16': 'Q16', 'q36': 'Q36'})
        url, options = calls[0]
        self.assertEqual(url, qimei.QIMEI_URL)
        headers = options['headers']
        self.assertEqual((headers['appid'], headers['method']), ('qimei_qq_android', 'GetQimei'))
        self.assertEqual(headers['sign'], qimei.md5_of('qimei_qq_androidpzAuCmaFAaFaHrdakPjLIEqKrGnSOOvH',
                                                       headers['timestamp']))
        params = stdjson.loads(options['body'])['qimeiParams']
        expected_sign = qimei.md5_of(params['key'], params['params'], str(int(params['time']) * 1000),
                                     params['nonce'], qimei.SECRET, params['extra'])
        self.assertEqual(params['sign'], expected_sign)
        self.assertEqual(len(base64.b64decode(params['key'])), 128)

    async def test_ensure_caches_and_falls_back(self):
        d = device.Device()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'device.json')
            fetched = []

            async def fake_fetch(dev):
                fetched.append(1)
                return {'q16': 'A', 'q36': 'B'}

            with mock.patch.object(device, 'DEVICE_PATH', path), mock.patch.object(qimei, 'fetch_qimei', new=fake_fetch):
                self.assertEqual(await qimei.ensure_qimei(d), {'q16': 'A', 'q36': 'B'})
                self.assertEqual(await qimei.ensure_qimei(d), {'q16': 'A', 'q36': 'B'})
                self.assertEqual(len(fetched), 1)  # 第二次直接用缓存
                self.assertEqual(device.load_device(path).qimei, {'q16': 'A', 'q36': 'B'})  # 已保存到文件

                # 缓存过期而重新获取失败：沿用旧值
                d.qimei_time = 0

                async def failing(dev):
                    raise OSError('down')
                with mock.patch.object(qimei, 'fetch_qimei', new=failing):
                    self.assertEqual(await qimei.ensure_qimei(d), {'q16': 'A', 'q36': 'B'})
                    # 从没成功过：返回空值而不是抛异常
                    self.assertEqual(await qimei.ensure_qimei(device.Device()), {'q16': '', 'q36': ''})


if __name__ == '__main__':
    unittest.main()
