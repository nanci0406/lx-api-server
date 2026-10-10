# ----------------------------------------
# - mode: python -
# - author: helloplhm-qwq -
# - name: refresh_login.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

from common import Httpx, variable
from common import scheduler
from common import config
from common import log
from .utils import sign
import ujson as json

logger = log.log('qqmusic_refresh_login')

WX_LOGIN_URL = 'https://u.y.qq.com/cgi-bin/musics.fcg'
QQ_LOGIN_URL = 'https://u6.y.qq.com/cgi-bin/musics.fcg'

# 除 qqmusic_key / uin 之外需要随账号保存的登录凭证字段(配置键 -> 响应 data 里的字段名)。
# 刷新时会带上这些字段，刷新成功后也会把响应里新的值写回，
# 否则下一轮刷新用的还是旧凭证，刷新能力会逐步退化。
EXTRA_FIELDS = {
    'refresh_key': 'refresh_key',
    'refresh_token': 'refresh_token',
    'openid': 'openid',
    'access_token': 'access_token',
    'unionid': 'unionid',
}

# 日志里需要打码的字段
_SECRET_FIELDS = {
    'musickey', 'refresh_key', 'refresh_token', 'access_token', 'openid',
    'unionid', 'authst', 'sessionKey', 'token',
}


def _mask(obj):
    """打码响应体里的敏感字段，用于日志输出"""
    if isinstance(obj, dict):
        return {k: (_mask_value(v) if k in _SECRET_FIELDS else _mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask(i) for i in obj]
    return obj


def _mask_value(value):
    value = str(value)
    if not value:
        return value
    return value[:4] + '***'


def _account_label(user_info):
    return f'QQ音乐账号({user_info.get("uin")})'


def _build_request(user_info):
    """
    根据 qqmusic_key 的前缀(微信 W_X / QQ Q_H_L)构造刷新登录请求

    @return: (url, payload)；key 格式未知或 uin 无效时返回 None
    """
    key = str(user_info.get('qqmusic_key') or '')
    uin = str(user_info.get('uin') or '')
    extra = {k: str(user_info.get(k) or '') for k in EXTRA_FIELDS}
    if key.startswith('W_X'):
        return WX_LOGIN_URL, {
            'comm': {
                'fPersonality': '0',
                'tmeLoginType': '1',
                'tmeLoginMethod': '1',
                'qq': '',
                'authst': '',
                'ct': '11',
                'cv': '12080008',
                'v': '12080008',
                'tmeAppID': 'qqmusic',
            },
            'req1': {
                'module': 'music.login.LoginServer',
                'method': 'Login',
                'param': {
                    'code': '',
                    'openid': extra['openid'],
                    'refresh_token': extra['refresh_token'],
                    'str_musicid': uin,
                    'musickey': key,
                    'unionid': extra['unionid'],
                    'refresh_key': extra['refresh_key'],
                    'loginMode': 2,
                },
            },
        }
    if key.startswith('Q_H_L'):
        if not uin.isdigit():
            logger.error(f'{_account_label(user_info)}刷新登录失败: uin 必须是数字')
            return None
        param = {
            'expired_in': 7776000,
            'musicid': int(uin),
            'musickey': key,
        }
        # 只带上已有的值，避免用空串干扰服务端判断
        for name in ('openid', 'access_token', 'refresh_token', 'refresh_key'):
            if extra[name]:
                param[name] = extra[name]
        return QQ_LOGIN_URL, {
            'req1': {
                'module': 'QQConnectLogin.LoginServer',
                'method': 'QQLogin',
                'param': param,
            },
        }
    logger.error(f'{_account_label(user_info)}刷新登录失败: 未知的 qqmusic_key 格式(应以 W_X 或 Q_H_L 开头)')
    return None


async def refresh_account(user_info):
    """
    为一个账号发起刷新登录请求，不修改任何配置

    @param user_info: 含 qqmusic_key、uin 以及可选的 EXTRA_FIELDS 的字典
    @return: 成功时返回需要写回的字段字典(键为配置键)；失败返回 None
    """
    label = _account_label(user_info)
    request = _build_request(user_info)
    if request is None:
        return None
    url, payload = request
    body_str = json.dumps(payload)
    req = await Httpx.AsyncRequest(f'{url}?sign={sign(body_str)}', {
        'method': 'POST',
        'body': body_str,
    })
    body = req.json()
    result = body.get('req1') or {}
    if result.get('code') != 0:
        logger.warning(f'{label}刷新登录失败, code: {result.get("code")}\n响应体: {_mask(body)}')
        return None
    data = result.get('data') or {}
    if not data.get('musickey'):
        logger.warning(f'{label}刷新登录失败: 响应中没有新的 musickey\n响应体: {_mask(body)}')
        return None

    updates = {'qqmusic_key': data['musickey']}
    if data.get('musicid'):
        updates['uin'] = str(data['musicid'])
    for name, field in EXTRA_FIELDS.items():
        # 响应里为空的字段不覆盖已有值
        if data.get(field):
            updates[name] = str(data[field])
    return updates


async def refresh():
    """非 cookie 池模式：刷新 module.tx.user 的登录状态"""
    user_info = config.read_config('module.tx.user') or {}
    if (not user_info.get('qqmusic_key')):
        return
    if (not config.read_config('module.tx.user.refresh_login.enable')):
        return
    label = _account_label(user_info)
    used_key = user_info['qqmusic_key']
    updates = await refresh_account(user_info)
    if updates is None:
        return False
    # 请求期间管理员可能已经改了 key，这时不能用旧 key 刷出来的结果覆盖
    if config.read_config('module.tx.user.qqmusic_key') != used_key:
        logger.warning(f'{label}的 qqmusic_key 在刷新期间已被修改，本次刷新结果已丢弃')
        return
    logger.info(f'{label}刷新登录成功')
    config.write_config_batch({f'module.tx.user.{name}': value for name, value in updates.items()})
    logger.info(f'{label}数据更新完毕，已更新: {", ".join(updates)}')


def _get_pool_user(index=None, user_info=None):
    user_list = config.read_config('module.cookiepool.tx') or []
    if index is None and user_info in user_list:
        index = user_list.index(user_info)
    if index is None or index >= len(user_list):
        logger.warning(f'QQ音乐账号池刷新登录失败: 账号索引不存在({index})')
        return None, None, user_list
    return index, user_list[index], user_list


async def refresh_login_for_pool(index=None, user_info=None):
    """cookie 池模式：刷新 module.cookiepool.tx 中指定账号的登录状态"""
    index, user_info, _ = _get_pool_user(index, user_info)
    if not user_info:
        return
    used_key = user_info.get('qqmusic_key')
    if not used_key:
        return
    label = _account_label(user_info)
    updates = await refresh_account(user_info)
    if updates is None:
        return False
    # 请求期间配置可能被热重载或修改，重新读取账号池再写回
    _, current, user_list = _get_pool_user(index)
    if not current or current.get('qqmusic_key') != used_key:
        logger.warning(f'{label}的配置在刷新期间已被修改，本次刷新结果已丢弃')
        return
    logger.info(f'{label}刷新登录成功')
    current.update(updates)
    config.write_config('module.cookiepool.tx', user_list)
    logger.info(f'{label}数据更新完毕，已更新: {", ".join(updates)}')


def reg_refresh_login_pool_task():
    user_info_pool = config.read_config('module.cookiepool.tx') or []
    for index, user_info in enumerate(user_info_pool):
        refresh_login = user_info.get('refresh_login') or {}
        if (refresh_login.get('enable')):
            scheduler.append(
                f'qqmusic_refresh_login_pooled_{index}', refresh_login_for_pool, refresh_login.get('interval', 86400), args = {'index': index})


if (not variable.use_cookie_pool):
    # changed refresh login config path
    txconfig = config.read_config('module.tx')
    refresh_login_info = txconfig.get('refresh_login')
    if (refresh_login_info):
        txconfig['user']['refresh_login'] = refresh_login_info
        txconfig.pop('refresh_login')
        config.write_config('module.tx', txconfig)

if (config.read_config('module.tx.user.refresh_login.enable') and not variable.use_cookie_pool):
    scheduler.append('qqmusic_refresh_login', refresh,
                     config.read_config('module.tx.user.refresh_login.interval'))

if (variable.use_cookie_pool):
    reg_refresh_login_pool_task()
