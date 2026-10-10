# ----------------------------------------
# - mode: python - 
# - author: helloplhm-qwq - 
# - name: utils.py - 
# - project: lx-music-api-server - 
# - license: MIT - 
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

from common import Httpx
from common import utils
from common import config
from .QMWSign import sign
import ujson as json

createObject = utils.CreateObject

tools = createObject({
    "fileInfo": {
        "128k": {
            'e': '.mp3',
            'h': 'M500',
        },
        '320k': {
            "e": '.mp3',
            'h': 'M800',
        },
        'flac': {
            "e": '.flac',
            'h': 'F000',
        },
        'flac24bit': {
            "e": '.flac',
            'h': 'RS01',
        },
        "dolby": {
            "e": ".flac",
            "h": "Q000",
        },
        "master": {
            "e": ".flac",
            "h": "AI00",
        }
    },
    'qualityMapReverse': {
        'M500': '128k',
        'M800': '320k',
        'F000': 'flac',
        'RS01': 'flac24bit',
        'Q000': 'dolby',
        'AI00': 'master'
    },
    "cdnaddr": config.read_config("module.tx.cdnaddr") if config.read_config("module.tx.cdnaddr") else 'http://ws.stream.qqmusic.qq.com/',
})

async def signRequest(data, cache = False):
    data = json.dumps(data)
    s = sign(data)
    headers = {}
    return await Httpx.AsyncRequest('https://u.y.qq.com/cgi-bin/musics.fcg?format=json&sign=' + s, {
        'method': 'POST',
        'body': data,
        'headers': headers,
        "cache": (86400 * 30) if cache else "no-cache"
    })

def formatSinger(singerList):
    n = []
    for s in singerList:
        n.append(s['name'])
    return '、'.join(n)


def login_kind(user_info):
    """
    判断账号的登录类型，决定刷新登录/检查登录状态时用哪一种请求

    优先使用登录时保存的 login_type(1 微信、2 QQ)，它来自登录接口的返回，比 key 的前缀可靠
    (例如手机验证码登录得到的 key 不一定以 W_X / Q_H_L 开头)；
    没有 login_type(手动配置的账号)时才按 key 前缀判断。

    @return: 'wx' | 'qq' | None(无法判断)
    """
    login_type = str(user_info.get('login_type') or '').strip()
    if login_type == '1':
        return 'wx'
    if login_type == '2':
        return 'qq'
    key = str(user_info.get('qqmusic_key') or '')
    if key.startswith('W_X'):
        return 'wx'
    if key.startswith('Q_H_L'):
        return 'qq'
    return None
