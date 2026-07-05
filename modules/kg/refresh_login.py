# ----------------------------------------
# - mode: python -
# - author: helloplhm-qwq - (feat. Huibq and ikun0014)
# - name: refresh_login.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
import time
from common import variable
from common import scheduler
from common import config
from common import log
from .utils import signRequest, aes_sign
import ujson as json

logger = log.log('kg_refresh_login')


async def refresh():
    if (not config.read_config('module.kg.user.token')):
        return
    if (not config.read_config('module.kg.user.refresh_login.enable')):
        return
    
    user_id = config.read_config('module.kg.user.userid')
    token = config.read_config('module.kg.user.token')

    if (config.read_config('module.kg.client.appid') == '1005'):
        ts = int(time.time() * 1000)
        p3 = aes_sign(json.dumps({'clienttime': ts // 1000, 'token': token}))
        data = {
            'p3': p3,
            'clienttime_ms': ts,
            't1': 0,
            't2': 0,
            'userid': user_id
        }
        params = {
            'dfid': '-',
            'appid': config.read_config('module.kg.client.appid'),
            'mid': config.read_config('module.kg.user.mid'),
            'clientver': config.read_config('module.kg.client.clientver'),
            'clienttime': ts // 1000
        }
        headers = {
            'User-Agent': 'Android712-AndroidPhone-8983-18-0-NetMusic-wifi',
            'KG-THash': '3e5ec6b',
            'KG-Rec': '1',
            'KG-RC': '1',
        }
        login_url = config.read_config('module.kg.user.refresh_login.login_url')
        req = await signRequest(login_url, params, {'method': 'POST', 'json': data, 'headers': headers})
        body = req.json()
        if body['error_code'] != 0:
            logger.warning(f'酷狗音乐账号(UID_{user_id})刷新登录失败, code: ' +
                           str(body['error_code']) + f'\n响应体: {body}')
            return
        else:
            logger.info(f'酷狗音乐账号(UID_{user_id})刷新登录成功')
            config.write_config('module.kg.user.userid',
                                str(body['data']['userid']))
            config.write_config('module.kg.user.token',
                                body['data']['token'])
            logger.info(f'为酷狗音乐账号(UID_{user_id})数据更新完毕')
            return
    elif (config.read_config('module.kg.client.appid') == '3116'):
        ts = int(time.time() * 1000)
        p3 = aes_sign(json.dumps({'clienttime': ts // 1000, 'token': token}), key=b'c24f74ca2820225badc01946dba4fdf7', iv=b'adc01946dba4fdf7')
        data = {
            'p3': p3,
            'clienttime_ms': ts,
            't1': 0,
            't2': 0,
            'userid': user_id
        }
        params = {
            'dfid': '-',
            'appid': config.read_config('module.kg.client.appid'),
            'mid': config.read_config('module.kg.user.mid'),
            'clientver': config.read_config('module.kg.client.clientver'),
            'clienttime': ts // 1000
        }
        headers = {
            'User-Agent': 'Android712-AndroidPhone-8983-18-0-NetMusic-wifi',
            'KG-THash': '3e5ec6b',
            'KG-Rec': '1',
            'KG-RC': '1',
        }
        login_url = config.read_config('module.kg.user.refresh_login.login_url')
        req = await signRequest(login_url, params, {'method': 'POST', 'json': data, 'headers': headers})
        body = req.json()
        if body['error_code'] != 0:
            logger.warning(f'酷狗音乐账号(UID_{user_id})刷新登录失败, code: ' +
                           str(body['error_code']) + f'\n响应体: {body}')
            return
        else:
            logger.info(f'酷狗音乐账号(UID_{user_id})刷新登录成功')
            config.write_config('module.kg.user.userid',
                                str(body['data']['userid']))
            config.write_config('module.kg.user.token',
                                body['data']['token'])
            logger.info(f'为酷狗音乐账号(UID_{user_id})数据更新完毕')
            return

if (not variable.use_cookie_pool):
    kgconfig = config.read_config('module.kg')
    refresh_login_info = kgconfig.get('refresh_login')
    if (refresh_login_info):
        kgconfig['user']['refresh_login'] = refresh_login_info
        kgconfig.pop('refresh_login')
        config.write_config('module.kg', kgconfig)

if (config.read_config('module.kg.user.refresh_login.enable') and not variable.use_cookie_pool):
    scheduler.append('kg_refresh_login', refresh,
                     config.read_config('module.kg.user.refresh_login.interval'))

def _get_pool_user(index=None, user_info=None):
    user_list = config.read_config('module.cookiepool.kg') or []
    if index is None and user_info in user_list:
        index = user_list.index(user_info)
    if index is None or index >= len(user_list):
        logger.warning(f'酷狗账号池刷新登录失败: 账号索引不存在({index})')
        return None, None, user_list
    return index, user_list[index], user_list


async def refresh_login_for_pool(index=None, user_info=None):
    index, user_info, _ = _get_pool_user(index, user_info)
    if not user_info:
        return
    user_id = user_info["userid"]
    token = user_info["token"]
    if (config.read_config('module.kg.client.appid') == '1005'):
        ts = int(time.time() * 1000)
        p3 = aes_sign(json.dumps({'clienttime': ts // 1000, 'token': token}))
        data = {
            'p3': p3,
            'clienttime_ms': ts,
            't1': 0,
            't2': 0,
            'userid': user_id
        }
        params = {
            'dfid': '-',
            'appid': config.read_config('module.kg.client.appid'),
            'mid': user_info.get('mid') or config.read_config('module.kg.user.mid'),
            'clientver': config.read_config('module.kg.client.clientver'),
            'clienttime': ts // 1000
        }
        headers = {
            'User-Agent': 'Android712-AndroidPhone-8983-18-0-NetMusic-wifi',
            'KG-THash': '3e5ec6b',
            'KG-Rec': '1',
            'KG-RC': '1',
        }
        login_url = user_info["refresh_login"]["login_url"]
        req = await signRequest(login_url, params, {'method': 'POST', 'json': data, 'headers': headers})
        body = req.json()
        if body['error_code'] != 0:
            logger.warning(f'酷狗音乐账号(UID_{user_id})刷新登录失败, code: ' +
                           str(body['error_code']) + f'\n响应体: {body}')
            return
        else:
            logger.info(f'为酷狗音乐账号(UID_{user_id})刷新登录成功')
            _, _, user_list = _get_pool_user(index, user_info)
            user_list[index]['token'] = body['data']['token']
            user_list[index]['userid'] = str(body['data']['userid'])
            config.write_config('module.cookiepool.kg', user_list)
            logger.info(f'为酷狗音乐账号(UID_{user_id})数据更新完毕')
    elif (config.read_config('module.kg.client.appid') == '3116'):
        ts = int(time.time() * 1000)
        p3 = aes_sign(json.dumps({'clienttime': ts // 1000, 'token': token}), key=b'c24f74ca2820225badc01946dba4fdf7', iv=b'adc01946dba4fdf7')
        data = {
            'p3': p3,
            'clienttime_ms': ts,
            't1': 0,
            't2': 0,
            'userid': user_id
        }
        params = {
            'dfid': '-',
            'appid': config.read_config('module.kg.client.appid'),
            'mid': user_info.get('mid') or config.read_config('module.kg.user.mid'),
            'clientver': config.read_config('module.kg.client.clientver'),
            'clienttime': ts // 1000
        }
        headers = {
            'User-Agent': 'Android712-AndroidPhone-8983-18-0-NetMusic-wifi',
            'KG-THash': '3e5ec6b',
            'KG-Rec': '1',
            'KG-RC': '1',
        }
        login_url = user_info["refresh_login"]["login_url"]
        req = await signRequest(login_url, params, {'method': 'POST', 'json': data, 'headers': headers})
        body = req.json()
        if body['error_code'] != 0:
            logger.warning(f'酷狗音乐账号(UID_{user_id})刷新登录失败, code: ' +
                           str(body['error_code']) + f'\n响应体: {body}')
            return
        else:
            logger.info(f'为酷狗音乐账号(UID_{user_id})刷新登录成功')
            _, _, user_list = _get_pool_user(index, user_info)
            user_list[index]['token'] = body['data']['token']
            user_list[index]['userid'] = str(body['data']['userid'])
            config.write_config('module.cookiepool.kg', user_list)
            logger.info(f'为酷狗音乐账号(UID_{user_id})数据更新完毕')
            return

def reg_refresh_login_pool_task():
    user_info_pool = config.read_config('module.cookiepool.kg') or []
    for index, user_info in enumerate(user_info_pool):
        refresh_login = user_info.get('refresh_login') or {}
        if (refresh_login.get('enable')):
            scheduler.append(
                f'kgmusic_refresh_login_pooled_{index}', refresh_login_for_pool, refresh_login.get('interval', 86400), args = {'index': index})

if (variable.use_cookie_pool):
    reg_refresh_login_pool_task()
