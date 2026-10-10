import asyncio
import time

from common import Httpx, config, db, scheduler, utils


MODULE_PROBES = {
    'kg': 'https://gateway.kugou.com',
    'tx': 'https://u.y.qq.com',
    'wy': 'https://interface.music.163.com',
}

REQUIRED_FIELDS = {
    'kg': [('module.kg.user.token', 'token'), ('module.kg.user.userid', 'userid')],
    'tx': [('module.tx.user.qqmusic_key', 'qqmusic_key'), ('module.tx.user.uin', 'uin')],
    'wy': [('module.wy.user.cookie', 'cookie')],
}

# 各音源登录保活类定时任务的名称前缀，用于把任务失败反映到模块状态上
SOURCE_TASK_PREFIXES = {
    'tx': ('qqmusic_refresh_login',),
    'kg': ('kg_refresh_login', 'kgmusic_refresh_login', 'kugou_lite_sign_in'),
    'wy': ('wy_refresh_login',),
}

SOURCES = list(MODULE_PROBES)

AUTO_REFRESH_SECONDS = 120


def _task_issues(source):
    """返回该音源已注册的定时任务里连续失败的任务描述(仅管理员可见)"""
    prefixes = SOURCE_TASK_PREFIXES.get(source, ())
    issues = []
    for task in scheduler.get_status():
        if not task['name'].startswith(prefixes) or not task['consecutive_failures']:
            continue
        text = f"{task['name']} 已连续失败 {task['consecutive_failures']} 次"
        if task['last_failure_at']:
            text += f"，最近一次 {utils.timestamp_format(task['last_failure_at'])}"
        if task['next_run']:
            text += f"，下次重试 {utils.timestamp_format(task['next_run'])}"
        if task['last_error']:
            text += f"({task['last_error']})"
        issues.append(text)
    return issues


async def _tx_credential_issue(force):
    """检查 QQ 音乐账号登录凭证，有问题时返回描述(仅管理员可见)，正常返回 None"""
    from modules.tx import credential
    summary = await credential.check_all(force)
    if summary['invalid']:
        return f"{summary['invalid']}/{summary['total']} 个账号登录凭证已失效，需要重新获取 qqmusic_key"
    return None


async def _probe_source(source: str, force: bool = False):
    enabled = config.read_config(f'module.{source}.enable')
    if not enabled:
        return {'source': source, 'status': 'disabled', 'detail': '模块已关闭'}
    missing = []
    for key, label in REQUIRED_FIELDS.get(source, []):
        value = config.read_config(key)
        if value in (None, '', '0'):
            missing.append(label)
    if missing:
        return {'source': source, 'status': 'misconfigured', 'detail': '缺少: ' + ', '.join(missing)}
    try:
        req = await Httpx.AsyncRequest(MODULE_PROBES[source], {'method': 'GET', 'cache': 120})
        if req.status >= 500:
            raise RuntimeError(f'bad status {req.status}')
    except Exception as e:
        return {'source': source, 'status': 'degraded', 'detail': str(e)}

    result = {'source': source, 'status': 'healthy', 'detail': f'探测成功({req.status})'}
    # 域名可达不代表账号可用：登录保活任务失败、凭证失效时也要体现出来。
    # detail 会展示在公开首页上，只写笼统描述；具体账号信息放进 admin_detail，仅管理员可见
    admin_issues = _task_issues(source)
    public_issues = ['账号刷新登录异常'] if admin_issues else []
    if source == 'tx':
        try:
            issue = await _tx_credential_issue(force)
        except Exception:
            issue = None
        if issue:
            admin_issues.append(issue)
            public_issues.append('账号登录状态异常')
    if admin_issues:
        result['status'] = 'degraded'
        result['detail'] = '；'.join(public_issues)
        result['admin_detail'] = '；'.join(admin_issues)
    return result


async def refresh_module_health(force: bool = False):
    results = []
    for source in SOURCES:
        result = await _probe_source(source, force)
        results.append(result)
    conn = db.get_connection()
    try:
        now = int(time.time())
        for item in results:
            conn.execute(
                '''INSERT INTO module_health (source, status, detail, checked_at, admin_detail)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET
                     status = excluded.status,
                     detail = excluded.detail,
                     checked_at = excluded.checked_at,
                     admin_detail = excluded.admin_detail''',
                (item['source'], item['status'], item['detail'], now, item.get('admin_detail')),
            )
        # 已下线的音源(如咪咕、酷我)留下的旧记录不再展示
        placeholders = ','.join('?' * len(SOURCES))
        conn.execute(f'DELETE FROM module_health WHERE source NOT IN ({placeholders})', SOURCES)
        conn.commit()
    finally:
        conn.close()
    return results


async def auto_refresh_loop():
    while True:
        try:
            await refresh_module_health()
        except Exception:
            pass
        await asyncio.sleep(AUTO_REFRESH_SECONDS)


def get_cached_module_health():
    conn = db.get_connection()
    try:
        rows = conn.execute(
            'SELECT source, status, detail, checked_at, admin_detail FROM module_health ORDER BY source ASC'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
