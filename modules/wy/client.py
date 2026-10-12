# ----------------------------------------
# - mode: python -
# - name: client.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 网易云 eapi 请求的客户端参数(请求头里的 header Cookie、UA、设备信息)。
# 参考 NeteaseCloudMusicApi 的 util/request.js：没有 os 等字段时按 PC 客户端填写，并且总是带上 deviceId。

import random
import time
from urllib.parse import quote

import ujson as json

from common import Httpx
from .encrypt import eapiEncrypt

API_BASE = 'https://interface.music.163.com'
EAPI_UA = 'NeteaseMusic 9.0.90/5038 (iPhone; iOS 16.2; zh_CN)'

OS_PROFILES = {
    'pc': {'os': 'pc', 'appver': '3.1.17.204416', 'osver': 'Microsoft-Windows-10-Professional-build-19045-64bit',
           'channel': 'netease'},
    'linux': {'os': 'linux', 'appver': '1.2.1.0428', 'osver': 'Deepin 20.9', 'channel': 'netease'},
    'android': {'os': 'android', 'appver': '8.20.20.231215173437', 'osver': '14', 'channel': 'xiaomi'},
    'iphone': {'os': 'iPhone OS', 'appver': '9.0.90', 'osver': '16.2', 'channel': 'distribution'},
}


def new_device_id():
    return ''.join(random.choice('0123456789ABCDEF') for _ in range(52))


# Cookie 里没有 deviceId 时使用的设备 ID(进程内固定，和 NeteaseCloudMusicApi 一样)
DEVICE_ID = new_device_id()


def parse_cookie(cookie_str):
    result = {}
    for part in (cookie_str or '').split(';'):
        if '=' in part:
            name, value = part.strip().split('=', 1)
            if name:
                result[name] = value
    return result


def device_fields(os_name='pc', device_id=None):
    """新登录使用的设备信息，会和登录凭证一起保存，之后的刷新登录沿用同一台"设备" """
    return dict(OS_PROFILES[os_name], deviceId=device_id or new_device_id())


def build_header(cookie):
    """eapi 请求体里的 header，同时也作为请求的 Cookie"""
    os_name = cookie.get('os')
    # 既认 pc / iphone 这样的键名，也认 'iPhone OS' 这样实际写在 Cookie 里的值(NeteaseCloudMusicApi 只认键名，
    # 保存了 os=iPhone OS 的账号会被配上 PC 的 appver)
    profile = OS_PROFILES.get(os_name) or next(
        (p for p in OS_PROFILES.values() if p['os'] == os_name), OS_PROFILES['pc'])
    header = {
        'osver': cookie.get('osver') or profile['osver'],
        'deviceId': cookie.get('deviceId') or DEVICE_ID,
        'os': cookie.get('os') or profile['os'],
        'appver': cookie.get('appver') or profile['appver'],
        'versioncode': cookie.get('versioncode') or '140',
        'mobilename': cookie.get('mobilename') or '',
        'buildver': cookie.get('buildver') or str(int(time.time())),
        'resolution': cookie.get('resolution') or '1920x1080',
        '__csrf': cookie.get('__csrf') or '',
        'channel': cookie.get('channel') or profile['channel'],
        'requestId': f'{int(time.time() * 1000)}_{random.randint(0, 999):04d}',
    }
    if cookie.get('MUSIC_U'):
        header['MUSIC_U'] = cookie['MUSIC_U']
    if cookie.get('MUSIC_A'):
        header['MUSIC_A'] = cookie['MUSIC_A']
    return header


def _encode(value):
    # 与 JavaScript 的 encodeURIComponent 一致
    return quote(str(value), safe="-_.!~*'()")


async def eapi_request(path, data, cookie):
    """
    发送 eapi 请求

    @param path: 接口路径，如 /api/login/token/refresh
    @param data: 请求参数
    @param cookie: Cookie 字典(登录凭证和设备信息)
    @return: common.Httpx.ClientResponse
    """
    header = build_header(cookie)
    body = dict(data, header=header, e_r=False)
    return await Httpx.AsyncRequest(f'{API_BASE}/eapi/{path[5:]}', {
        'method': 'POST',
        'headers': {
            'User-Agent': EAPI_UA,
            'Cookie': '; '.join(f'{_encode(k)}={_encode(v)}' for k, v in header.items()),
        },
        'form': eapiEncrypt(path, json.dumps(body)),
    })


def response_code(resp):
    """eapi 响应的业务码；响应不是 JSON 时返回 None"""
    try:
        body = resp.json()
    except (ValueError, TypeError):
        return None, {}
    if not isinstance(body, dict):
        return None, {}
    try:
        return int(body.get('code')), body
    except (TypeError, ValueError):
        return None, body
