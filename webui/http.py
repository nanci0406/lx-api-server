# ----------------------------------------
# - mode: python -
# - name: http.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# Web 界面后端的公共工具：统一的 JSON 响应、鉴权、CSRF 防护、安全响应头。

import json
from urllib.parse import urlsplit

from aiohttp import web

from common import config
from common.services import admin_auth

_ERRORS = {
    400: web.HTTPBadRequest,
    401: web.HTTPUnauthorized,
    403: web.HTTPForbidden,
    404: web.HTTPNotFound,
    409: web.HTTPConflict,
    413: web.HTTPRequestEntityTooLarge,
    429: web.HTTPTooManyRequests,
}


def _dumps(payload):
    return json.dumps(payload, ensure_ascii=False)


def ok(data=None, status=200):
    return web.json_response({'code': 0, 'msg': 'success', 'data': data}, status=status, dumps=_dumps)


def fail(status, message, data=None):
    """中断请求并返回 JSON 错误"""
    error_class = _ERRORS.get(status, web.HTTPBadRequest)
    if error_class is web.HTTPRequestEntityTooLarge:
        raise error_class(max_size=0, actual_size=0, text=_dumps({'code': status, 'msg': message, 'data': data}),
                          content_type='application/json')
    raise error_class(text=_dumps({'code': status, 'msg': message, 'data': data}), content_type='application/json')


def client_ip(request):
    # remote_addr 由 main.py 的中间件设置(已处理反向代理的真实 IP 头)
    return getattr(request, 'remote_addr', None) or request.remote or ''


def check_same_origin(request):
    """
    写操作的来源校验：浏览器发起的跨站请求会带 Origin(或 Referer)，其主机必须与本站一致；
    两者都没有时(如 curl)不拦截。反向代理改写了 Host 导致误拦时，可关闭 security.admin_origin_check。
    """
    if not config.read_config('security.admin_origin_check'):
        return
    source = request.headers.get('Origin') or request.headers.get('Referer')
    if not source:
        return
    allowed = {request.host.lower()}
    forwarded_host = request.headers.get('X-Forwarded-Host')
    if forwarded_host:
        allowed.add(forwarded_host.split(',')[0].strip().lower())
    if source == 'null' or urlsplit(source).netloc.lower() not in allowed:
        fail(403, '请求来源校验失败。如果你通过反向代理访问，请让代理传递原始 Host，'
                  '或在配置中关闭 security.admin_origin_check')


async def read_json(request, max_size=256 * 1024):
    """读取 JSON 请求体。要求 Content-Type 为 application/json：跨站表单无法发出这种请求，是 CSRF 的又一道防线"""
    if request.content_type != 'application/json':
        fail(400, '请求格式错误，需要 JSON')
    if request.content_length is not None and request.content_length > max_size:
        fail(413, '请求内容太大')
    try:
        data = await request.json()
    except ValueError:
        fail(400, '请求内容不是有效的 JSON')
    if not isinstance(data, dict):
        fail(400, '请求内容格式错误')
    return data


def require_admin(request, write=False):
    session = admin_auth.get_session(request)
    if not session:
        fail(401, '登录已过期，请重新登录')
    if write:
        check_same_origin(request)
    return session


def current_token(request):
    return request.cookies.get(admin_auth.COOKIE_NAME)


async def add_security_headers(request, response):
    """给 Web 界面相关的响应加上安全头和缓存策略"""
    path = request.path
    if not (path == '/' or path.startswith(('/admin', '/api/admin', '/api/public', '/static/'))):
        return
    headers = response.headers
    headers.setdefault('X-Content-Type-Options', 'nosniff')
    headers.setdefault('Referrer-Policy', 'same-origin')
    if path.startswith('/api/'):
        headers.setdefault('Cache-Control', 'no-store')
    elif path.startswith('/static/'):
        # 静态文件每次都向服务器确认是否有更新(304)，升级后不会用到旧的脚本
        headers['Cache-Control'] = 'no-cache'
    if response.content_type == 'text/html':
        headers.setdefault('Cache-Control', 'no-store')
        headers.setdefault('X-Frame-Options', 'DENY')
        headers.setdefault('Content-Security-Policy',
                           "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                           "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
