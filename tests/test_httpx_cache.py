import _env  # noqa: F401

import pickle
import unittest

import requests

from common import Httpx, config, utils, variable


class SerializationTest(unittest.TestCase):
    def test_roundtrip(self):
        data = Httpx._serialize_response(200, {'Content-Type': 'application/json'}, b'{"a": "\xe4\xb8\xad"}')
        status, headers, content = Httpx._deserialize_response(data)
        self.assertEqual(status, 200)
        self.assertEqual(headers, {'Content-Type': 'application/json'})
        self.assertEqual(content, b'{"a": "\xe4\xb8\xad"}')

    def test_binary_content_survives(self):
        raw = bytes(range(256))
        _, _, content = Httpx._deserialize_response(Httpx._serialize_response(200, {}, raw))
        self.assertEqual(content, raw)

    def test_legacy_pickle_entries_are_cache_misses_not_executed(self):
        executed = []

        class Evil:
            def __reduce__(self):
                return (executed.append, ('pwned',))

        legacy = utils.createBase64Encode(pickle.dumps(Evil()))
        self.assertIsNone(Httpx._deserialize_response(legacy))
        self.assertEqual(executed, [])
        for garbage in ('', 'not base64!!', utils.createBase64Encode(b'{"status": 1}')):
            self.assertIsNone(Httpx._deserialize_response(garbage))


class CachedRequestTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_request_serves_cached_response(self):
        variable.aioSession = object()  # 命中缓存时不会真正发请求
        self.addCleanup(setattr, variable, 'aioSession', None)
        cached = Httpx._serialize_response(200, {'X-Test': '1'}, b'{"ok": true}')
        original = config.getCache
        config.getCache = lambda module, key: {'data': cached}
        self.addCleanup(setattr, config, 'getCache', original)
        resp = await Httpx.AsyncRequest('https://example.invalid/x', {'cache': 60})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers, {'X-Test': '1'})
        self.assertEqual(resp.json(), {'ok': True})

    def test_sync_request_serves_cached_response(self):
        cached = Httpx._serialize_response(201, {'X-Test': '1'}, b'{"ok": 1}')
        original = config.getCache
        config.getCache = lambda module, key: {'data': cached}
        self.addCleanup(setattr, config, 'getCache', original)
        resp = Httpx.request('https://example.invalid/y', {'cache': 60})
        self.assertIsInstance(resp, requests.Response)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.headers['x-test'], '1')
        self.assertEqual(resp.json(), {'ok': 1})


if __name__ == '__main__':
    unittest.main()
