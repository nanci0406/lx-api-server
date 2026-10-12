# ----------------------------------------
# - mode: python -
# - name: login.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 网易云音乐扫码登录(给后台"音乐账号"页使用)。
# 流程参考 NeteaseCloudMusicApi 的 login_qr_key / login_qr_create / login_qr_check：
#   1. /api/login/qrcode/unikey 拿到 unikey，二维码内容是 https://music.163.com/login?codekey=<unikey>
#   2. 轮询 /api/login/qrcode/client/login：800 已过期、801 等待扫码、802 已扫码待确认、803 登录成功
#   3. 登录成功时服务端通过 Set-Cookie 下发 MUSIC_U、__csrf 等登录凭证

import asyncio
import io
import time

from common import config, log, login_session, variable
from common.login_session import LoginError, LoginSession
from . import client
from .refresh_login import parseSetCookie

logger = log.log('wy_login')

QR_CONTENT = 'https://music.163.com/login?codekey={key}'
POLL_INTERVAL = 2
DEFAULT_REFRESH_INTERVAL = 86400

QR_EVENTS = {800: 'timeout', 801: 'scan', 802: 'conf', 803: 'done'}
RISK_CODES = (8821, -462)  # 网易云要求做行为验证(风控)


def qr_svg(content):
    """生成白底的二维码 SVG(不依赖 Pillow；深色模式下也能扫)"""
    # 用到时才导入：升级后还没安装新依赖时，只有扫码登录不可用，不影响服务启动
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        raise LoginError('缺少依赖 qrcode，请在服务器上执行 pip install -r requirements.txt 后重启服务')
    image = qrcode.make(content, image_factory=qrcode.image.svg.SvgPathFillImage, border=2,
                        error_correction=qrcode.constants.ERROR_CORRECT_M)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()


def _check_code(code, body, action):
    if code in RISK_CODES:
        raise LoginError('网易云要求进行安全验证(风控)，暂时无法扫码登录，请稍后再试', code)
    if code is None:
        raise LoginError(f'{action}失败：网易云返回了无法识别的内容')
    message = body.get('message') or body.get('msg') or ''
    raise LoginError(f'{action}失败(code: {code}{"，" + message if message else ""})', code)


async def qr_start(device):
    """获取登录二维码，返回 (unikey, svg 图片)"""
    resp = await client.eapi_request('/api/login/qrcode/unikey', {'type': 3}, device)
    code, body = client.response_code(resp)
    unikey = str(body.get('unikey') or '')
    if code != 200 or not unikey:
        _check_code(code, body, '获取二维码')
    return unikey, qr_svg(QR_CONTENT.format(key=unikey))


async def qr_check(unikey, device):
    """
    查询二维码状态

    @return: (事件, 响应内容, Set-Cookie 列表)；事件为 scan / conf / done / timeout
    """
    resp = await client.eapi_request('/api/login/qrcode/client/login', {'key': unikey, 'type': 3}, device)
    code, body = client.response_code(resp)
    event = QR_EVENTS.get(code)
    if event is None:
        _check_code(code, body, '查询二维码状态')
    return event, body, resp.set_cookies


async def fetch_account(cookie):
    """用新拿到的凭证查询账号信息，同时确认凭证可用；返回 (用户 ID, 昵称)"""
    resp = await client.eapi_request('/api/nuser/account/get', {}, cookie)
    code, body = client.response_code(resp)
    account = body.get('account') or {}
    profile = body.get('profile') or {}
    uid = account.get('id') or profile.get('userId')
    if code != 200 or not uid:
        raise LoginError('登录成功，但没能用新的凭证查到账号信息，请重试')
    return str(uid), str(profile.get('nickname') or '')


def build_credential(set_cookies, device):
    """把登录成功时下发的 Cookie 和设备信息合成要保存的 cookie 字符串"""
    cookies = parseSetCookie(set_cookies)
    if not cookies.get('MUSIC_U'):
        raise LoginError('登录成功，但网易云没有下发 MUSIC_U')
    merged = dict(cookies)
    for name, value in device.items():
        merged.setdefault(name, value)
    return merged


