import asyncio
import time

from common import Httpx, config, db


MODULE_PROBES = {
    'kg': 'https://gateway.kugou.com',
    'tx': 'https://u.y.qq.com',
    'wy': 'https://interface.music.163.com',
    'mg': 'https://m.music.migu.cn',
    'kw': 'https://bd-api.kuwo.cn',
}

REQUIRED_FIELDS = {
    'kg': [('module.kg.user.token', 'token'), ('module.kg.user.userid', 'userid')],
    'tx': [('module.tx.user.qqmusic_key', 'qqmusic_key'), ('module.tx.user.uin', 'uin')],
    'wy': [('module.wy.user.cookie', 'cookie')],
    'mg': [('module.mg.user.by', 'by'), ('module.mg.user.session', 'session')],
    'kw': [('module.kw.user.uid', 'uid'), ('module.kw.user.token', 'token'), ('module.kw.user.device_id', 'device_id')],
}

AUTO_REFRESH_SECONDS = 120


async def _probe_source(source: str):
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
        return {'source': source, 'status': 'healthy', 'detail': f'探测成功({req.status})'}
    except Exception as e:
        return {'source': source, 'status': 'degraded', 'detail': str(e)}


async def refresh_module_health():
    results = []
    for source in ['kg', 'tx', 'wy', 'mg', 'kw']:
        result = await _probe_source(source)
        results.append(result)
    conn = db.get_connection()
    try:
        now = int(time.time())
        for item in results:
            conn.execute(
                '''INSERT INTO module_health (source, status, detail, checked_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET
                     status = excluded.status,
                     detail = excluded.detail,
                     checked_at = excluded.checked_at''',
                (item['source'], item['status'], item['detail'], now),
            )
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
            'SELECT source, status, detail, checked_at FROM module_health ORDER BY source ASC'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
