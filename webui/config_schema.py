# ----------------------------------------
# - mode: python -
# - name: config_schema.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 后台"配置"页可编辑的配置项：分组、类型、说明、取值范围，以及值的校验与转换。
# 这里没有列出的配置(如 cookie 池)可以在后台的"原始配置"里直接编辑 config.yml。

import math
import re

QUALITY_OPTIONS = {
    'kg': ['128k', '320k', 'flac', 'flac24bit', 'master'],
    'tx': ['128k', '320k', 'flac', 'flac24bit', 'dolby', 'master'],
    'wy': ['128k', '192k', '320k', 'flac', 'flac24bit', 'dolby', 'sky', 'master'],
}

SOURCE_NAMES = {'tx': 'QQ 音乐', 'kg': '酷狗音乐', 'wy': '网易云音乐'}

REFRESH_INTERVAL = {'type': 'int', 'min': 600, 'max': 30 * 86400, 'unit': '秒'}

SECTIONS = [
    {
        'id': 'service', 'title': '服务', 'icon': 'server',
        'description': '监听地址、反向代理、出站代理等服务基础设置。',
        'fields': [
            {'key': 'common.hosts', 'label': '监听地址', 'type': 'list', 'restart': True,
             'placeholder': '0.0.0.0', 'help': '回车添加。监听 IPv6 可添加 ::'},
            {'key': 'common.ports', 'label': '监听端口', 'type': 'int_list', 'restart': True, 'min': 1, 'max': 65535,
             'placeholder': '9763'},
            {'key': 'common.ssl_info.is_https', 'label': '对外使用 HTTPS', 'type': 'bool',
             'help': '通过 HTTPS 反向代理访问时打开：后台 Cookie 会加上 Secure，生成的音源脚本使用 https 地址'},
            {'key': 'common.reverse_proxy.allow_proxy', 'label': '信任反向代理传来的真实 IP', 'type': 'bool'},
            {'key': 'common.reverse_proxy.real_ip_header', 'depends': 'common.reverse_proxy.allow_proxy',
             'label': '真实 IP 请求头', 'type': 'text',
             'placeholder': 'X-Real-IP'},
            {'key': 'common.reverse_proxy.allow_public_ip', 'depends': 'common.reverse_proxy.allow_proxy',
             'label': '允许来自公网的代理转发', 'type': 'bool',
             'help': '只有反向代理和本服务不在同一内网时才需要打开'},
            {'key': 'common.proxy.enable', 'label': '出站请求使用代理', 'type': 'bool'},
            {'key': 'common.proxy.http_value', 'depends': 'common.proxy.enable', 'label': 'HTTP 代理地址', 'type': 'text',
             'placeholder': 'http://127.0.0.1:7890'},
            {'key': 'common.proxy.https_value', 'depends': 'common.proxy.enable',
             'label': 'HTTPS 代理地址', 'type': 'text',
             'placeholder': 'http://127.0.0.1:7890'},
            {'key': 'common.cookiepool', 'label': '启用账号池(cookie 池)', 'type': 'bool',
             'help': '开启后各平台使用 module.cookiepool 里的多个账号，单账号配置会被忽略。账号池可在“原始配置”里编辑，'
                     'QQ 音乐和网易云账号也可以在“音乐账号”页扫码后直接加入'},
            {'key': 'common.debug_mode', 'label': '调试日志', 'type': 'bool', 'restart': True},
            {'key': 'common.log_length_limit', 'label': '单条日志最大长度', 'type': 'int', 'min': 50, 'max': 100000},
            {'key': 'common.parse_log_retention_days', 'label': '解析记录保留天数', 'type': 'int', 'min': 0, 'max': 3650,
             'unit': '天', 'help': '超过天数的解析记录每天自动清理，0 表示永久保留'},
        ],
    },
    {
        'id': 'security', 'title': '安全', 'icon': 'shield',
        'description': '接口鉴权、限速、封禁与后台防护。',
        'fields': [
            {'key': 'security.key.enable', 'label': '接口需要用户 Key', 'type': 'bool',
             'help': '关闭后任何人都可以调用解析接口，不建议关闭'},
            {'key': 'security.rate_limit.global', 'label': '全局请求间隔', 'type': 'number', 'min': 0, 'max': 3600,
             'unit': '秒', 'help': '两次解析请求之间的最小间隔，0 表示不限制'},
            {'key': 'security.rate_limit.ip', 'label': '单个 IP 请求间隔', 'type': 'number', 'min': 0, 'max': 3600,
             'unit': '秒'},
            {'key': 'security.banlist.enable', 'label': '启用 IP 封禁', 'type': 'bool'},
            {'key': 'security.banlist.expire.enable', 'depends': 'security.banlist.enable',
             'label': '封禁自动到期', 'type': 'bool'},
            {'key': 'security.banlist.expire.length', 'depends': 'security.banlist.expire.enable',
             'label': '封禁时长', 'type': 'int', 'min': 60,
             'max': 10 * 365 * 86400, 'unit': '秒'},
            {'key': 'security.allowed_host.enable', 'label': '只允许指定的 Host 访问', 'type': 'bool'},
            {'key': 'security.allowed_host.list', 'depends': 'security.allowed_host.enable',
             'label': '允许的 Host', 'type': 'list', 'placeholder': 'music.example.com'},
            {'key': 'security.allowed_host.blacklist.enable', 'depends': 'security.allowed_host.enable',
             'label': 'Host 不匹配时封禁来源 IP', 'type': 'bool'},
            {'key': 'security.allowed_host.blacklist.length', 'depends': 'security.allowed_host.blacklist.enable',
             'label': 'Host 不匹配的封禁时长', 'type': 'int', 'min': 0,
             'max': 10 * 365 * 86400, 'unit': '秒', 'help': '0 表示永久封禁'},
            {'key': 'security.admin_origin_check', 'label': '后台请求来源校验', 'type': 'bool',
             'help': '防跨站请求伪造。反向代理改写了 Host 导致后台无法保存时可以关闭'},
        ],
    },
    {
        'id': 'script', 'title': '音源脚本', 'icon': 'code',
        'description': '用户通过 /script?key=… 下载的 LX Music 自定义音源脚本。',
        'fields': [
            {'key': 'common.allow_download_script', 'label': '允许下载音源脚本', 'type': 'bool', 'restart': True},
            {'key': 'common.download_config.name', 'label': '脚本名称', 'type': 'text'},
            {'key': 'common.download_config.intro', 'label': '脚本简介', 'type': 'text'},
            {'key': 'common.download_config.author', 'label': '作者', 'type': 'text'},
            {'key': 'common.download_config.version', 'label': '版本号', 'type': 'text'},
            {'key': 'common.download_config.filename', 'label': '下载文件名', 'type': 'text',
             'placeholder': 'lx-music-source.js'},
            {'key': 'common.download_config.dev', 'label': '开发模式(输出调试日志)', 'type': 'bool'},
            {'key': 'common.download_config.update', 'label': '检查脚本更新', 'type': 'bool'},
            {'key': 'common.download_config.updateMsg', 'depends': 'common.download_config.update',
             'label': '更新提示文字', 'type': 'textarea',
             'help': '可用 {updateUrl}(带 key 的更新地址)、{url}、{key}'},
        ] + [
            {'key': f'common.download_config.quality.{source}', 'label': f'{name}可用音质', 'type': 'multi',
             'options': QUALITY_OPTIONS[source]}
            for source, name in SOURCE_NAMES.items()
        ],
    },
    {
        'id': 'tx', 'title': 'QQ 音乐', 'icon': 'music',
        'description': '账号凭证推荐通过“音乐账号”页扫码获取，会自动填写下面的字段。',
        'fields': [
            {'key': 'module.tx.enable', 'label': '启用 QQ 音乐', 'type': 'bool'},
            {'key': 'module.tx.user.uin', 'label': 'uin(QQ 号)', 'type': 'text'},
            {'key': 'module.tx.user.qqmusic_key', 'label': 'qqmusic_key', 'type': 'secret'},
            {'key': 'module.tx.user.login_type', 'label': '登录方式', 'type': 'select',
             'options': [['', '按 key 前缀判断'], ['1', '微信'], ['2', 'QQ']]},
            {'key': 'module.tx.user.refresh_key', 'label': 'refresh_key', 'type': 'secret'},
            {'key': 'module.tx.user.refresh_token', 'label': 'refresh_token', 'type': 'secret'},
            {'key': 'module.tx.user.openid', 'label': 'openid', 'type': 'secret'},
            {'key': 'module.tx.user.access_token', 'label': 'access_token', 'type': 'secret'},
            {'key': 'module.tx.user.unionid', 'label': 'unionid', 'type': 'secret'},
            {'key': 'module.tx.user.refresh_login.enable', 'label': '自动刷新登录', 'type': 'bool'},
            dict(REFRESH_INTERVAL, key='module.tx.user.refresh_login.interval', label='刷新间隔',
                 depends='module.tx.user.refresh_login.enable'),
            {'key': 'module.tx.cdnaddr', 'label': '下载 CDN 地址', 'type': 'text',
             'placeholder': 'http://ws.stream.qqmusic.qq.com/'},
            {'key': 'module.tx.vkey_api.use_vkey_api', 'label': '使用第三方 vkey 接口', 'type': 'bool'},
            {'key': 'module.tx.vkey_api.vkey_api_url', 'depends': 'module.tx.vkey_api.use_vkey_api',
             'label': '第三方 vkey 接口地址', 'type': 'text'},
        ],
    },
    {
        'id': 'kg', 'title': '酷狗音乐', 'icon': 'music',
        'description': '账号信息需要抓包获取(/v5/url 请求)。',
        'fields': [
            {'key': 'module.kg.enable', 'label': '启用酷狗音乐', 'type': 'bool'},
            {'key': 'module.kg.user.userid', 'label': 'userid', 'type': 'text'},
            {'key': 'module.kg.user.token', 'label': 'token', 'type': 'secret'},
            {'key': 'module.kg.user.mid', 'label': 'mid', 'type': 'text'},
            {'key': 'module.kg.client.appid', 'label': '客户端类型(appid)', 'type': 'select', 'restart': True,
             'options': [['1005', '安卓 (1005)'], ['3116', '概念版 (3116)'], ['1001', 'PC (1001)']],
             'help': '自动刷新登录只支持 1005 和 3116；3116 需要同时修改签名 key(在原始配置中)'},
            {'key': 'module.kg.user.refresh_login.enable', 'label': '自动刷新登录(token 保活)', 'type': 'bool',
             'help': 'token 30 天不刷新会失效'},
            dict(REFRESH_INTERVAL, key='module.kg.user.refresh_login.interval', label='刷新间隔',
                 depends='module.kg.user.refresh_login.enable'),
            {'key': 'module.kg.user.refresh_login.login_url', 'depends': 'module.kg.user.refresh_login.enable',
             'label': '刷新登录接口', 'type': 'text'},
            {'key': 'module.kg.user.lite_sign_in.enable', 'label': '概念版自动签到', 'type': 'bool',
             'help': '仅 appid 为 3116 时生效'},
            dict(REFRESH_INTERVAL, key='module.kg.user.lite_sign_in.interval', label='签到间隔',
                 depends='module.kg.user.lite_sign_in.enable'),
        ],
    },
    {
        'id': 'wy', 'title': '网易云音乐', 'icon': 'music',
        'description': '推荐在“音乐账号”页用网易云音乐 App 扫码登录，会自动填写 Cookie；也可以从浏览器复制完整 Cookie。',
        'fields': [
            {'key': 'module.wy.enable', 'label': '启用网易云音乐', 'type': 'bool'},
            {'key': 'module.wy.user.cookie', 'label': 'Cookie', 'type': 'secret', 'multiline': True},
            {'key': 'module.wy.user.refresh_login.enable', 'label': '自动刷新登录', 'type': 'bool',
             'help': '刷新成功后服务端返回的新 Cookie 会自动写回'},
            dict(REFRESH_INTERVAL, key='module.wy.user.refresh_login.interval', label='刷新间隔',
                 depends='module.wy.user.refresh_login.enable'),
        ],
    },
    {
        'id': 'local', 'title': '本地音乐', 'icon': 'folder',
        'description': '服务器上的本地音乐目录。',
        'fields': [
            {'key': 'common.local_music.audio_path', 'label': '音乐目录', 'type': 'text', 'restart': True},
            {'key': 'common.local_music.temp_path', 'label': '临时目录', 'type': 'text', 'restart': True},
        ],
    },
]