async def _poll(ls, unikey, device):
    try:
        deadline = ls.created_at + login_session.QR_TIMEOUT
        while time.time() < deadline:
            event, body, set_cookies = await qr_check(unikey, device)
            if event == 'done':
                cookie = build_credential(set_cookies, device)
                uid, nick = await fetch_account(cookie)
                ls.credential = {
                    'cookie': '; '.join(f'{name}={value}' for name, value in cookie.items()),
                    'uin': uid,
                    'nick': nick or ls.message,
                    'has_refresh': True,  # 网易云用 MUSIC_U 本身刷新，不需要额外的 refresh 凭证
                }
                ls.finish('done', '登录成功')
                return
            if event == 'timeout':
                ls.finish('timeout', '二维码已失效')
                return
            ls.state = event
            if event == 'conf' and body.get('nickname'):
                ls.message = str(body['nickname'])  # 扫码后先显示扫码人的昵称
            await asyncio.sleep(POLL_INTERVAL)
        ls.finish('timeout', '二维码已失效')
    except asyncio.CancelledError:
        raise
    except LoginError as e:
        ls.finish('error', e.message)
    except Exception as e:
        logger.warning(f'网易云扫码登录异常: {type(e).__name__}: {e}')
        ls.finish('error', '登录过程出错，请稍后重试')


async def start_qr(owner):
    """发起网易云扫码登录，返回登录会话"""
    login_session.ensure_capacity()
    device = client.device_fields('pc')
    unikey, image = await qr_start(device)
    ls = LoginSession('wy', owner)
    ls.image, ls.mimetype = image, 'image/svg+xml'
    login_session.register(ls)
    ls.task = asyncio.ensure_future(_poll(ls, unikey, device))
    return ls


def apply_credential(ls, target, enable_refresh=True):
    """
    把登录得到的 cookie 写入配置

    @param target: 'main' 写入 module.wy.user；'pool' 加入 module.cookiepool.wy(同一个账号会被更新)
    @return: 给用户看的说明文字
    """
    if ls.state != 'done' or not ls.credential:
        raise LoginError('这次登录没有可保存的凭证')
    cookie, uid = ls.credential['cookie'], ls.credential['uin']
    if target == 'main':
        updates = {'module.wy.user.cookie': cookie}
        if enable_refresh:
            updates['module.wy.user.refresh_login.enable'] = True
            if not config.read_config('module.wy.user.refresh_login.interval'):
                updates['module.wy.user.refresh_login.interval'] = DEFAULT_REFRESH_INTERVAL
        config.write_config_batch(updates)
        note = '已保存为主账号 (module.wy.user)'
        if variable.use_cookie_pool:
            note += '；当前启用了 cookie 池，主账号配置会被忽略，请改用“加入 cookie 池”'
    elif target == 'pool':
        pool = [dict(account) for account in (config.read_config('module.cookiepool.wy') or [])
                if account.get('cookie')]  # 丢掉默认配置里留空的占位账号
        entry = {'cookie': cookie, 'uid': uid,
                 'refresh_login': {'enable': bool(enable_refresh), 'interval': DEFAULT_REFRESH_INTERVAL}}
        for index, account in enumerate(pool):
            if str(account.get('uid') or '') == uid:
                entry['refresh_login'] = account.get('refresh_login') or entry['refresh_login']
                if enable_refresh:
                    entry['refresh_login'] = dict(entry['refresh_login'], enable=True)
                pool[index] = entry
                break
        else:
            pool.append(entry)
        config.write_config('module.cookiepool.wy', pool)
        note = f'已加入 cookie 池 (module.cookiepool.wy，共 {len(pool)} 个账号)'
        if not variable.use_cookie_pool:
            note += '；当前没有启用 cookie 池，需要把 common.cookiepool 设为 true 才会使用'
    else:
        raise LoginError('不支持的保存位置')
    ls.credential = None  # 凭证已落盘，内存里不再保留
    ls.state = 'applied'
    ls.message = note
    return note
