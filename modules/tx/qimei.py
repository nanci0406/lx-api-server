# ----------------------------------------
# - mode: python -
# - name: qimei.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 向 QQ 音乐的 QIMEI 服务申请设备标识。请求的构造方式参考 MIT 许可的
# MeoProject/lx-music-api-server (utils/platform/tx/qimei.py)，改用项目已有的 pycryptodome。

import base64
import random
import time
from datetime import datetime, timedelta
import ujson as json
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from common import Httpx, utils, log
from .device import Device, save_device

logger = log.log('qqmusic_qimei')

QIMEI_URL = 'https://api.tencentmusic.com/tme/trpc/proxy'
APP_VERSION = '14.9.0.8'
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDEIxgwoutfwoJxcGQeedgP7FG9qaIuS0qzfR8gWkrkTZKM2iWHn2ajQpBRZjMSoSf6+KJGvar2ORhBfpDXyVtZCKpqLQ+FLkpncClKVIrBwv6PHyUvuCb0rIarmgDnzkfQAqVufEtR64iazGDKatvJ9y6B9NMbHddGSAUmRTCrHQIDAQAB
-----END PUBLIC KEY-----"""
SECRET = 'ZdJqM15EeO2zWc08'
APP_KEY = '0AND0HD6FE4HY80F'


def rsa_encrypt(content: bytes) -> bytes:
    return PKCS1_v1_5.new(RSA.import_key(PUBLIC_KEY)).encrypt(content)


def aes_encrypt(key: bytes, content: bytes) -> bytes:
    """AES-CBC(PKCS7)，IV 与密钥相同"""
    pad = 16 - len(content) % 16
    return AES.new(key, AES.MODE_CBC, key).encrypt(content + bytes([pad]) * pad)


def md5_of(*parts: str) -> str:
    return utils.createMD5(''.join(parts))


def random_beacon_id() -> str:
    beacon_id = ''
    month = datetime.now().strftime('%Y-%m-') + '01'
    rand1 = random.randint(100000, 999999)
    rand2 = random.randint(100000000, 999999999)
    for i in range(1, 41):
        if i in (1, 2, 13, 14, 17, 18, 21, 22, 25, 26, 29, 30, 33, 34, 37, 38):
            beacon_id += f'k{i}:{month}{rand1}.{rand2}'
        elif i == 3:
            beacon_id += 'k3:0000000000000000'
        elif i == 4:
            beacon_id += 'k4:' + ''.join(random.choices('123456789abcdef', k=16))
        else:
            beacon_id += f'k{i}:{random.randint(0, 9999)}'
        beacon_id += ';'
    return beacon_id


def build_payload(device: Device, version: str = APP_VERSION) -> dict:
    reserved = {
        'harmony': '0',
        'clone': '0',
        'containe': '',
        'oz': 'UhYmelwouA+V2nPWbOvLTgN2/m8jwGB+yUB5v9tysQg=',
        'oo': 'Xecjt+9S1+f8Pz2VLSxgpw==',
        'kelong': '0',
        'uptimes': (datetime.now() - timedelta(seconds=random.randint(0, 14400))).strftime('%Y-%m-%d %H:%M:%S'),
        'multiUser': '0',
        'bod': device.brand,
        'dv': device.device,
        'firstLevel': '',
        'manufact': device.brand,
        'name': device.model,
        'host': 'se.infra',
        'kernel': device.proc_version,
    }
    return {
        'androidId': device.android_id,
        'platformId': 1,
        'appKey': APP_KEY,
        'appVersion': version,
        'beaconIdSrc': random_beacon_id(),
        'brand': device.brand,
        'channelId': '10003505',
        'cid': '',
        'imei': device.imei,
        'imsi': '',
        'mac': '',
        'model': device.model,
        'networkType': 'unknown',
        'oaid': '',
        'osVersion': f'Android {device.version.release},level {device.version.sdk}',
        'qimei': '',
        'qimei36': '',
        'sdkVersion': '1.2.13.6',
        'targetSdkVersion': '33',
        'audit': '',
        'userId': '{}',
        'packageId': 'com.tencent.qqmusic',
        'deviceType': 'Phone',
        'sdkName': '',
        'reserved': json.dumps(reserved),
    }


async def fetch_qimei(device: Device) -> dict:
    """向服务端申请 QIMEI，返回 {'q16': ..., 'q36': ...}；失败时抛出异常"""
    crypt_key = ''.join(random.choices('adbcdef1234567890', k=16))
    nonce = ''.join(random.choices('adbcdef1234567890', k=16))
    ts = int(time.time())
    key = base64.b64encode(rsa_encrypt(crypt_key.encode())).decode()
    params = base64.b64encode(aes_encrypt(crypt_key.encode(), json.dumps(build_payload(device)).encode())).decode()
    extra = '{"appKey":"' + APP_KEY + '"}'
    sign = md5_of(key, params, str(ts * 1000), nonce, SECRET, extra)
    body = json.dumps({
        'app': 0,
        'os': 1,
        'qimeiParams': {'key': key, 'params': params, 'time': str(ts), 'nonce': nonce, 'sign': sign, 'extra': extra},
    })
    resp = await Httpx.AsyncRequest(QIMEI_URL, {
        'method': 'POST',
        'headers': {
            'Host': 'api.tencentmusic.com',
            'method': 'GetQimei',
            'service': 'trpc.tme_datasvr.qimeiproxy.QimeiProxy',
            'appid': 'qimei_qq_android',
            'sign': md5_of('qimei_qq_androidpzAuCmaFAaFaHrdakPjLIEqKrGnSOOvH', str(ts)),
            'User-Agent': 'QQMusic',
            'timestamp': str(ts),
            'Content-Type': 'application/json',
        },
        'body': body,
    })
    data = json.loads(json.loads(resp.content)['data'])['data']
    if not data.get('q36'):
        raise ValueError('QIMEI 响应中没有 q36')
    return {'q16': data.get('q16', ''), 'q36': data['q36']}


async def ensure_qimei(device: Device) -> dict:
    """返回有效的 QIMEI，必要时申请并保存到设备文件；申请失败时沿用旧值(没有旧值则为空)"""
    if device.qimei_fresh():
        return device.qimei
    try:
        device.qimei = await fetch_qimei(device)
        device.qimei_time = int(time.time())
        save_device(device)
    except Exception as e:
        logger.warning(f'获取 QIMEI 失败: {e}')
        if not device.qimei:
            return {'q16': '', 'q36': ''}
    return device.qimei
