import html
import json
import time

from aiohttp import web

from common import config
from common.services import admin_auth, module_health, stats_service, users_service
import modules


STATUS_LABELS = {
    'healthy': '正常',
    'degraded': '降级',
    'misconfigured': '配置缺失',
    'disabled': '已关闭',
}

DOWNLOAD_SOURCES = [('kg', '酷狗'), ('tx', 'QQ 音乐'), ('wy', '网易云'), ('mg', '咪咕'), ('kw', '酷我')]
QUALITY_OPTIONS = ['128k', '320k', 'flac', 'flac24bit', 'master']

CONFIG_SECTIONS = [
    {
        'title': '服务基础',
        'description': '控制监听地址、端口和基础运行开关。监听相关字段保存后建议重启确认。',
        'fields': [
            {'key': 'common.hosts', 'label': '监听地址', 'type': 'list', 'restart': True, 'placeholder': '每行一个，例如 0.0.0.0'},
            {'key': 'common.ports', 'label': '监听端口', 'type': 'int_list', 'restart': True, 'placeholder': '每行一个，例如 9763'},
            {'key': 'common.allow_download_script', 'label': '允许下载脚本', 'type': 'bool'},
            {'key': 'common.debug_mode', 'label': '调试模式', 'type': 'bool'},
            {'key': 'common.log_length_limit', 'label': '日志长度限制', 'type': 'int'},
        ],
    },
    {
        'title': '代理与安全',
        'description': '这些项会直接影响后续请求行为，保存后立即热生效。',
        'fields': [
            {'key': 'common.proxy.enable', 'label': '启用代理', 'type': 'bool'},
            {'key': 'common.proxy.http_value', 'label': 'HTTP 代理', 'type': 'text'},
            {'key': 'common.proxy.https_value', 'label': 'HTTPS 代理', 'type': 'text'},
            {'key': 'security.key.enable', 'label': '启用用户 Key 鉴权', 'type': 'bool'},
            {'key': 'security.check_lxm.enable', 'label': '启用 lxm 请求头校验', 'type': 'bool'},
            {'key': 'security.allowed_host.enable', 'label': '启用 Host 白名单', 'type': 'bool'},
            {'key': 'security.allowed_host.list', 'label': '允许的 Host', 'type': 'list', 'placeholder': '每行一个 host'},
        ],
    },
    {
        'title': '酷狗模块',
        'description': '模块开关与关键凭据。缺少关键字段时首页会显示配置缺失。',
        'fields': [
            {'key': 'module.kg.enable', 'label': '启用酷狗', 'type': 'bool'},
            {'key': 'module.kg.user.token', 'label': 'token', 'type': 'text'},
            {'key': 'module.kg.user.userid', 'label': 'userid', 'type': 'text'},
            {'key': 'module.kg.user.mid', 'label': 'mid', 'type': 'text'},
        ],
    },
    {
        'title': '酷狗自动登录',
        'description': '这里集中管理酷狗概念版签到与 token 保活任务，保存后会重新注册定时任务。',
        'fields': [
            {'key': 'module.kg.user.lite_sign_in.enable', 'label': '启用概念版自动签到', 'type': 'bool'},
            {'key': 'module.kg.user.lite_sign_in.interval', 'label': '签到间隔(秒)', 'type': 'int'},
            {'key': 'module.kg.user.lite_sign_in.mixsongmid.value', 'label': 'mixsongmid', 'type': 'text', 'placeholder': 'auto 或手动填写 songmid'},
            {'key': 'module.kg.user.refresh_login.enable', 'label': '启用 token 保活', 'type': 'bool'},
            {'key': 'module.kg.user.refresh_login.interval', 'label': '保活间隔(秒)', 'type': 'int'},
            {'key': 'module.kg.user.refresh_login.login_url', 'label': '登录地址', 'type': 'text'},
        ],
    },
    {
        'title': 'QQ 音乐模块',
        'description': 'QQ 音乐的 key 与 uin 需要成对配置。',
        'fields': [
            {'key': 'module.tx.enable', 'label': '启用 QQ 音乐', 'type': 'bool'},
            {'key': 'module.tx.user.qqmusic_key', 'label': 'qqmusic_key', 'type': 'text'},
            {'key': 'module.tx.user.uin', 'label': 'uin', 'type': 'text'},
            {'key': 'module.tx.cdnaddr', 'label': '下载前缀', 'type': 'text'},
        ],
    },
    {
        'title': 'QQ 自动登录',
        'description': 'QQ 音乐刷新登录任务设置，保存后会立即按最新配置重建任务。',
        'fields': [
            {'key': 'module.tx.user.refresh_login.enable', 'label': '启用刷新登录', 'type': 'bool'},
            {'key': 'module.tx.user.refresh_login.interval', 'label': '刷新间隔(秒)', 'type': 'int'},
        ],
    },
    {
        'title': '网易云模块',
        'description': 'Cookie 可留空，但留空时模块状态会判定为配置缺失。',
        'fields': [
            {'key': 'module.wy.enable', 'label': '启用网易云', 'type': 'bool'},
            {'key': 'module.wy.user.cookie', 'label': 'Cookie', 'type': 'textarea', 'rows': 4},
        ],
    },
    {
        'title': '网易云自动登录',
        'description': '网易云 cookie 保活任务设置，保存后会立即按最新配置重建任务。',
        'fields': [
            {'key': 'module.wy.user.refresh_login.enable', 'label': '启用刷新登录', 'type': 'bool'},
            {'key': 'module.wy.user.refresh_login.interval', 'label': '刷新间隔(秒)', 'type': 'int'},
        ],
    },
    {
        'title': '咪咕模块',
        'description': '咪咕需要 by 与 session，User-Agent 按需调整。',
        'fields': [
            {'key': 'module.mg.enable', 'label': '启用咪咕', 'type': 'bool'},
            {'key': 'module.mg.user.by', 'label': 'by', 'type': 'text'},
            {'key': 'module.mg.user.session', 'label': 'session', 'type': 'text'},
            {'key': 'module.mg.user.useragent', 'label': 'User-Agent', 'type': 'textarea', 'rows': 3},
        ],
    },
    {
        'title': '咪咕自动登录',
        'description': '咪咕 cookie 保活任务设置，保存后会立即按最新配置重建任务。',
        'fields': [
            {'key': 'module.mg.user.refresh_login.enable', 'label': '启用刷新登录', 'type': 'bool'},
            {'key': 'module.mg.user.refresh_login.interval', 'label': '刷新间隔(秒)', 'type': 'int'},
        ],
    },
    {
        'title': '酷我模块',
        'description': '酷我的 uid、token、device_id 缺一不可。',
        'fields': [
            {'key': 'module.kw.enable', 'label': '启用酷我', 'type': 'bool'},
            {'key': 'module.kw.proto', 'label': '协议类型', 'type': 'text'},
            {'key': 'module.kw.user.uid', 'label': 'uid', 'type': 'text'},
            {'key': 'module.kw.user.token', 'label': 'token', 'type': 'text'},
            {'key': 'module.kw.user.device_id', 'label': 'device_id', 'type': 'text'},
        ],
    },
]

