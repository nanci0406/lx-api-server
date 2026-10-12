# ----------------------------------------
# - mode: python -
# - name: api_admin.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 后台管理 JSON 接口(/api/admin/...)。所有接口都需要管理员会话，写操作额外做来源校验并要求 JSON 请求体。

import base64
import datetime
import os
import re
import secrets
import shutil
import time

import ruamel.yaml as yaml_

from common import config, db, login_session, scheduler, variable
from common.services import admin_auth, module_health, stats_service, users_service
from modules.tx import login as qq_login
from modules.wy import login as wy_login

from . import config_schema
from .http import check_same_origin, client_ip, current_token, fail, ok, read_json, require_admin

START_TIME = time.time()

USERNAME_RE = re.compile(r'[A-Za-z0-9_.@-]{1,32}')
API_KEY_RE = re.compile(r'[A-Za-z0-9_.~-]{6,64}')

MODULE_NAMES = dict(config_schema.SOURCE_NAMES)


# ---------------------------------------------------------------------------
# 登录 / 退出
# ---------------------------------------------------------------------------

async def login(request):
    check_same_origin(request)
    ip = client_ip(request)
    if admin_auth.login_blocked(ip):
        fail(429, '登录失败次数过多，请 15 分钟后再试')
    data = await read_json(request)
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '').strip()
    if not username or not password:
        fail(400, '请输入用户名和密码')
    if not admin_auth.authenticate_admin(username, password):
        admin_auth.record_login_failure(ip)
        fail(401, '用户名或密码错误')
    admin_auth.clear_login_failures(ip)
    token = admin_auth.create_session(username)
    response = ok({'username': username})
    # 通过 HTTPS 访问(含反向代理后的 HTTPS，由 common.ssl_info.is_https 声明)时只允许在 HTTPS 下携带 Cookie
    secure = request.secure or bool(config.read_config('common.ssl_info.is_https'))
    # SameSite=Strict：后台是同源的单页应用，自己发出的请求都会带上 Cookie，跨站请求一律不带
    response.set_cookie(admin_auth.COOKIE_NAME, token, httponly=True, samesite='Strict', secure=secure, path='/')
    return response


async def logout(request):
    check_same_origin(request)
    admin_auth.destroy_session(request)
    response = ok()
    response.del_cookie(admin_auth.COOKIE_NAME, path='/')
    return response


async def me(request):
    session = require_admin(request)
    admin = admin_auth.get_admin(session['username']) or {}
    return ok({
        'username': session['username'],
        'last_login_at': admin.get('last_login_at'),
        'created_at': admin.get('created_at'),
        'session_started_at': session.get('created_at'),
        'other_sessions': len([s for t, s in variable.admin_sessions.items()
                               if s['username'] == session['username'] and t != current_token(request)]),
        'cookiepool': bool(variable.use_cookie_pool),
    })


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------

def _day_start(days_ago=0):
    """本地时间 days_ago 天前的 0 点；统计"近 N 天"从 N-1 天前的 0 点算起，和图表展示的 N 个自然日一致"""
    day = datetime.date.today() - datetime.timedelta(days=days_ago)
    return int(time.mktime(day.timetuple()))


def _module_rows():
    rows = []
    for row in module_health.get_cached_module_health():
        row = dict(row)
        row['name'] = MODULE_NAMES.get(row['source'], row['source'])
        rows.append(row)
    return rows


def task_label(name):
    pooled = re.match(r'(.+)_pooled_(\d+)$', name)
    base, index = (pooled.group(1), int(pooled.group(2)) + 1) if pooled else (name, None)
    labels = {
        'qqmusic_refresh_login': 'QQ 音乐 · 刷新登录',
        'kg_refresh_login': '酷狗 · 刷新登录',
        'kgmusic_refresh_login': '酷狗 · 刷新登录',
        'wy_refresh_login': '网易云 · 刷新登录',
        'parse_logs_cleanup': '清理过期解析记录',
    }
    if base.startswith('kugou_lite_sign_in'):
        label = '酷狗概念版 · 签到'
    else:
        label = labels.get(base, name)
    return f'{label}(账号池 #{index})' if index else label


def _tasks():
    result = []
    for task in scheduler.get_status():
        task = dict(task)
        task['label'] = task_label(task['name'])
        result.append(task)
    return result


def _overview_queries():
    users = users_service.list_users()
    today = stats_service.get_overview(_day_start())
    week = stats_service.get_overview(_day_start(6))
    logs, _ = stats_service.query_logs(limit=6)
    return users, today, week, logs


