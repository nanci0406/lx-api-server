import time

from common import config, db, log, scheduler

logger = log.log('stats_service')


async def record_parse_async(*args):
    """在线程池里写入解析记录；统计写失败不能影响接口本身的返回"""
    try:
        await db.run_in_db_thread(record_parse, *args)
    except Exception as e:
        logger.warning(f'写入解析统计失败: {e}')


def cleanup_old_logs(retention_days: int) -> int:
    """删除 retention_days 天之前的解析记录，返回删除条数"""
    cutoff = int(time.time()) - int(retention_days) * 86400
    conn = db.get_connection()
    try:
        cursor = conn.execute('DELETE FROM parse_logs WHERE created_at < ?', (cutoff,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


async def cleanup_task():
    days = config.read_config('common.parse_log_retention_days')
    if not days or int(days) <= 0:
        return
    deleted = await db.run_in_db_thread(cleanup_old_logs, days)
    if deleted:
        logger.info(f'已清理 {deleted} 条超过 {days} 天的解析记录')


def register_tasks():
    """注册解析记录定时清理任务(每天一次)；保留天数为 0 或负数表示不清理"""
    days = config.read_config('common.parse_log_retention_days')
    if days and int(days) > 0:
        scheduler.append('parse_logs_cleanup', cleanup_task, 86400)


def record_parse(user, source, method, song_id, quality, success, error_message, client_ip):
    conn = db.get_connection()
    try:
        conn.execute(
            '''INSERT INTO parse_logs (
                user_id, username, source, method, song_id, quality, success, error_message, client_ip, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                user.get('id') if user else None,
                user.get('name') if user else None,
                source,
                method,
                song_id,
                quality,
                1 if success else 0,
                error_message,
                client_ip,
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_logs(limit: int = 50):
    conn = db.get_connection()
    try:
        rows = conn.execute(
            '''SELECT username, source, method, song_id, quality, success, error_message, client_ip, created_at
               FROM parse_logs
               ORDER BY created_at DESC
               LIMIT ?''',
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _filters(since=None, username=None, source=None, success=None):
    clauses, params = [], []
    if since is not None:
        clauses.append('created_at >= ?')
        params.append(int(since))
    if username:
        clauses.append('username = ?')
        params.append(username)
    if source:
        clauses.append('source = ?')
        params.append(source)
    if success is not None:
        clauses.append('success = ?')
        params.append(1 if success else 0)
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', params


def get_overview(since: int):
    """since 时间戳之后的统计：总数/成功/失败/活跃用户、按天、按音源、按用户"""
    where, params = _filters(since)
    conn = db.get_connection()
    try:
        totals = dict(conn.execute(
            f'''SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success,
                       COUNT(DISTINCT username) AS users
                FROM parse_logs{where}''', params).fetchone())
        totals['failure'] = totals['total'] - totals['success']
        daily = [dict(row) for row in conn.execute(
            f'''SELECT strftime('%Y-%m-%d', created_at, 'unixepoch', 'localtime') AS day,
                       COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success
                FROM parse_logs{where} GROUP BY day ORDER BY day ASC''', params)]
        by_source = [dict(row) for row in conn.execute(
            f'''SELECT source, COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success
                FROM parse_logs{where} GROUP BY source ORDER BY total DESC''', params)]
        by_user = [dict(row) for row in conn.execute(
            f'''SELECT COALESCE(username, '') AS username, COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success,
                       MAX(created_at) AS last_at
                FROM parse_logs{where} GROUP BY username ORDER BY total DESC LIMIT 50''', params)]
        return {'totals': totals, 'daily': daily, 'by_source': by_source, 'by_user': by_user}
    finally:
        conn.close()


def query_logs(limit=50, offset=0, username=None, source=None, success=None):
    """分页查询解析记录，返回 (记录列表, 总数)"""
    where, params = _filters(None, username, source, success)
    conn = db.get_connection()
    try:
        total = conn.execute(f'SELECT COUNT(*) FROM parse_logs{where}', params).fetchone()[0]
        rows = conn.execute(
            f'''SELECT id, username, source, method, song_id, quality, success, error_message, client_ip, created_at
                FROM parse_logs{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?''',
            params + [int(limit), int(offset)]).fetchall()
        return [dict(row) for row in rows], total
    finally:
        conn.close()
