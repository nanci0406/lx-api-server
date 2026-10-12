# ----------------------------------------
# - mode: python -
# - name: login.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# QQ 音乐登录：QQ 扫码、微信扫码、手机验证码。登录成功后得到完整的登录凭证
# (musickey、refresh_key、refresh_token 等)，可以直接写入配置并交给自动刷新登录使用。
#
# 登录流程的接口地址、参数等协议细节参考了 YAQMC/qm-api-rs 的文档与行为说明，
# 代码为独立实现。QIMEI 与设备信息部分见 device.py / qimei.py。

import asyncio
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

import aiohttp
import ujson as json

from common import config, log, login_session, variable
from common.login_session import (  # noqa: F401  会话管理与网易云登录共用，这里保留原来的名字
    MAX_ACTIVE_SESSIONS, QR_TIMEOUT, RESULT_TTL, LoginError, LoginSession, _sessions, cancel_session, get_session,
)
from .device import load_device
from .qimei import ensure_qimei
from .utils import sign

logger = log.log('qqmusic_login')

# 接口地址集中放在这里，测试时可以替换成本地的模拟服务
ENDPOINTS = {
    'ptqrshow': 'https://ssl.ptlogin2.qq.com/ptqrshow',
    'ptqrlogin': 'https://ssl.ptlogin2.qq.com/ptqrlogin',
    'check_sig': 'https://ssl.ptlogin2.graph.qq.com/check_sig',
    'authorize': 'https://graph.qq.com/oauth2.0/authorize',
    'wx_qrconnect': 'https://open.weixin.qq.com/connect/qrconnect',
    'wx_qrcode': 'https://open.weixin.qq.com/connect/qrcode/{uuid}',
    'wx_poll': 'https://lp.open.weixin.qq.com/connect/l/qrconnect',
    'cgi': 'https://u.y.qq.com/cgi-bin/musics.fcg',
}

# 只跟随这些域名下的重定向，避免被带到不相干的站点
ALLOWED_REDIRECT_SUFFIXES = ('qq.com', 'weixin.qq.com')

WECHAT_APP_ID = 'wx48db31d50e334801'
QQ_CLIENT_ID = '100497308'
QQ_APP_ID = '716027609'
PTLOGIN_REFERER = 'https://xui.ptlogin2.qq.com/'
# ptlogin 的 check_sig 等接口会检查 User-Agent，非浏览器的 UA 拿不到 p_skey，所以所有请求默认都用浏览器 UA
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
QQ_REDIRECT_URI = 'https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https://y.qq.com/'
WX_REDIRECT_URI = 'https://y.qq.com/portal/wx_redirect.html?login_type=2&surl=https://y.qq.com/'
DEFAULT_REFRESH_INTERVAL = 86000

POLL_INTERVAL = 2  # 轮询二维码状态的间隔(秒)
SMS_COOLDOWN = 60  # 同一个手机号两次发送验证码的最短间隔

QR_EVENTS = {
    0: 'done', 405: 'done',
    66: 'scan', 408: 'scan',
    67: 'conf', 404: 'conf',
    65: 'timeout', 402: 'timeout',
    68: 'refuse', 403: 'refuse',
}

# 登录相关业务码的说明
LOGIN_MESSAGES = {
    1000: '登录鉴权参数无效或已过期',
    104400: '登录鉴权参数无效或已过期',
    104401: '登录鉴权参数无效或已过期',
    20261: '登录参数错误',
    20271: '验证码错误',
    20272: '账号绑定异常',
    20274: '账号绑定缺失',
    20277: '账号受限',
    20278: '账号受限',
    20279: '登录设备数量超限',
    20450: '账号已被封禁',
    104604: '操作过于频繁',
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def hash33(text, seed=0):
    value = seed
    for ch in text:
        value = ((value << 5) + value + ord(ch)) & 0x7fffffff
    return value


def extract_between(text, start, end):
    index = text.find(start)
    if index < 0:
        return ''
    rest = text[index + len(start):]
    end_index = rest.find(end)
    if end_index < 0:
        return ''
    return rest[:end_index]


class _Response:
    def __init__(self, status, headers, body, set_cookies, url):
        self.status = status
        self.headers = headers
        self.body = body
        self.set_cookies = set_cookies
        self.url = url

    @property
    def text(self):
        return self.body.decode('utf-8', errors='ignore')

    def cookies(self):
        """Set-Cookie 里设置的 Cookie；同名的取最后一个非空值(服务端可能先下发一个空值清掉旧 Cookie)"""
        result = {}
        for line in self.set_cookies:
            first = line.split(';', 1)[0].strip()
            if '=' in first:
                key, val = first.split('=', 1)
                key, val = key.strip(), val.strip()
                if key and val:
                    result[key] = val
        return result

    def cookie(self, name):
        return self.cookies().get(name, '')


def new_http_session():
    # 不使用共享的会话：登录流程的 Cookie 由我们自己显式传递，
    # 不能让 ptlogin 等站点的 Cookie 混进其他请求，也不能被其他请求带走
    return aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar(), trust_env=True)