async def overview(request):
    session = require_admin(request)
    users, today, week, logs = await db.run_in_db_thread(_overview_queries)
    tasks = _tasks()
    return ok({
        'username': session['username'],
        'uptime': int(time.time() - START_TIME),
        'users': {'total': len(users), 'enabled': len([u for u in users if u['enabled']])},
        'today': today['totals'],
        'week': week['totals'],
        'daily': _fill_days(week['daily'], 7),
        'modules': _module_rows(),
        'tasks': {'total': len(tasks), 'failing': [t for t in tasks if t['consecutive_failures']]},
        'recent': logs,
        'cookiepool': bool(variable.use_cookie_pool),
        'key_enabled': bool(config.read_config('security.key.enable')),
    })


def _fill_days(daily, days):
    """把按天统计补全成连续的 days 天(没有记录的日子记为 0)，方便画图"""
    by_day = {row['day']: row for row in daily}
    today = datetime.date.today()
    result = []
    for offset in range(days - 1, -1, -1):
        day = (today - datetime.timedelta(days=offset)).isoformat()
        row = by_day.get(day) or {'day': day, 'total': 0, 'success': 0}
        result.append({'day': day, 'total': row['total'], 'success': row['success']})
    return result


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def _config_payload():
    sections = []
    for section in config_schema.SECTIONS:
        fields = []
        for field in section['fields']:
            item = {k: v for k, v in field.items() if k != 'key'}
            item['key'] = field['key']
            item['value'] = config_schema.public_value(field, config.read_config(field['key']))
            fields.append(item)
        sections.append(dict(section, fields=fields))
    return {'sections': sections}


async def get_config(request):
    require_admin(request)
    return ok(_config_payload())


async def save_config(request):
    require_admin(request, write=True)
    data = await read_json(request)
    values = data.get('values')
    if not isinstance(values, dict) or not values:
        fail(400, '没有需要保存的修改')
    updates, errors = {}, {}
    for key, value in values.items():
        field = config_schema.FIELDS.get(key)
        if field is None:
            errors[key] = '未知的配置项'
            continue
        if field['type'] == 'secret' and value is None:
            continue  # 密钥类字段没有修改
        try:
            updates[key] = config_schema.convert(field, value)
        except config_schema.ValidationError as e:
            errors[key] = str(e)
    if errors:
        fail(400, '有配置项填写不正确', {'errors': errors})
    if not updates:
        fail(400, '没有需要保存的修改')
    config.write_config_batch(updates)
    reload_error = None
    try:
        config.hot_reload_config()
    except Exception as e:  # 配置已经写入，热重载失败时告诉前端
        reload_error = str(e)
    restart = [config_schema.FIELDS[key]['label'] for key in updates if config_schema.FIELDS[key].get('restart')]
    payload = _config_payload()
    payload.update({'saved': list(updates), 'restart_required': restart, 'reload_error': reload_error})
    return ok(payload)


CONFIG_PATH = './config/config.yml'
MAX_RAW_CONFIG = 512 * 1024


async def get_raw_config(request):
    require_admin(request)
    return ok({'content': config.read_config_text()})


async def save_raw_config(request):
    require_admin(request, write=True)
    data = await read_json(request, max_size=MAX_RAW_CONFIG + 4096)
    content = data.get('content')
    if not isinstance(content, str) or not content.strip():
        fail(400, '配置内容不能为空')
    if len(content) > MAX_RAW_CONFIG:
        fail(413, '配置内容太大')
    try:
        parsed = yaml_.YAML().load(content)
    except Exception as e:
        fail(400, f'YAML 格式错误：{e}')
    if not isinstance(parsed, dict) or not all(isinstance(parsed.get(k), dict) for k in ('common', 'security', 'module')):
        fail(400, '配置必须包含 common、security、module 三个部分')
    backup = CONFIG_PATH + '.bak'
    shutil.copyfile(CONFIG_PATH, backup)
    try:
        config.write_config_text(content)
    except Exception as e:
        # 新配置无法加载：恢复原来的配置，避免服务停在一份坏配置上
        shutil.copyfile(backup, CONFIG_PATH)
        try:
            config.hot_reload_config()
        except Exception:
            pass
        fail(400, f'新配置无法加载，已恢复原配置：{e}')
    return ok({'content': config.read_config_text(), 'backup': os.path.basename(backup)})


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------

def _generate_key():
    return secrets.token_urlsafe(18)


def _validate_key(api_key):
    if not API_KEY_RE.fullmatch(api_key):
        fail(400, 'Key 需要 6～64 位，只能包含字母、数字和 _ . ~ -')


def _user_or_404(user_id):
    try:
        user = users_service.get_user(int(user_id))
    except ValueError:
        user = None
    if not user:
        fail(404, '用户不存在')
    return user


async def list_users(request):
    require_admin(request)
    return ok({
        'users': await db.run_in_db_thread(users_service.list_users_with_usage),
        'script_enabled': bool(config.read_config('common.allow_download_script')),
        'key_enabled': bool(config.read_config('security.key.enable')),
    })


