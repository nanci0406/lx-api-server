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


async def refresh():
    if (not config.read_config('module.tx.user.qqmusic_key')):
        return
    if (not config.read_config('module.tx.user.refresh_login.enable')):
        return
    if (config.read_config('module.tx.user.qqmusic_key').startswith('W_X')):
        options = {
            'method': 'POST',
            'body': json.dumps({
                "comm": {
                    "fPersonality": "0",
                    "tmeLoginType": "1",
                    "tmeLoginMethod": "1",
                    "qq": "",
                    "authst": "",
                    "ct": "11",
                    "cv": "12080008",
                    "v": "12080008",
                    "tmeAppID": "qqmusic"
                },
                "req1": {
                    "module": "music.login.LoginServer",
                    "method": "Login",
                    "param": {
                        "code": "",
                        "openid": "",
                        "refresh_token": "",
                        "str_musicid": str(config.read_config('module.tx.user.uin')),
                        "musickey": config.read_config('module.tx.user.qqmusic_key'),
                        "unionid": "",
                        "refresh_key": "",
                        "loginMode": 2
                    }
                }
            })
        }
        signature = sign(options['body'])
        req = await Httpx.AsyncRequest(f'https://u.y.qq.com/cgi-bin/musics.fcg?sign={signature}', options)
        body = req.json()
        if (body['req1']['code'] != 0):
            logger.warning('刷新登录失败, code: ' +
                           str(body['req1']['code']) + f'\n响应体: {body}')
            return
        else:
            logger.info('刷新登录成功')
            config.write_config('module.tx.user.uin',
                                str(body['req1']['data']['musicid']))
            logger.info('已通过相应数据更新uin')
            config.write_config('module.tx.user.qqmusic_key',
                                body['req1']['data']['musickey'])
            logger.info('已通过相应数据更新qqmusic_key')
    elif (config.read_config('module.tx.user.qqmusic_key').startswith('Q_H_L')):
        options = {
            'method': 'POST',
            'body': json.dumps({
                'req1': {
                    'module': 'QQConnectLogin.LoginServer',
                    'method': 'QQLogin',
                    'param': {
                        'expired_in': 7776000,
                        'musicid': int(config.read_config('module.tx.user.uin')),
                        'musickey': config.read_config('module.tx.user.qqmusic_key')
                    }
                }
            })
        }
        signature = sign(options['body'])
        req = await Httpx.AsyncRequest(f'https://u6.y.qq.com/cgi-bin/musics.fcg?sign={signature}', options)
        body = req.json()
        if (body['req1']['code'] != 0):
            logger.warning('刷新登录失败, code: ' +
                           str(body['req1']['code']) + f'\n响应体: {body}')
            return
        else:
            logger.info('刷新登录成功')
            config.write_config('module.tx.user.uin',
                                str(body['req1']['data']['musicid']))
            logger.info('已通过相应数据更新uin')
            config.write_config('module.tx.user.qqmusic_key',
                                body['req1']['data']['musickey'])
            logger.info('已通过相应数据更新qqmusic_key')
    else:
        logger.error('未知的qqmusic_key格式')

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

def _get_pool_user(index=None, user_info=None):
    user_list = config.read_config('module.cookiepool.tx') or []
    if index is None and user_info in user_list:
        index = user_list.index(user_info)
    if index is None or index >= len(user_list):
        logger.warning(f'QQ音乐账号池刷新登录失败: 账号索引不存在({index})')
        return None, None, user_list
    return index, user_list[index], user_list


async def refresh_login_for_pool(index=None, user_info=None):
    index, user_info, _ = _get_pool_user(index, user_info)
    if not user_info:
        return
    if (user_info['qqmusic_key'].startswith('W_X')):
        options = {
            'method': 'POST',
            'body': json.dumps({
                "comm": {
                    "fPersonality": "0",
                    "tmeLoginType": "1",
                    "tmeLoginMethod": "1",
                    "qq": "",
                    "authst": "",
                    "ct": "11",
                    "cv": "12080008",
                    "v": "12080008",
                    "tmeAppID": "qqmusic"
                },
                "req1": {
                    "module": "music.login.LoginServer",
                    "method": "Login",
                    "param": {
                        "code": "",
                        "openid": "",
                        "refresh_token": "",
                        "str_musicid": str(user_info['uin']),
                        "musickey": user_info['qqmusic_key'],
                        "unionid": "",
                        "refresh_key": "",
                        "loginMode": 2
                    }
                }
            })
        }
        signature = sign(options['body'])
        req = await Httpx.AsyncRequest(f'https://u.y.qq.com/cgi-bin/musics.fcg?sign={signature}', options)
        body = req.json()
        if (body['req1']['code'] != 0):
            logger.warning(f'为QQ音乐账号({user_info["uin"]})刷新登录失败, code: ' +
                           str(body['req1']['code']) + f'\n响应体: {body}')
            return
        else:
            logger.info(f'为QQ音乐账号(WeChat_{user_info["uin"]})刷新登录成功')
            _, _, user_list = _get_pool_user(index, user_info)
            user_list[index]['qqmusic_key'] = body['req1']['data']['musickey']
            user_list[index]['uin'] = str(body['req1']['data']['musicid'])
            config.write_config('module.cookiepool.tx', user_list)
            logger.info(f'为QQ音乐账号(WeChat_{user_info["uin"]})数据更新完毕')
            return
    elif (user_info['qqmusic_key'].startswith('Q_H_L')):
        options = {
            'method': 'POST',
            'body': json.dumps({
                'req1': {
                    'module': 'QQConnectLogin.LoginServer',
                    'method': 'QQLogin',
                    'param': {
                        'expired_in': 7776000,
                        'musicid': int(user_info['uin']),
                        'musickey': user_info['qqmusic_key']
                    }
                }
            })
        }
        signature = sign(options['body'])
        req = await Httpx.AsyncRequest(f'https://u6.y.qq.com/cgi-bin/musics.fcg?sign={signature}', options)
        body = req.json()
        if (body['req1']['code'] != 0):
            logger.warning(
                f'为QQ音乐账号({user_info["uin"]})刷新登录失败, code: ' + str(body['req1']['code']) + f'\n响应体: {body}')
            return
        else:
            logger.info(f'为QQ音乐账号(QQ_{user_info["uin"]})刷新登录成功')
            _, _, user_list = _get_pool_user(index, user_info)
            user_list[index]['qqmusic_key'] = body['req1']['data']['musickey']
            user_list[index]['uin'] = str(body['req1']['data']['musicid'])
            config.write_config('module.cookiepool.tx', user_list)
            logger.info(f'为QQ音乐账号(QQ_{user_info["uin"]})数据更新完毕')
            return
    else:
        logger.warning(f'为QQ音乐账号({user_info["uin"]})刷新登录失败: 未知或不支持的key类型')
        return

def reg_refresh_login_pool_task():
    user_info_pool = config.read_config('module.cookiepool.tx') or []
    for index, user_info in enumerate(user_info_pool):
        refresh_login = user_info.get('refresh_login') or {}
        if (refresh_login.get('enable')):
            scheduler.append(
                f'qqmusic_refresh_login_pooled_{index}', refresh_login_for_pool, refresh_login.get('interval', 86400), args = {'index': index})


if (variable.use_cookie_pool):
    reg_refresh_login_pool_task()