FIELDS = {field['key']: field for section in SECTIONS for field in section['fields']}

MAX_TEXT = 4000
MAX_SECRET = 16000


class ValidationError(ValueError):
    pass


def secret_preview(value):
    value = '' if value is None else str(value)
    if not value:
        return {'set': False, 'preview': ''}
    tail = value[-4:] if len(value) > 8 else ''
    return {'set': True, 'preview': tail}


def public_value(field, value):
    """返回给前端的值：密钥类只告诉前端"是否已设置"和末尾几位"""
    kind = field['type']
    if kind == 'secret':
        return secret_preview(value)
    if kind == 'bool':
        return bool(value)
    if kind in ('list', 'int_list', 'multi'):
        return list(value) if isinstance(value, (list, tuple)) else []
    if kind in ('int', 'number'):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    return '' if value is None else str(value)


def _number(field, value, integer):
    if isinstance(value, bool):
        raise ValidationError('需要数字')
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValidationError('不能为空')
    try:
        number = int(value) if integer else float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError('需要整数' if integer else '需要数字')
    if not math.isfinite(number):
        raise ValidationError('需要数字')
    if integer and isinstance(value, float) and value != int(value):
        raise ValidationError('需要整数')
    if not integer and number == int(number):
        number = int(number)
    if 'min' in field and number < field['min']:
        raise ValidationError(f"不能小于 {field['min']}")
    if 'max' in field and number > field['max']:
        raise ValidationError(f"不能大于 {field['max']}")
    return number