CONFIG_SECTION_MAP = {section['title']: section for section in CONFIG_SECTIONS}


def _page(title, body, extra_nav='', hero_text=None):
    description = hero_text or '面向桌面与手机的统一控制台，覆盖模块状态、在线下载、配置热重载、用户管理与解析统计。'
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <div class="wrapper">
    <div class="hero shell">
      <div class="hero-copy loading-glow">
        <div class="eyebrow">LX API SERVER</div>
        <h1>{html.escape(title)}</h1>
        <p>{html.escape(description)}</p>
      </div>
      <div class="hero-side loading-glow">
        <div class="nav">
          <a class="btn secondary" href="/">首页</a>
          <a class="btn secondary" href="/admin">管理后台</a>
          {extra_nav}
        </div>
        <div class="hero-note">模块状态每 2 分钟自动刷新一次，后台也支持手动刷新。</div>
      </div>
    </div>
    {body}
  </div>
</body>
</html>'''


def _admin_page(title, body, description='管理操作页。完成当前操作后返回仪表盘，再进入其他模块。'):
    return web.Response(
        text=_page(title, body, '<a class="btn secondary" href="/admin/logout">退出</a>', description),
        content_type='text/html',
    )


def _format_checked_at(timestamp):
    if not timestamp:
        return '-'
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))


def _format_admin_time(timestamp):
    if not timestamp:
        return '-'
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))


def _status_badge(status):
    return f'<span class="status {html.escape(status)}">{html.escape(STATUS_LABELS.get(status, status))}</span>'


def _public_health_rows(rows):
    return [row for row in rows if row.get('status') != 'disabled']


def _render_status_cards(health_rows):
    status_cards = []
    for row in health_rows:
        checked = _format_checked_at(row.get('checked_at'))
        status_cards.append(f'''
        <article class="card module-card loading-glow" data-source="{html.escape(row['source'])}">
          <div class="module-head">
            <div>
              <div class="eyebrow">SOURCE</div>
              <strong>{html.escape(row['source'].upper())}</strong>
            </div>
            {_status_badge(row['status'])}
          </div>
          <p class="module-detail">{html.escape(row.get('detail') or '')}</p>
          <div class="small module-time">最近检查: {html.escape(checked)}</div>
        </article>''')
    if not status_cards:
        status_cards.append('<div class="card"><p>当前没有启用中的模块，管理员可先到后台完成配置。</p></div>')
    return ''.join(status_cards)


def _json_ok(data):
    return web.json_response({'code': 0, 'msg': 'success', 'data': data})


def _field_value(field):
    value = config.read_config(field['key'])
    if value is None:
        value = config.read_default_config(field['key'])
    if value is None:
        return ''
    return value


def _render_config_input(field):
    value = _field_value(field)
    key = html.escape(field['key'])
    label = html.escape(field['label'])
    tip = '<span class="field-tag">需重启确认</span>' if field.get('restart') else ''
    field_type = field['type']
    if field_type == 'bool':
        current = 'true' if bool(value) else 'false'
        control = f'''
        <select name="{key}">
          <option value="true"{' selected' if current == 'true' else ''}>开启</option>
          <option value="false"{' selected' if current == 'false' else ''}>关闭</option>
        </select>'''
    elif field_type in ('list', 'int_list'):
        if isinstance(value, list):
            raw = '\n'.join(str(item) for item in value)
        else:
            raw = str(value)
        control = f'<textarea name="{key}" rows="4" placeholder="{html.escape(field.get("placeholder", ""))}">{html.escape(raw)}</textarea>'
    elif field_type == 'textarea':
        rows = int(field.get('rows', 4))
        control = f'<textarea name="{key}" rows="{rows}">{html.escape(str(value))}</textarea>'
    else:
        control = f'<input name="{key}" value="{html.escape(str(value))}" placeholder="{html.escape(field.get("placeholder", ""))}">'
    return f'''
    <div class="row">
      <label>{label}{tip}</label>
      {control}
    </div>'''


def _render_config_sections():
    cards = []
    for section in CONFIG_SECTIONS:
        fields_html = ''.join(_render_config_input(field) for field in section['fields'])
        cards.append(f'''
        <section class="card config-card loading-glow">
          <form method="post" action="/admin/config">
            <input type="hidden" name="section_title" value="{html.escape(section['title'])}">
            <div class="panel-top">
              <div>
                <div class="eyebrow">CONFIG</div>
                <h2>{html.escape(section['title'])}</h2>
              </div>
              <div class="actions">
                <button type="submit">保存本分组</button>
                <button type="submit" name="action" value="reload" class="secondary">保存并热重载</button>
              </div>
            </div>
            <p class="kv">{html.escape(section['description'])}</p>
            {fields_html}
          </form>
        </section>''')
    return ''.join(cards)


def _render_home_health_summary(health_rows):
    total = len(health_rows)
    healthy = len([row for row in health_rows if row.get('status') == 'healthy'])
    issue = total - healthy
    return f'''
    <div class="summary-strip">
      <div><span>已展示模块</span><strong>{total}</strong></div>
      <div><span>状态正常</span><strong>{healthy}</strong></div>
      <div><span>需关注</span><strong>{issue}</strong></div>
    </div>'''


def _parse_form_value(field, raw_value):
    if field['type'] == 'bool':
        return str(raw_value).lower() == 'true'
    if field['type'] == 'int':
        raw = str(raw_value).strip()
        return int(raw) if raw else 0
    if field['type'] == 'int_list':
        values = []
        for item in str(raw_value).replace(',', '\n').splitlines():
            item = item.strip()
            if item:
                values.append(int(item))
        return values
    if field['type'] == 'list':
        values = []
        for item in str(raw_value).replace(',', '\n').splitlines():
            item = item.strip()
            if item:
                values.append(item)
        return values
    return str(raw_value).strip()


def _dashboard_back_actions(path):
    return f'<div class="actions"><a class="btn secondary" href="{html.escape(path)}">返回当前模块</a><a class="btn secondary" href="/admin">返回仪表盘</a></div>'


async def home(request):
    health_rows = _public_health_rows(module_health.get_cached_module_health())
    labels_json = json.dumps(STATUS_LABELS, ensure_ascii=False)
    body = f'''
    <section class="grid two hero-panels compact-home-grid">
      <section class="card panel-accent landing-card loading-glow">
        <div class="eyebrow">PROJECT OVERVIEW</div>
        <h2>项目介绍</h2>
        <div class="project-copy kv">
          <p><strong>lx-music-api-server</strong> 是一个面向多音乐源的解析服务项目，提供统一 API、Web 管理后台，以及按用户隔离的下载入口。</p>
          <p>它适合部署为私有服务节点，用来集中维护模块凭据、管理 API 用户、观察模块健康状态，并保留对现有客户端与脚本的兼容能力。</p>
          <p>当前首页只保留项目介绍、模块状态和下载入口三类核心信息，其他运维操作都放到后台处理。</p>
        </div>
        <div class="project-badges">
          <span>多源解析</span>
          <span>统一鉴权</span>
          <span>Web 管理后台</span>
          <span>配置热重载</span>
        </div>
      </section>
      <section class="card panel-dark compact-home-card loading-glow">
        <div class="eyebrow">DOWNLOAD ENTRY</div>
        <h2>音源下载入口</h2>
        <p class="kv light">输入普通 API 用户名和 Key，即可生成下载链接或获取客户端脚本，继续复用现有解析链路。</p>
        <form method="post" action="/download-link">
          <div class="row"><label>用户名</label><input name="username" required></div>
          <div class="row"><label>用户 Key</label><input name="key" required></div>
          <div class="inline-fields">
            <div class="row"><label>来源</label>
              <select name="source">{''.join(f'<option value="{value}">{name}</option>' for value, name in DOWNLOAD_SOURCES)}</select>
            </div>
            <div class="row"><label>音质</label>
              <select name="quality">{''.join(f'<option value="{value}">{value}</option>' for value in QUALITY_OPTIONS)}</select>
            </div>
          </div>
          <div class="row"><label>歌曲 ID</label><input name="song_id" required></div>
          <button type="submit">生成下载链接</button>
        </form>
        <div class="divider"></div>
        <form method="get" action="/script">
          <div class="row"><label>用户 Key</label><input name="key" required></div>
          <button type="submit" class="secondary">下载音源脚本</button>
        </form>
        <p class="kv light top-gap">兼容请求头: <code>X-Request-User</code> / <code>X-Request-Key</code></p>
      </section>
    </section>
    <section class="card panel-accent loading-glow">
      <div class="panel-top">
        <div>
          <div class="eyebrow">HEALTH OVERVIEW</div>
          <h2>模块健康状态</h2>
        </div>
        <div class="small refresh-indicator">自动刷新: 120 秒</div>
      </div>
      <p class="kv">首页只展示启用中的模块，并把状态结果压缩成可快速浏览的卡片。完整列表仍在后台保留。</p>
      {_render_home_health_summary(health_rows)}
      <div id="module-status-grid" class="grid three compact-status-grid">{_render_status_cards(health_rows)}</div>
    </section>
    <script>
      const statusLabels = {labels_json};
      function escapeHtml(value) {{
        return String(value ?? '').replace(/[&<>"']/g, (char) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }})[char]);
      }}
      function renderStatusCard(row) {{
        const label = statusLabels[row.status] || row.status || '';
        return `
          <article class="card module-card loading-glow" data-source="${{escapeHtml(row.source)}}">
            <div class="module-head">
              <div>
                <div class="eyebrow">SOURCE</div>
                <strong>${{escapeHtml(String(row.source || '').toUpperCase())}}</strong>
              </div>
              <span class="status ${{escapeHtml(row.status || '')}}">${{escapeHtml(label)}}</span>
            </div>
            <p class="module-detail">${{escapeHtml(row.detail || '')}}</p>
            <div class="small module-time">最近检查: ${{escapeHtml(row.checked_at_text || '-')}}</div>
          </article>`;
      }}
      function renderHealthSummary(rows) {{
        const healthy = rows.filter((row) => row.status === 'healthy').length;
        const issue = rows.length - healthy;
        return `
          <div class="summary-strip">
            <div><span>已展示模块</span><strong>${{rows.length}}</strong></div>
            <div><span>状态正常</span><strong>${{healthy}}</strong></div>
            <div><span>需关注</span><strong>${{issue}}</strong></div>
          </div>`;
      }}
      async function refreshModuleStatus() {{
        try {{
          const res = await fetch('/api/webui/module-health?scope=public');
          const payload = await res.json();
          if (!payload || !Array.isArray(payload.data)) return;
          const container = document.getElementById('module-status-grid');
          const summary = document.querySelector('.summary-strip');
          if (!payload.data.length) {{
            if (summary) summary.outerHTML = renderHealthSummary([]);
            container.innerHTML = '<div class="card"><p>当前没有启用中的模块，管理员可先到后台完成配置。</p></div>';
            return;
          }}
          if (summary) summary.outerHTML = renderHealthSummary(payload.data);
          container.innerHTML = payload.data.map(renderStatusCard).join('');
        }} catch (error) {{
          console.error(error);
        }}
      }}
      setInterval(refreshModuleStatus, 120000);
    </script>
    '''
    return web.Response(text=_page('音乐解析服务面板', body, hero_text='一个面向私有部署的多源音乐解析服务项目，提供统一接口、Web 管理后台与可观测的模块健康状态。'), content_type='text/html')


async def generate_download_link(request):
    data = await request.post()
    username = data.get('username', '').strip()
    api_key = data.get('key', '').strip()
    source = data.get('source', '').strip()
    song_id = data.get('song_id', '').strip()
    quality = data.get('quality', '').strip()
    user = users_service.get_user_by_name_and_key(username, api_key)
    if not user:
        body = '<div class="notice error">用户或 Key 无效。</div>'
        body += '<a class="btn secondary" href="/">返回首页</a>'
        return web.Response(text=_page('生成下载链接失败', body), content_type='text/html', status=403)
    try:
        result = await modules.url(source, song_id, quality, {})
        final_url = result['data'] if isinstance(result, dict) else result
        body = f'''
        <section class="card result-card loading-glow">
          <div class="eyebrow">READY</div>
          <h2>下载链接已生成</h2>
          <div class="meta-grid">
            <div><span class="small">用户</span><strong>{html.escape(username)}</strong></div>
            <div><span class="small">来源</span><strong>{html.escape(source)}</strong></div>
            <div><span class="small">音质</span><strong>{html.escape(quality)}</strong></div>
          </div>
          <p><a class="btn" href="{html.escape(final_url)}" target="_blank" rel="noopener">打开下载链接</a></p>
          <p class="kv break-all">{html.escape(final_url)}</p>
          <div class="actions"><a class="btn secondary" href="/">返回首页</a></div>
        </section>
        '''
        return web.Response(text=_page('下载链接', body), content_type='text/html')
    except Exception as e:
        body = f'<div class="notice error">解析失败: {html.escape(str(e))}</div><a class="btn secondary" href="/">返回首页</a>'
        return web.Response(text=_page('生成下载链接失败', body), content_type='text/html', status=500)


async def module_health_api(request):
    rows = module_health.get_cached_module_health()
    if request.query.get('scope') == 'public':
        rows = _public_health_rows(rows)
    payload = []
    for row in rows:
        row_dict = dict(row)
        row_dict['checked_at_text'] = _format_checked_at(row.get('checked_at'))
        payload.append(row_dict)
    return _json_ok(payload)


async def admin_login_page(request):
    body = '''
    <section class="card login-card loading-glow">
      <h2>管理员登录</h2>
      <form method="post" action="/admin/login">
        <div class="row"><label>用户名</label><input name="username" required></div>
        <div class="row"><label>密码</label><input name="password" type="password" required></div>
        <button type="submit">登录后台</button>
      </form>
    </section>
    '''
    return web.Response(text=_page('管理员登录', body), content_type='text/html')


async def admin_login(request):
    data = await request.post()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not admin_auth.authenticate_admin(username, password):
        body = '<div class="notice error">管理员用户名或密码错误。</div>'
        body += '<a class="btn secondary" href="/admin/login">返回登录</a>'
        return web.Response(text=_page('管理员登录失败', body), content_type='text/html', status=403)
    token = admin_auth.create_session(username)
    response = web.HTTPFound('/admin')
    response.set_cookie(admin_auth.COOKIE_NAME, token, httponly=True, samesite='Lax')
    raise response


async def admin_logout(request):
    admin_auth.destroy_session(request)
    response = web.HTTPFound('/admin/login')
    response.del_cookie(admin_auth.COOKIE_NAME)
    raise response


def _require_admin(request):
    session = admin_auth.get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')
    return session


async def admin_dashboard(request):
    session = _require_admin(request)
    summary = stats_service.get_summary()
    users = users_service.list_users()
    health_rows = module_health.get_cached_module_health()
    active_modules = len(_public_health_rows(health_rows))
    body = f'''
    <div class="dashboard-top grid three">
      <section class="card metric-card loading-glow"><div class="eyebrow">ADMIN</div><h3>{html.escape(session['username'])}</h3><p class="kv">当前登录管理员</p></section>
      <section class="card metric-card loading-glow"><div class="eyebrow">USERS</div><h3>{len(users)}</h3><p class="kv">已录入 API 用户数量</p></section>
      <section class="card metric-card loading-glow"><div class="eyebrow">MODULES</div><h3>{active_modules}</h3><p class="kv">首页正在展示的启用模块数</p></section>
    </div>
    <div class="grid two" style="margin-top:18px;">
      <section class="card panel-accent loading-glow">
        <h2>后台模块入口</h2>
        <p class="kv">从这里进入具体管理页。进入某个模块后，如需切换到别的模块，请先返回仪表盘。</p>
        <div class="actions stack-mobile">
          <a class="btn" href="/admin/config">配置管理</a>
          <a class="btn" href="/admin/users">用户管理</a>
          <a class="btn" href="/admin/stats">解析统计</a>
          <a class="btn" href="/admin/health">模块状态</a>
          <a class="btn" href="/admin/admins">管理员密码</a>
          <a class="btn secondary" href="/admin/logout">退出登录</a>
        </div>
      </section>
      <section class="card compact-card loading-glow">
        <h2>运行说明</h2>
        <p class="kv">配置保存后会立即重载并重新注册刷新登录类任务。模块状态每 2 分钟自动刷新一次，管理员仍可手动立即刷新。</p>
      </section>
    </div>
    <section class="card loading-glow" style="margin-top:18px;">
      <h2>最近活跃用户汇总</h2>
      <div class="table-shell"><div class="table-wrap">
        <table class="table"><thead><tr><th>用户</th><th>总次数</th><th>成功</th><th>失败</th></tr></thead><tbody>{''.join([f"<tr><td>{html.escape(row['username'])}</td><td>{row['total']}</td><td>{row['success_count'] or 0}</td><td>{row['failure_count'] or 0}</td></tr>" for row in summary[:8]]) or '<tr><td colspan="4">暂无统计</td></tr>'}</tbody></table>
      </div></div>
    </section>
    '''
    return _admin_page('管理后台', body, '后台首页用于进入各个管理模块。切换模块时请先回到这里，再进入下一个页面。')


async def admin_config_page(request):
    _require_admin(request)
    body = f'''
    <section class="card panel-accent config-intro loading-glow">
      <div class="panel-top">
        <div>
          <div class="eyebrow">CONFIG CENTER</div>
          <h2>分组配置管理</h2>
        </div>
        <div class="actions"><a class="btn" href="/admin/config/reload">仅热重载</a><a class="btn secondary" href="/admin">返回仪表盘</a></div>
      </div>
      <p class="kv">这里不再直接暴露整份 YAML。每个分组单独保存，减少误改概率，也更适合手机端操作。自动刷新登录类配置已经拆分到单独分组，保存后会重新注册定时任务。</p>
    </section>
    <div class="grid two admin-grid config-grid">{_render_config_sections()}</div>
    '''
    return _admin_page('配置管理', body)


async def admin_config_save(request):
    _require_admin(request)
    data = await request.post()
    section_title = data.get('section_title', '')
    section = CONFIG_SECTION_MAP.get(section_title)
    if not section:
        body = '<div class="notice error">未找到对应的配置分组。</div>'
        body += _dashboard_back_actions('/admin/config')
        return _admin_page('配置保存结果', body)
    action = data.get('action', '').strip()
    try:
        for field in section['fields']:
            raw_value = data.get(field['key'], '')
            parsed_value = _parse_form_value(field, raw_value)
            config.write_config(field['key'], parsed_value)
        if action == 'reload':
            config.hot_reload_config()
            body = f'<div class="notice">{html.escape(section_title)} 已保存并热重载。</div>'
        else:
            body = f'<div class="notice">{html.escape(section_title)} 已保存到配置文件。</div>'
    except Exception as e:
        body = f'<div class="notice error">保存失败: {html.escape(str(e))}</div>'
    body += _dashboard_back_actions('/admin/config')
    return _admin_page('配置保存结果', body)


async def admin_config_reload(request):
    _require_admin(request)
    try:
        config.hot_reload_config()
        body = '<div class="notice">配置已热重载，刷新登录类任务也已重新注册。</div>'
    except Exception as e:
        body = f'<div class="notice error">热重载失败: {html.escape(str(e))}</div>'
    body += _dashboard_back_actions('/admin/config')
    return _admin_page('配置热重载结果', body)


async def admin_users_page(request):
    _require_admin(request)
    rows = []
    for user in users_service.list_users():
        rows.append(f'''
        <tr>
          <td>{user['id']}</td>
          <td>{html.escape(user['name'])}</td>
          <td><code>{html.escape(user['api_key'])}</code></td>
          <td>{'启用' if user['enabled'] else '禁用'}</td>
          <td>{user['created_at']}</td>
          <td>{user['last_used_at'] or '-'}</td>
          <td>
            <form method="post" action="/admin/users/delete" onsubmit="return confirm('确认删除该用户？')">
              <input type="hidden" name="user_id" value="{user['id']}">
              <button type="submit">删除</button>
            </form>
          </td>
        </tr>
        ''')
    body = f'''
    <section class="card panel-accent page-lead loading-glow">
      <div class="panel-top">
        <div>
          <div class="eyebrow">USER MODULE</div>
          <h2>用户管理</h2>
        </div>
        <a class="btn secondary" href="/admin">返回仪表盘</a>
      </div>
      <p class="kv">当前页面只处理用户相关操作。如需进入其他后台模块，请先返回仪表盘。</p>
    </section>
    <div class="grid two admin-grid">
      <section class="card compact-card loading-glow">
        <div class="eyebrow">CREATE USER</div>
        <h2>新增用户</h2>
        <form method="post" action="/admin/users/create">
          <div class="row"><label>用户名</label><input name="name" required></div>
          <div class="row"><label>用户 Key</label><input name="api_key" required></div>
          <button type="submit">创建用户</button>
        </form>
      </section>
      <section class="card loading-glow">
        <div class="eyebrow">USER TABLE</div>
        <h2>用户列表</h2>
        <div class="table-shell"><div class="table-wrap">
          <table class="table responsive-table">
            <thead><tr><th>ID</th><th>用户名</th><th>Key</th><th>状态</th><th>创建时间</th><th>最近使用</th><th>操作</th></tr></thead>
            <tbody>{''.join(rows) or '<tr><td colspan="7">暂无用户</td></tr>'}</tbody>
          </table>
        </div></div>
      </section>
    </div>
    '''
    return _admin_page('用户管理', body)


async def admin_user_create(request):
    _require_admin(request)
    data = await request.post()
    try:
        users_service.create_user(data.get('name', '').strip(), data.get('api_key', '').strip())
        body = '<div class="notice">用户已创建。</div>'
    except Exception as e:
        body = f'<div class="notice error">创建失败: {html.escape(str(e))}</div>'
    body += _dashboard_back_actions('/admin/users')
    return _admin_page('用户创建结果', body)


async def admin_user_delete(request):
    _require_admin(request)
    data = await request.post()
    users_service.delete_user(int(data.get('user_id')))
    raise web.HTTPFound('/admin/users')


async def admin_stats_page(request):
    _require_admin(request)
    summary = stats_service.get_summary()
    selected_user = request.query.get('username', '').strip()
    breakdown = stats_service.get_user_breakdown(selected_user) if selected_user else []
    recent_logs = stats_service.get_recent_logs(30)
    summary_rows = []
    for row in summary:
        summary_rows.append(f'''<tr>
          <td><a href="/admin/stats?username={html.escape(row['username'])}">{html.escape(row['username'])}</a></td>
          <td>{row['total']}</td><td>{row['success_count'] or 0}</td><td>{row['failure_count'] or 0}</td>
        </tr>''')
    breakdown_rows = []
    for row in breakdown:
        breakdown_rows.append(f'''<tr><td>{html.escape(row['source'])}</td><td>{row['total']}</td><td>{row['success_count'] or 0}</td><td>{row['failure_count'] or 0}</td></tr>''')
    recent_rows = []
    for row in recent_logs:
        recent_rows.append(f'''<tr><td>{html.escape(str(row['username'] or '-'))}</td><td>{html.escape(str(row['source'] or '-'))}</td><td>{html.escape(str(row['method'] or '-'))}</td><td>{1 if row['success'] else 0}</td><td>{html.escape(str(row['song_id'] or '-'))}</td><td>{html.escape(str(row['error_message'] or '-'))}</td><td>{row['created_at']}</td></tr>''')
    body = f'''
    <section class="card panel-accent page-lead loading-glow">
      <div class="panel-top">
        <div>
          <div class="eyebrow">STATS MODULE</div>
          <h2>解析统计</h2>
        </div>
        <a class="btn secondary" href="/admin">返回仪表盘</a>
      </div>
      <p class="kv">这里仅处理统计查看。若需切换到配置、用户或状态模块，请先返回仪表盘。</p>
    </section>
    <div class="grid two admin-grid">
      <section class="card loading-glow">
        <div class="eyebrow">SUMMARY</div>
        <h2>按用户汇总</h2>
        <div class="table-shell"><div class="table-wrap">
          <table class="table responsive-table"><thead><tr><th>用户</th><th>总次数</th><th>成功</th><th>失败</th></tr></thead><tbody>{''.join(summary_rows) or '<tr><td colspan="4">暂无数据</td></tr>'}</tbody></table>
        </div></div>
      </section>
      <section class="card loading-glow">
        <div class="eyebrow">BREAKDOWN</div>
        <h2>按模块明细 {html.escape(selected_user) if selected_user else ''}</h2>
        <div class="table-shell"><div class="table-wrap">
          <table class="table responsive-table"><thead><tr><th>模块</th><th>总次数</th><th>成功</th><th>失败</th></tr></thead><tbody>{''.join(breakdown_rows) or '<tr><td colspan="4">请选择左侧用户</td></tr>'}</tbody></table>
        </div></div>
      </section>
    </div>
    <section class="card loading-glow" style="margin-top:18px;">
      <div class="eyebrow">RECENT LOGS</div>
      <h2>最近解析记录</h2>
      <div class="table-shell"><div class="table-wrap">
        <table class="table responsive-table"><thead><tr><th>用户</th><th>模块</th><th>方法</th><th>成功</th><th>歌曲ID</th><th>错误</th><th>时间</th></tr></thead><tbody>{''.join(recent_rows) or '<tr><td colspan="7">暂无记录</td></tr>'}</tbody></table>
      </div></div>
    </section>
    '''
    return _admin_page('解析统计', body)


async def admin_health_page(request):
    _require_admin(request)
    rows = module_health.get_cached_module_health()
    body = f'''
    <section class="card panel-accent page-lead loading-glow">
      <div class="panel-top">
        <div>
          <div class="eyebrow">HEALTH MODULE</div>
          <h2>模块健康状态</h2>
        </div>
        <div class="actions"><a class="btn" href="/admin/health/refresh">立即刷新</a><a class="btn secondary" href="/admin">返回仪表盘</a></div>
      </div>
      <p class="kv">后台会展示完整模块列表，包括首页隐藏的已关闭模块。</p>
    </section>
    <section class="card panel-accent loading-glow">
      <div class="grid three">{_render_status_cards(rows)}</div>
    </section>
    '''
    return _admin_page('模块状态管理', body)


async def admin_health_refresh(request):
    _require_admin(request)
    await module_health.refresh_module_health()
    raise web.HTTPFound('/admin/health')


async def admin_admins_page(request):
    _require_admin(request)
    rows = []
    for admin in admin_auth.list_admins():
        rows.append(f'''
        <article class="card compact-card admin-card loading-glow">
          <div class="eyebrow">ADMIN ACCOUNT</div>
          <h3>{html.escape(admin['username'])}</h3>
          <p class="kv">创建时间: {_format_admin_time(admin['created_at'])}</p>
          <p class="kv">最近登录: {_format_admin_time(admin['last_login_at'])}</p>
          <form method="post" action="/admin/admins/password">
            <input type="hidden" name="admin_id" value="{admin['id']}">
            <div class="row"><label>新密码</label><input name="new_password" type="password" required></div>
            <div class="row"><label>确认新密码</label><input name="confirm_password" type="password" required></div>
            <button type="submit">更新密码</button>
          </form>
        </article>
        ''')
    body = f'''
    <section class="card panel-accent page-lead loading-glow">
      <div class="panel-top">
        <div>
          <div class="eyebrow">ADMIN MODULE</div>
          <h2>管理员密码管理</h2>
        </div>
        <a class="btn secondary" href="/admin">返回仪表盘</a>
      </div>
      <p class="kv">这里用于维护管理员账户密码。当前页面只处理管理员认证信息，不与其他后台模块混用。</p>
    </section>
    <section class="grid two admin-grid">{''.join(rows) or '<div class="card"><p>暂无管理员账号。</p></div>'}</section>
    '''
    return _admin_page('管理员密码', body)


async def admin_admin_password_save(request):
    _require_admin(request)
    data = await request.post()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()
    admin_id = data.get('admin_id', '').strip()
    try:
        if not admin_id:
            raise ValueError('管理员编号缺失')
        if new_password != confirm_password:
            raise ValueError('两次输入的密码不一致')
        admin_auth.update_admin_password(int(admin_id), new_password)
        body = '<div class="notice">管理员密码已更新。</div>'
    except Exception as e:
        body = f'<div class="notice error">保存失败: {html.escape(str(e))}</div>'
    body += _dashboard_back_actions('/admin/admins')
    return _admin_page('管理员密码更新结果', body)


def register_routes(app):
    app.router.add_static('/static/', './webui/static', show_index=False)
    app.router.add_get('/', home)
    app.router.add_get('/api/webui/module-health', module_health_api)
    app.router.add_post('/download-link', generate_download_link)
    app.router.add_get('/admin/login', admin_login_page)
    app.router.add_post('/admin/login', admin_login)
    app.router.add_get('/admin/logout', admin_logout)
    app.router.add_get('/admin', admin_dashboard)
    app.router.add_get('/admin/config', admin_config_page)
    app.router.add_post('/admin/config', admin_config_save)
    app.router.add_get('/admin/config/reload', admin_config_reload)
    app.router.add_get('/admin/users', admin_users_page)
    app.router.add_post('/admin/users/create', admin_user_create)
    app.router.add_post('/admin/users/delete', admin_user_delete)
    app.router.add_get('/admin/stats', admin_stats_page)
    app.router.add_get('/admin/health', admin_health_page)
    app.router.add_get('/admin/health/refresh', admin_health_refresh)
    app.router.add_get('/admin/admins', admin_admins_page)
    app.router.add_post('/admin/admins/password', admin_admin_password_save)
