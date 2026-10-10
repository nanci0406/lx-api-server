# ----------------------------------------
# - mode: python -
# - name: routes.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# Web 界面入口：公开首页(/)、管理后台(/admin/...，单页应用)、静态文件和 JSON 接口。

import os

from aiohttp import web

from . import api_admin, api_public
from .http import add_security_headers

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

_SHELL = '''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="light dark">
  <meta name="theme-color" content="#6d5dfc">
  <title>{title}</title>
  <link rel="icon" href="/static/img/logo.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/css/app.css">
  <script src="/static/js/theme.js"></script>
</head>
<body class="{body_class}">
  <div id="app"><div class="boot"><div class="boot-logo"></div></div></div>
  <noscript><p class="noscript">这个页面需要启用 JavaScript。</p></noscript>
  <script type="module" src="/static/js/{script}"></script>
</body>
</html>
'''


def _shell(title, body_class, script):
    return web.Response(text=_SHELL.format(title=title, body_class=body_class, script=script),
                        content_type='text/html')


async def public_page(request):
    return _shell('LX API Server', 'page-public', 'public.js')


async def admin_page(request):
    # /admin 下的所有页面都由前端路由处理，服务端统一返回同一个页面
    return _shell('管理后台 · LX API Server', 'page-admin', 'admin.js')


def register_routes(app):
    app.on_response_prepare.append(add_security_headers)
    app.router.add_static('/static/', STATIC_DIR, show_index=False)
    api_admin.register(app)
    api_public.register(app)
    app.router.add_get('/', public_page)
    app.router.add_get('/admin', admin_page)
    app.router.add_get('/admin/{tail:.*}', admin_page)