async def create_user(request):
    require_admin(request, write=True)
    data = await read_json(request)
    name = str(data.get('name') or '').strip()
    api_key = str(data.get('api_key') or '').strip() or _generate_key()
    if not USERNAME_RE.fullmatch(name):
        fail(400, '用户名需要 1～32 位，只能包含字母、数字和 _ . @ -')
    _validate_key(api_key)
    taken = users_service.name_or_key_taken(name, api_key)
    if taken:
        fail(409, '用户名已存在' if taken == 'name' else '这个 Key 已被其他用户使用')
    users_service.create_user(name, api_key)
    user = [u for u in users_service.list_users_with_usage() if u['name'] == name][0]
    return ok(user, status=201)


async def update_user(request):
    require_admin(request, write=True)
    user = _user_or_404(request.match_info['user_id'])
    data = await read_json(request)
    if 'enabled' in data:
        if not isinstance(data['enabled'], bool):
            fail(400, 'enabled 需要布尔值')
        users_service.set_enabled(user['id'], data['enabled'])
    return ok(users_service.get_user(user['id']))


async def reset_user_key(request):
    require_admin(request, write=True)
    user = _user_or_404(request.match_info['user_id'])
    data = await read_json(request)
    api_key = str(data.get('api_key') or '').strip() or _generate_key()
    _validate_key(api_key)
    if users_service.name_or_key_taken(api_key=api_key, exclude_id=user['id']):
        fail(409, '这个 Key 已被其他用户使用')
    users_service.set_api_key(user['id'], api_key)
    return ok(users_service.get_user(user['id']))


async def delete_user(request):
    require_admin(request, write=True)
    user = _user_or_404(request.match_info['user_id'])
    users_service.delete_user(user['id'])
    return ok({'id': user['id']})


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

async def stats(request):
    require_admin(request)
    try:
        days = int(request.query.get('days', 7))
    except ValueError:
        days = 7
    if days not in (1, 7, 30):
        days = 7
    data = await db.run_in_db_thread(stats_service.get_overview, _day_start(days - 1))
    data['daily'] = _fill_days(data['daily'], days)
    data['days'] = days
    for row in data['by_source']:
        row['name'] = MODULE_NAMES.get(row['source'], row['source'])
    return ok(data)


async def stats_logs(request):
    require_admin(request)
    query = request.query
    try:
        limit = max(1, min(int(query.get('limit', 30)), 200))
        offset = max(0, int(query.get('offset', 0)))
    except ValueError:
        fail(400, '分页参数错误')
    result = query.get('result')
    success = True if result == 'success' else (False if result == 'failure' else None)
    rows, total = await db.run_in_db_thread(
        stats_service.query_logs, limit, offset, query.get('username') or None, query.get('source') or None, success)
    return ok({'logs': rows, 'total': total, 'limit': limit, 'offset': offset})


# ---------------------------------------------------------------------------
# 模块状态与定时任务
# ---------------------------------------------------------------------------

def _health_payload():
    return {'modules': _module_rows(), 'tasks': _tasks()}


async def health(request):
    require_admin(request)
    return ok(_health_payload())


async def refresh_health(request):
    require_admin(request, write=True)
    await module_health.refresh_module_health(force=True)
    return ok(_health_payload())


async def run_task(request):
    require_admin(request, write=True)
    name = request.match_info['name']
    if name not in [t['name'] for t in scheduler.get_status()]:
        fail(404, '任务不存在或未启用')
    if not scheduler.run_now(name):
        fail(409, '任务正在执行中')
    return ok({'name': name})


# ---------------------------------------------------------------------------
# 管理员账号
# ---------------------------------------------------------------------------

async def change_password(request):
    session = require_admin(request, write=True)
    data = await read_json(request)
    current = str(data.get('current') or '').strip()
    new = str(data.get('new') or '').strip()
    ip = client_ip(request)
    limit_key = 'password:' + ip
    if admin_auth.login_blocked(limit_key):
        fail(429, '尝试次数过多，请 15 分钟后再试')
    if not admin_auth.check_password(session['username'], current):
        admin_auth.record_login_failure(limit_key)
        fail(400, '当前密码不正确')
    if new == current:
        fail(400, '新密码不能和当前密码相同')
    admin = admin_auth.get_admin(session['username'])
    try:
        admin_auth.update_admin_password(admin['id'], new)
    except ValueError as e:
        fail(400, str(e))
    admin_auth.destroy_other_sessions(session['username'], current_token(request))
    return ok()


async def logout_others(request):
    session = require_admin(request, write=True)
    before = len(variable.admin_sessions)
    admin_auth.destroy_other_sessions(session['username'], current_token(request))
    return ok({'closed': before - len(variable.admin_sessions)})


