import time

from common import db


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
