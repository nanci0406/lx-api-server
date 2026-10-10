# ----------------------------------------
# - mode: python -
# - name: api_public.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 公开首页使用的接口(/api/public/...)：服务状态、在线解析下载链接。

import re

import modules
from common import config
from common.services import admin_auth, module_health, stats_service, users_service

from . import config_schema
from .http import client_ip, fail, ok, read_json

SONG_ID_RE = re.compile(r'[A-Za-z0-9_.\-]{1,64}')


async def status(request):
    rows = []
    for row in module_health.get_cached_module_health():
        if row['status'] == 'disabled':
            continue
        rows.append({
            'source': row['source'],
            'name': config_schema.SOURCE_NAMES.get(row['source'], row['source']),
            'status': row['status'],
            'detail': row['detail'],  # 只是笼统描述，具体账号信息在 admin_detail 里，不对外
            'checked_at': row['checked_at'],
        })
    order = list(config_schema.SOURCE_NAMES)
    rows.sort(key=lambda row: order.index(row['source']) if row['source'] in order else len(order))
    sources = [
        {'id': source, 'name': name, 'qualities': config_schema.QUALITY_OPTIONS[source]}
        for source, name in config_schema.SOURCE_NAMES.items()
        if config.read_config(f'module.{source}.enable')
    ]
    return ok({
        'modules': rows,
        'sources': sources,
        'key_required': bool(config.read_config('security.key.enable')),
        'script_enabled': bool(config.read_config('common.allow_download_script')),
    })


async def resolve(request):
    """首页的在线解析：用用户名和 Key 换取一首歌的下载链接"""
    data = await read_json(request)
    ip = client_ip(request)
    limit_key = 'resolve:' + ip
    if admin_auth.login_blocked(limit_key):
        fail(429, '验证失败次数过多，请 15 分钟后再试')

    source = str(data.get('source') or '')
    song_id = str(data.get('song_id') or '').strip()
    quality = str(data.get('quality') or '')
    if source not in config_schema.SOURCE_NAMES or not config.read_config(f'module.{source}.enable'):
        fail(400, '不支持的平台')
    if quality not in config_schema.QUALITY_OPTIONS[source]:
        fail(400, '不支持的音质')
    if not SONG_ID_RE.fullmatch(song_id):
        fail(400, '歌曲 ID 格式不正确')

    user = None
    if config.read_config('security.key.enable'):
        username = str(data.get('username') or '').strip()
        api_key = str(data.get('key') or '').strip()
        if not username or not api_key:
            fail(400, '请输入用户名和 Key')
        user = users_service.get_user_by_name_and_key(username, api_key)
        if not user:
            admin_auth.record_login_failure(limit_key)
            fail(403, '用户名或 Key 不正确，或用户已被停用')

    try:
        result = await modules.url(source, song_id, quality, {})
    except Exception:
        await stats_service.record_parse_async(user, source, 'url', song_id, quality, False, '内部错误', ip)
        fail(400, '解析失败，请稍后再试')
    if not isinstance(result, dict) or result.get('code') != 0 or not result.get('data'):
        message = (result.get('msg') if isinstance(result, dict) else None) or '解析失败'
        await stats_service.record_parse_async(user, source, 'url', song_id, quality, False, message, ip)
        fail(400, message)
    await stats_service.record_parse_async(user, source, 'url', song_id, quality, True, None, ip)
    extra = result.get('extra') or {}
    return ok({
        'url': result['data'],
        'quality': (extra.get('quality') or {}).get('result') or quality,
        'cached': bool(extra.get('cache')),
        'expire_at': (extra.get('expire') or {}).get('time'),
    })


def register(app):
    app.router.add_get('/api/public/status', status)
    app.router.add_post('/api/public/resolve', resolve)
