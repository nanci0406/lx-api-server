# ----------------------------------------
# - mode: python -
# - name: credential.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

# QQ音乐登录凭证有效性检查，供后台模块健康页使用

import hashlib
import time
import ujson as json
from common import Httpx, config, variable, log
from .utils import sign

logger = log.log('qqmusic_credential')

# GetLoginUserInfo 返回这些业务码表示登录凭证已过期/无效
EXPIRED_CODES = (1000, 104400, 104401)
# 检查结果缓存时长(秒)，避免健康页自动刷新时频繁请求官方接口
CACHE_SECONDS = 1800

_cache = {}


def _accounts():
    """返回当前模式下配置了 qqmusic_key 的账号"""
    if variable.use_cookie_pool:
        users = config.read_config('module.cookiepool.tx') or []
    else:
        users = [config.read_config('module.tx.user') or {}]
    return [u for u in users if u.get('qqmusic_key')]


async def check_account(user_info):
    """
    检查单个账号的登录凭证

    @return: 'valid' 有效；'invalid' 已过期或无效；'unknown' 无法判断(业务码未知)
    """
    key = str(user_info.get('qqmusic_key') or '')
    uin = str(user_info.get('uin') or '')
    payload = {
        'comm': {
            'ct': '11',
            'cv': '12080008',
            'v': '12080008',
            'tmeAppID': 'qqmusic',
            'format': 'json',
            'qq': uin,
            'authst': key,
            'tmeLoginType': '1' if key.startswith('W_X') else '2',
        },
        'req': {
            'module': 'music.UserInfo.userInfoServer',
            'method': 'GetLoginUserInfo',
            'param': {},
        },
    }
    body_str = json.dumps(payload)
    req = await Httpx.AsyncRequest(f'https://u.y.qq.com/cgi-bin/musics.fcg?sign={sign(body_str)}', {
        'method': 'POST',
        'body': body_str,
    })
    code = ((req.json() or {}).get('req') or {}).get('code')
    if code == 0:
        return 'valid'
    if code in EXPIRED_CODES:
        return 'invalid'
    logger.warning(f'检查QQ音乐账号({uin})登录状态得到未知业务码: {code}')
    return 'unknown'


async def check_all(force=False):
    """
    检查所有已配置的账号

    @param force: 为 True 时忽略缓存重新检查
    @return: {'total': 总数, 'valid': 有效数, 'invalid': 失效数, 'unknown': 未知数}
    """
    now = time.time()
    for k in [k for k, (ts, _) in _cache.items() if now - ts >= CACHE_SECONDS]:
        _cache.pop(k, None)
    summary = {'total': 0, 'valid': 0, 'invalid': 0, 'unknown': 0}
    for user_info in _accounts():
        # 缓存键包含 key：刷新登录换了新 key 之后会自动重新检查
        cache_key = hashlib.sha256(
            f'{user_info.get("uin")}|{user_info.get("qqmusic_key")}'.encode('utf-8')).hexdigest()
        cached = _cache.get(cache_key)
        if cached and not force:
            state = cached[1]
        else:
            try:
                state = await check_account(user_info)
            except Exception as e:
                logger.warning(f'检查QQ音乐账号({user_info.get("uin")})登录状态失败: {e}')
                state = 'unknown'
            # 网络异常等无法判断的结果不缓存，下次继续尝试
            if state != 'unknown':
                _cache[cache_key] = (time.time(), state)
        summary['total'] += 1
        summary[state] += 1
    return summary
