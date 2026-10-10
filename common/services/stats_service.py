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


def get_summary():
    conn = db.get_connection()
    try:
        rows = conn.execute(
            '''SELECT username,
                      COUNT(*) AS total,
                      SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                      SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count
               FROM parse_logs
               WHERE username IS NOT NULL
               GROUP BY username
               ORDER BY total DESC, username ASC'''
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_user_breakdown(username: str):
    conn = db.get_connection()
    try:
        rows = conn.execute(
            '''SELECT source,
                      COUNT(*) AS total,
                      SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                      SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count
               FROM parse_logs
               WHERE username = ?
               GROUP BY source
               ORDER BY total DESC, source ASC''',
            (username,),
        ).fetchall()
        return [dict(row) for row in rows]
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