async def _request(http, method, url, *, params=None, data=None, headers=None, cookies=None, timeout=20):
    headers = dict(headers or {})
    headers.setdefault('User-Agent', BROWSER_UA)
    if cookies:
        # 手动拼 Cookie 头：aiohttp 会对含特殊字符的 Cookie 值加引号，服务端不一定认
        headers['Cookie'] = '; '.join(f'{name}={value}' for name, value in cookies.items())
    try:
        async with http.request(
                method, url, params=params, data=data, headers=headers,
                allow_redirects=False, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            body = await resp.read()
            return _Response(resp.status, resp.headers, body, resp.headers.getall('Set-Cookie', []), str(resp.url))
    except asyncio.TimeoutError:
        raise LoginError('请求超时')
    except aiohttp.ClientError as e:
        raise LoginError(f'网络请求失败: {type(e).__name__}')


def _redirect_allowed(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    return parts.scheme in ('http', 'https') and any(
        host == suffix or host.endswith('.' + suffix) for suffix in ALLOWED_REDIRECT_SUFFIXES)


# ---------------------------------------------------------------------------
# CGI 调用与凭证解析
# ---------------------------------------------------------------------------

async def cgi_call(http, module, method, param, comm, user_agent=None):
    """调用 QQ 音乐 CGI 接口，返回 (业务码, data)"""
    payload = {'comm': comm, 'req_0': {'module': module, 'method': method, 'param': param}}
    body = json.dumps(payload)
    resp = await _request(http, 'POST', f"{ENDPOINTS['cgi']}?sign={sign(body)}", data=body, headers={
        'User-Agent': user_agent or BROWSER_UA,
        'Referer': 'https://y.qq.com/',
        'Origin': 'https://y.qq.com',
        'Content-Type': 'application/json',
    })
    if resp.status != 200:
        raise LoginError(f'接口返回了 HTTP {resp.status}')
    try:
        result = json.loads(resp.body)
    except ValueError:
        raise LoginError('接口返回的不是有效的 JSON')
    if result.get('code') not in (0, None):
        raise LoginError('接口返回了全局错误', result.get('code'))
    inner = result.get('req_0') or {}
    return inner.get('code'), inner.get('data') or {}


def credential_from_login(code, data, login_type):
    """校验登录接口的响应，转换成可以写入配置的凭证字典"""
    if code != 0:
        raise LoginError(LOGIN_MESSAGES.get(code) or f'登录失败(业务码 {code})', code)
    musickey = data.get('musickey') or data.get('musicKey') or ''
    musicid = data.get('musicid') or 0
    uin = str(musicid) if musicid else str(data.get('str_musicid') or data.get('uin') or '')
    if not musickey or not uin:
        raise LoginError('登录接口没有返回有效的 musickey 或 uin')
    return {
        'qqmusic_key': str(musickey),
        'uin': uin,
        'refresh_key': str(data.get('refresh_key') or ''),
        'refresh_token': str(data.get('refresh_token') or ''),
        'openid': str(data.get('openid') or ''),
        'access_token': str(data.get('access_token') or ''),
        'unionid': str(data.get('unionid') or ''),
        'login_type': str(login_type),
        'nick': str(data.get('nick') or ''),
    }


# ---------------------------------------------------------------------------
# QQ 扫码
# ---------------------------------------------------------------------------

async def qq_qr_start(http):
    """获取 QQ 登录二维码，返回 (qrsig, 图片字节, mimetype)"""
    resp = await _request(http, 'GET', ENDPOINTS['ptqrshow'], params={
        'appid': QQ_APP_ID, 'e': '2', 'l': 'M', 's': '3', 'd': '72', 'v': '4',
        't': f'{time.time():.3f}', 'daid': '383', 'pt_3rd_aid': QQ_CLIENT_ID,
    }, headers={'Referer': PTLOGIN_REFERER})
    if resp.status != 200:
        raise LoginError(f'获取二维码失败(HTTP {resp.status})')
    qrsig = resp.cookie('qrsig')
    if not qrsig:
        raise LoginError('获取二维码失败: 没有拿到 qrsig')
    return qrsig, resp.body, 'image/png'


async def qq_qr_check(http, qrsig):
    """
    查询 QQ 二维码状态

    @return: (事件, 登录信息)；事件为 scan/conf/done/timeout/refuse，只有 done 时才有登录信息：
             {uin, sigx, url: ptlogin 给出的 check_sig 地址, set_cookies: 这次响应下发的 Set-Cookie}
    """
    resp = await _request(http, 'GET', ENDPOINTS['ptqrlogin'], params={
        'u1': 'https://graph.qq.com/oauth2.0/login_jump',
        'ptqrtoken': str(hash33(qrsig)),
        'ptredirect': '0', 'h': '1', 't': '1', 'g': '1', 'from_ui': '1', 'ptlang': '2052',
        'action': f'0-0-{int(time.time() * 1000)}',
        'js_ver': '20102616', 'js_type': '1', 'pt_uistyle': '40',
        'aid': QQ_APP_ID, 'daid': '383', 'pt_3rd_aid': QQ_CLIENT_ID, 'has_onekey': '1',
    }, headers={'Referer': PTLOGIN_REFERER}, cookies={'qrsig': qrsig})
    match = re.search(r'ptuiCB\((.*)\)', resp.text, re.S)
    args = re.findall(r"'([^']*)'", match.group(1)) if match else []
    if not args:
        raise LoginError('获取二维码状态失败: 无法解析响应')
    try:
        code = int(args[0])
    except ValueError:
        raise LoginError('获取二维码状态失败: 状态码无效')
    event = QR_EVENTS.get(code)
    if event is None:
        raise LoginError(f'无法识别的二维码状态码: {code}')
    if event != 'done':
        return event, None
    if len(args) < 3:
        raise LoginError('获取登录凭据失败: 缺少必要参数')
    # 只认 ?uin= / &uin= 这样的完整参数名，不会误匹配 pt_uin= 之类的参数
    sigx = re.search(r'[?&]ptsigx=(.+?)&s_url', args[2])
    uin = re.search(r'[?&]uin=(.+?)&service', args[2])
    sigx, uin = (sigx.group(1) if sigx else ''), (uin.group(1) if uin else '')
    if not sigx or not uin:
        raise LoginError('获取登录凭据失败: 无法解析必要参数')
    return event, {'uin': uin, 'sigx': sigx, 'url': args[2], 'set_cookies': list(resp.set_cookies)}


def _cookies_for_host(set_cookies, host):
    """
    从 Set-Cookie 里挑出浏览器会带给 host 的 Cookie：只要带 Domain 且域名匹配的；
    没有 Domain 的只属于下发它的那个主机(ptlogin2.qq.com)，不会被带到别的主机
    """
    host = (host or '').lower()
    result = {}
    for line in set_cookies or []:
        parts = [part.strip() for part in line.split(';')]
        if '=' not in parts[0]:
            continue
        name, value = (item.strip() for item in parts[0].split('=', 1))
        domain = ''
        for attr in parts[1:]:
            key, _, val = attr.partition('=')
            if key.strip().lower() == 'domain':
                domain = val.strip().lstrip('.').lower()
        if name and value and domain and (host == domain or host.endswith('.' + domain)):
            result[name] = value
    return result


def _check_sig_url_allowed(url):
    """只跟随 ptlogin 给出的 check_sig 地址(qq.com 域名下)，不访问其他地址"""
    parts = urlsplit(url or '')
    if not parts.path.endswith('/check_sig'):
        return False
    return _redirect_allowed(url) or parts.netloc == urlsplit(ENDPOINTS['check_sig']).netloc


def _describe(resp):
    """一次请求的结果摘要(只有状态码和跳转的域名、路径，不含参数)，用于排查问题"""
    location = urlsplit(urljoin(resp.url, resp.headers.get('Location', '')))
    detail = f'HTTP {resp.status}'
    if location.hostname:
        detail += f'，跳转到 {location.hostname}{location.path}'
    return detail


async def qq_authorize_code(http, uin, sigx, check_url='', login_set_cookies=()):
    """
    扫码确认后，换取 QQ 互联的授权 code

    先按 qqmusic-api-python 的方式请求 check_sig(自己拼参数，不带 Cookie)拿 p_skey；
    拿不到时再按浏览器的方式重试一次：直接打开 ptlogin 给出的地址，带上登录成功时下发的、浏览器会带的 Cookie
    """
    resp = await _request(http, 'GET', ENDPOINTS['check_sig'], params={
        'uin': uin, 'pttype': '1', 'service': 'ptqrlogin', 'nodirect': '0', 'ptsigx': sigx,
        's_url': 'https://graph.qq.com/oauth2.0/login_jump', 'ptlang': '2052', 'ptredirect': '100',
        'aid': QQ_APP_ID, 'daid': '383', 'j_later': '0', 'low_login_hour': '0', 'regmaster': '0',
        'pt_login_type': '3', 'pt_aid': '0', 'pt_aaid': '16', 'pt_light': '0', 'pt_3rd_aid': QQ_CLIENT_ID,
    }, headers={'Referer': PTLOGIN_REFERER})
    sig_cookies = resp.cookies()
    attempts = [_describe(resp)]
    if not sig_cookies.get('p_skey') and _check_sig_url_allowed(check_url):
        logger.info('QQ 扫码登录：check_sig 没有返回 p_skey，改用浏览器的方式重试')
        cookies = _cookies_for_host(login_set_cookies, urlsplit(check_url).hostname)
        resp = await _request(http, 'GET', check_url, headers={'Referer': PTLOGIN_REFERER}, cookies=cookies)
        sig_cookies = resp.cookies()
        attempts.append(_describe(resp))
    p_skey = sig_cookies.get('p_skey', '')
    if not p_skey:
        # 记下 check_sig 的去向(只记域名和路径，不记参数)，方便判断是参数问题还是 QQ 要求额外验证
        detail = '；重试：'.join(attempts)
        logger.warning(f'QQ 扫码登录 check_sig 没有返回 p_skey: {detail}，返回的 Cookie: {sorted(sig_cookies) or "无"}')
        raise LoginError(f'获取登录凭据失败: 没有拿到 p_skey({detail})')

    form = {
        'response_type': 'code', 'client_id': QQ_CLIENT_ID, 'redirect_uri': QQ_REDIRECT_URI,
        'scope': 'get_user_info,get_app_friends', 'state': 'state', 'switch': '', 'from_ptlogin': '1',
        'src': '1', 'update_auth': '1', 'openapi': '1010_1030',
        'g_tk': str(hash33(p_skey, 5381)), 'auth_time': str(int(time.time() * 1000)), 'ui': str(uuid4()),
    }
    # 带上 check_sig 下发的全部 Cookie(p_skey、p_uin、pt4_token 等)，和浏览器的行为一致
    cookies = sig_cookies
    method, url, data = 'POST', ENDPOINTS['authorize'], form
    # 手动跟随重定向：一拿到带 code 的地址就停止，不去请求最终的页面
    for _ in range(5):
        resp = await _request(http, method, url, data=data, cookies=cookies)
        location = resp.headers.get('Location')
        if not location:
            break
        url = urljoin(url, location)
        code = (parse_qs(urlsplit(url).query).get('code') or [''])[0]
        if code:
            return code
        if not _redirect_allowed(url):
            raise LoginError('授权过程被重定向到了未知的地址')
        method, data = 'GET', None
    stop = urlsplit(url)
    logger.warning(f'QQ 扫码登录没有拿到授权 code: HTTP {resp.status}，停在 {stop.hostname}{stop.path}')
    raise LoginError(f'获取授权 code 失败(HTTP {resp.status})')


async def qq_exchange(http, code):
    # 和手机验证码登录一样按安卓客户端调用(qqmusic-api-python 默认也是安卓平台)
    comm, user_agent = await _android_comm({'tmeLoginType': 2})
    result_code, data = await cgi_call(http, 'QQConnectLogin.LoginServer', 'QQLogin', {'code': code}, comm, user_agent)
    return credential_from_login(result_code, data, 2)


# ---------------------------------------------------------------------------
# 微信扫码
# ---------------------------------------------------------------------------

async def wx_qr_start(http):
    """获取微信登录二维码，返回 (uuid, 图片字节, mimetype)"""
    resp = await _request(http, 'GET', ENDPOINTS['wx_qrconnect'], params={
        'appid': WECHAT_APP_ID, 'redirect_uri': WX_REDIRECT_URI, 'response_type': 'code',
        'scope': 'snsapi_login', 'state': 'STATE',
        'href': 'https://y.qq.com/mediastyle/music_v17/src/css/popup_wechat.css#wechat_redirect',
    })
    uuid = extract_between(resp.text, 'uuid=', '"')
    if not re.fullmatch(r'[A-Za-z0-9_\-]{6,64}', uuid):
        raise LoginError('获取二维码失败: 没有拿到 uuid')
    image = await _request(http, 'GET', ENDPOINTS['wx_qrcode'].format(uuid=uuid),
                           headers={'Referer': ENDPOINTS['wx_qrconnect']})
    if image.status != 200 or not image.body:
        raise LoginError('获取二维码失败')
    return uuid, image.body, 'image/jpeg'


async def wx_qr_check(http, uuid):
    """
    查询微信二维码状态(长轮询，没有变化时服务端会挂起一段时间再返回)

    @return: (事件, 授权 code)；只有 done 时才有 code
    """
    try:
        resp = await _request(http, 'GET', ENDPOINTS['wx_poll'], params={
            'uuid': uuid, '_': str(int(time.time() * 1000)),
        }, headers={'Referer': 'https://open.weixin.qq.com/'}, timeout=40)
    except LoginError as e:
        if e.message == '请求超时':
            return 'scan', None  # 长轮询到点没有结果，等同于"还没有扫码"
        raise
    errcode = extract_between(resp.text, 'window.wx_errcode=', ';')
    try:
        code = int(errcode)
    except ValueError:
        raise LoginError('获取二维码状态失败: 无法解析响应')
    event = QR_EVENTS.get(code)
    if event is None:
        raise LoginError(f'无法识别的二维码状态码: {code}')
    if event != 'done':
        return event, None
    wx_code = extract_between(resp.text, "window.wx_code='", "'")
    if not wx_code:
        raise LoginError('获取授权 code 失败')
    return event, wx_code


async def wx_exchange(http, code):
    comm, user_agent = await _android_comm({'tmeLoginType': 1})
    result_code, data = await cgi_call(
        http, 'music.login.LoginServer', 'Login', {'code': code, 'strAppid': WECHAT_APP_ID}, comm, user_agent)
    return credential_from_login(result_code, data, 1)


# ---------------------------------------------------------------------------
# 手机验证码登录
# ---------------------------------------------------------------------------

ANDROID_VERSION = 14090008


async def _android_comm(extra):
    """构造"安卓客户端"风格的 comm(含设备信息和 QIMEI)，手机验证码登录使用"""
    device = load_device()
    qimei = await ensure_qimei(device)
    guid = device.open_udid
    comm = {
        'ct': 11, 'cv': ANDROID_VERSION, 'v': ANDROID_VERSION, 'chid': '10003505',
        'qq': '0', 'authst': '', 'tmeAppID': 'qqmusic', 'tmeLoginType': 0,
        'QIMEI': qimei.get('q16', ''), 'QIMEI36': qimei.get('q36', ''),
        'OpenUDID': guid, 'udid': guid, 'uid': '', 'OpenUDID2': guid, 'sid': '',
        'aid': device.android_id, 'os_ver': device.version.release, 'phonetype': device.model,
        'devicelevel': str(device.version.sdk), 'newdevicelevel': str(device.version.sdk),
        'rom': device.fingerprint,
    }
    comm.update(extra)
    return comm, f'QQMusic {ANDROID_VERSION}(android {device.version.release})'


def validate_phone(phone, country_code='86'):
    phone = str(phone or '').strip()
    country_code = str(country_code or '86').strip().lstrip('+')
    if not re.fullmatch(r'\d{5,15}', phone):
        raise LoginError('手机号格式不正确')
    if not re.fullmatch(r'\d{1,4}', country_code):
        raise LoginError('国家/地区区号格式不正确')
    return phone, country_code


async def phone_send_code(http, phone, country_code='86'):
    """
    发送手机验证码

    @return: {'state': 'sent' | 'captcha' | 'frequency', 'url': 需要人机验证时的验证地址}
    """
    phone, country_code = validate_phone(phone, country_code)
    comm, user_agent = await _android_comm({'tmeLoginMethod': 3})
    code, data = await cgi_call(http, 'music.login.LoginServer', 'SendPhoneAuthCode',
                                {'tmeAppid': 'qqmusic', 'areaCode': country_code, 'phoneNo': phone},
                                comm, user_agent)
    if code == 0:
        return {'state': 'sent'}
    if code == 20276:
        return {'state': 'captcha', 'url': data.get('securityURL') or ''}
    if code == 100001:
        return {'state': 'frequency'}
    if code == 104400:
        raise LoginError('发送验证码失败：手机号无效或请求被拒绝', code)
    raise LoginError('发送验证码失败', code)


async def phone_login(http, phone, auth_code, country_code='86'):
    phone, _ = validate_phone(phone, country_code)
    auth_code = str(auth_code or '').strip()
    if not re.fullmatch(r'\d{4,8}', auth_code):
        raise LoginError('验证码格式不正确')
    comm, user_agent = await _android_comm({'tmeLoginMethod': 3, 'tmeLoginType': 0})
    code, data = await cgi_call(http, 'music.login.LoginServer', 'Login',
                                {'code': auth_code, 'loginMode': 1, 'phoneNo': phone}, comm, user_agent)
    return credential_from_login(code, data, data.get('loginType') or 0)


# ---------------------------------------------------------------------------
# 登录会话(给后台页面使用，全部保存在内存里)
# ---------------------------------------------------------------------------

_sms_last_sent = {}
_stop_session = login_session.stop_session


def _purge(now=None):
    login_session.purge(now)
    now = time.time() if now is None else now
    for key, ts in list(_sms_last_sent.items()):
        if now - ts > SMS_COOLDOWN:
            _sms_last_sent.pop(key, None)


async def _poll_qr(ls, http, identifier):
    """后台轮询二维码状态，扫码确认后自动换取并保存凭证"""
    try:
        deadline = ls.created_at + QR_TIMEOUT
        while time.time() < deadline:
            if ls.kind == 'qq':
                event, info = await qq_qr_check(http, identifier)
            else:
                event, info = await wx_qr_check(http, identifier)
            if event == 'done':
                ls.state = 'conf'
                if ls.kind == 'qq':
                    logger.info('QQ 扫码登录：手机已确认，正在换取登录凭证')
                    code = await qq_authorize_code(http, info['uin'], info['sigx'], info.get('url', ''),
                                                   info.get('set_cookies', ()))
                    ls.credential = await qq_exchange(http, code)
                else:
                    ls.credential = await wx_exchange(http, info)
                ls.finish('done', '登录成功')
                return
            if event in ('timeout', 'refuse'):
                ls.finish(event, '二维码已失效' if event == 'timeout' else '你已在手机上拒绝了登录')
                return
            ls.state = event
            await asyncio.sleep(POLL_INTERVAL)
        ls.finish('timeout', '二维码已失效')
    except asyncio.CancelledError:
        raise
    except LoginError as e:
        ls.finish('error', e.message)
    except Exception as e:
        logger.warning(f'扫码登录异常: {type(e).__name__}')
        ls.finish('error', '登录过程出错，请稍后重试')
    finally:
        await http.close()
        ls.http = None


async def start_qr(kind, owner):
    """发起扫码登录，返回 (登录会话, 二维码图片字节)"""
    if kind not in ('qq', 'wx'):
        raise LoginError('不支持的登录方式')
    _purge()
    login_session.ensure_capacity()
    http = new_http_session()
    try:
        if kind == 'qq':
            identifier, image, mimetype = await qq_qr_start(http)
        else:
            identifier, image, mimetype = await wx_qr_start(http)
    except BaseException:
        await http.close()
        raise
    ls = LoginSession(kind, owner)
    ls.image, ls.mimetype = image, mimetype
    ls.http = http
    login_session.register(ls)
    ls.task = asyncio.ensure_future(_poll_qr(ls, http, identifier))
    return ls


async def phone_send(owner, phone, country_code='86'):
    phone, country_code = validate_phone(phone, country_code)
    _purge()
    key = (country_code, phone)
    if time.time() - _sms_last_sent.get(key, 0) < SMS_COOLDOWN:
        return {'state': 'frequency'}
    http = new_http_session()
    try:
        result = await phone_send_code(http, phone, country_code)
    finally:
        await http.close()
    if result['state'] == 'sent':
        _sms_last_sent[key] = time.time()
    return result


async def phone_verify(owner, phone, auth_code, country_code='86'):
    _purge()
    http = new_http_session()
    try:
        credential = await phone_login(http, phone, auth_code, country_code)
    finally:
        await http.close()
    ls = LoginSession('phone', owner)
    ls.credential = credential
    ls.finish('done', '登录成功')
    return login_session.register(ls)


# ---------------------------------------------------------------------------
# 保存到配置
# ---------------------------------------------------------------------------

CONFIG_FIELDS = ('qqmusic_key', 'uin', 'refresh_key', 'refresh_token', 'openid', 'access_token', 'unionid',
                 'login_type')


def apply_credential(ls, target, enable_refresh=True):
    """
    把登录得到的凭证写入配置

    @param target: 'main' 写入 module.tx.user；'pool' 加入 module.cookiepool.tx
    @param enable_refresh: 是否同时开启这个账号的自动刷新登录
    @return: 给用户看的说明文字
    """
    if ls.state != 'done' or not ls.credential:
        raise LoginError('这次登录没有可保存的凭证')
    credential = {name: ls.credential.get(name, '') for name in CONFIG_FIELDS}
    if target == 'main':
        updates = {f'module.tx.user.{name}': value for name, value in credential.items()}
        if enable_refresh:
            updates['module.tx.user.refresh_login.enable'] = True
            if not config.read_config('module.tx.user.refresh_login.interval'):
                updates['module.tx.user.refresh_login.interval'] = DEFAULT_REFRESH_INTERVAL
        config.write_config_batch(updates)
        note = '已保存为主账号 (module.tx.user)'
        if variable.use_cookie_pool:
            note += '；当前启用了 cookie 池，主账号配置会被忽略，请改用“加入 cookie 池”'
    elif target == 'pool':
        pool = [dict(account) for account in (config.read_config('module.cookiepool.tx') or [])
                if account.get('qqmusic_key')]  # 丢掉默认配置里留空的占位账号
        entry = dict(credential)
        entry['refresh_login'] = {'enable': bool(enable_refresh), 'interval': DEFAULT_REFRESH_INTERVAL}
        for index, account in enumerate(pool):
            if str(account.get('uin')) == entry['uin']:
                entry['refresh_login'] = account.get('refresh_login') or entry['refresh_login']
                if enable_refresh:
                    entry['refresh_login'] = dict(entry['refresh_login'], enable=True)
                pool[index] = entry
                break
        else:
            pool.append(entry)
        config.write_config('module.cookiepool.tx', pool)
        note = f'已加入 cookie 池 (module.cookiepool.tx，共 {len(pool)} 个账号)'
        if not variable.use_cookie_pool:
            note += '；当前没有启用 cookie 池，需要把 common.cookiepool 设为 true 才会使用'
    else:
        raise LoginError('不支持的保存位置')
    ls.credential = None  # 凭证已落盘，内存里不再保留
    ls.state = 'applied'
    ls.message = note
    return note