def convert(field, value):
    """把前端提交的值校验并转换成写入配置的值；不合法时抛出 ValidationError"""
    kind = field['type']
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValidationError('需要开关值')
        return value
    if kind == 'int':
        return _number(field, value, True)
    if kind == 'number':
        return _number(field, value, False)
    if kind in ('text', 'textarea', 'secret'):
        if not isinstance(value, str):
            raise ValidationError('需要文本')
        limit = MAX_SECRET if kind == 'secret' else MAX_TEXT
        if len(value) > limit:
            raise ValidationError('内容太长')
        if kind == 'text' and ('\n' in value or '\r' in value):
            raise ValidationError('不能包含换行')
        return value.strip() if kind != 'textarea' else value
    if kind == 'select':
        options = [option[0] for option in field['options']]
        if not isinstance(value, str) or value not in options:
            raise ValidationError('不是可选的值')
        return value
    if kind in ('list', 'int_list', 'multi'):
        if not isinstance(value, list):
            raise ValidationError('需要列表')
        if len(value) > 200:
            raise ValidationError('条目太多')
        if kind == 'multi':
            chosen = set()
            for item in value:
                if item not in field['options']:
                    raise ValidationError(f'未知的选项: {item}')
                chosen.add(item)
            return [option for option in field['options'] if option in chosen]
        result = []
        for item in value:
            if kind == 'int_list':
                item = _number(field, item, True)
            else:
                if not isinstance(item, str):
                    raise ValidationError('需要文本')
                item = item.strip()
                if not item:
                    continue
                if len(item) > 500 or re.search(r'\s', item):
                    raise ValidationError(f'无效的条目: {item[:30]}')
            if item not in result:
                result.append(item)
        return result
    raise ValidationError('不支持的类型')