# ---------------------------------------------------------------------------
# 音乐平台登录(QQ 音乐扫码/验证码、网易云扫码)
# ---------------------------------------------------------------------------

def _safe_security_url(url):
    """人机验证地址来自服务端响应，只放行 QQ/腾讯域名下的 https 地址"""
    from urllib.parse import urlsplit
    parts = urlsplit(url or '')
    host = (parts.hostname or '').lower()
    if parts.scheme == 'https' and any(host == d or host.endswith('.' + d) for d in ('qq.com', 'tencent.com')):
        return url
    return ''


def _login_session(request, session):
    ls = login_session.get_session(request.match_info['session_id'], session['username'])
    if not ls:
        fail(404, '登录会话不存在或已过期')
    return ls


async def login_start_qr(request):
    session = require_admin(request, write=True)
    data = await read_json(request)
    kind = str(data.get('kind') or '')
    try:
        if kind == 'wy':
            ls = await wy_login.start_qr(session['username'])
        else:
            ls = await qq_login.start_qr(kind, session['username'])
    except login_session.LoginError as e:
        fail(400, e.message)
    image = f"data:{ls.mimetype};base64,{base64.b64encode(ls.image).decode('ascii')}"
    return ok(dict(ls.public(), image=image, expires_in=login_session.QR_TIMEOUT))


async def login_status(request):
    session = require_admin(request)
    return ok(_login_session(request, session).public())


async def login_cancel(request):
    session = require_admin(request, write=True)
    login_session.cancel_session(request.match_info['session_id'], session['username'])
    return ok()


async def qq_phone_send(request):
    session = require_admin(request, write=True)
    data = await read_json(request)
    try:
        result = await qq_login.phone_send(session['username'], data.get('phone', ''), data.get('country_code', '86'))
    except login_session.LoginError as e:
        fail(400, e.message)
    if 'url' in result:
        result['url'] = _safe_security_url(result['url'])
    return ok(dict(result, cooldown=qq_login.SMS_COOLDOWN))


async def qq_phone_verify(request):
    session = require_admin(request, write=True)
    data = await read_json(request)
    try:
        ls = await qq_login.phone_verify(session['username'], data.get('phone', ''), data.get('code', ''),
                                         data.get('country_code', '86'))
    except login_session.LoginError as e:
        fail(400, e.message)
    return ok(ls.public())


async def login_apply(request):
    session = require_admin(request, write=True)
    ls = _login_session(request, session)
    data = await read_json(request)
    platform_login = wy_login if ls.platform == 'wy' else qq_login
    try:
        note = platform_login.apply_credential(ls, str(data.get('target') or ''), bool(data.get('enable_refresh')))
    except login_session.LoginError as e:
        fail(400, e.message)
    reload_error = None
    try:
        # 重新加载配置并重新注册定时任务，让自动刷新登录立即生效
        config.hot_reload_config()
    except Exception as e:
        reload_error = str(e)
    return ok({'note': note, 'reload_error': reload_error})


def register(app):
    r = app.router
    r.add_post('/api/admin/login', login)
    r.add_post('/api/admin/logout', logout)
    r.add_get('/api/admin/me', me)
    r.add_get('/api/admin/overview', overview)
    r.add_get('/api/admin/config', get_config)
    r.add_put('/api/admin/config', save_config)
    r.add_get('/api/admin/config/raw', get_raw_config)
    r.add_put('/api/admin/config/raw', save_raw_config)
    r.add_get('/api/admin/users', list_users)
    r.add_post('/api/admin/users', create_user)
    r.add_patch('/api/admin/users/{user_id}', update_user)
    r.add_delete('/api/admin/users/{user_id}', delete_user)
    r.add_post('/api/admin/users/{user_id}/reset-key', reset_user_key)
    r.add_get('/api/admin/stats', stats)
    r.add_get('/api/admin/stats/logs', stats_logs)
    r.add_get('/api/admin/health', health)
    r.add_post('/api/admin/health/refresh', refresh_health)
    r.add_post('/api/admin/tasks/{name}/run', run_task)
    r.add_post('/api/admin/account/password', change_password)
    r.add_post('/api/admin/account/logout-others', logout_others)
    r.add_post('/api/admin/music-login/qr', login_start_qr)
    r.add_post('/api/admin/music-login/phone/send', qq_phone_send)
    r.add_post('/api/admin/music-login/phone/verify', qq_phone_verify)
    r.add_get('/api/admin/music-login/{session_id}', login_status)
    r.add_post('/api/admin/music-login/{session_id}/cancel', login_cancel)
    r.add_post('/api/admin/music-login/{session_id}/apply', login_apply)
