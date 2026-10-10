import time

from common import db


def get_user_by_name_and_key(username: str, api_key: str):
    conn = db.get_connection()
    try:
        row = conn.execute(
            'SELECT id, name, api_key, enabled FROM users WHERE name = ? AND api_key = ?',
            (username, api_key),
        ).fetchone()
        if not row or not row['enabled']:
            return None
        conn.execute('UPDATE users SET last_used_at = ? WHERE id = ?', (int(time.time()), row['id']))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def get_user_by_key(api_key: str):
    conn = db.get_connection()
    try:
        row = conn.execute(
            'SELECT id, name, api_key, enabled FROM users WHERE api_key = ?',
            (api_key,),
        ).fetchone()
        if not row or not row['enabled']:
            return None
        conn.execute('UPDATE users SET last_used_at = ? WHERE id = ?', (int(time.time()), row['id']))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def list_users():
    conn = db.get_connection()
    try:
        rows = conn.execute(
            'SELECT id, name, api_key, enabled, created_at, last_used_at FROM users ORDER BY id ASC'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_user(name: str, api_key: str):
    conn = db.get_connection()
    try:
        conn.execute(
            'INSERT INTO users (name, api_key, enabled, created_at) VALUES (?, ?, 1, ?)',
            (name, api_key, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id: int):
    conn = db.get_connection()
    try:
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
    finally:
        conn.close()


def list_users_with_usage():
    """用户列表，附带累计解析次数与成功次数"""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            '''SELECT u.id, u.name, u.api_key, u.enabled, u.created_at, u.last_used_at,
                      COUNT(p.id) AS total,
                      COALESCE(SUM(CASE WHEN p.success = 1 THEN 1 ELSE 0 END), 0) AS success_count
               FROM users u LEFT JOIN parse_logs p ON p.user_id = u.id
               GROUP BY u.id
               ORDER BY u.id ASC'''
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_user(user_id: int):
    conn = db.get_connection()
    try:
        row = conn.execute(
            'SELECT id, name, api_key, enabled, created_at, last_used_at FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_enabled(user_id: int, enabled: bool) -> bool:
    conn = db.get_connection()
    try:
        cursor = conn.execute('UPDATE users SET enabled = ? WHERE id = ?', (1 if enabled else 0, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_api_key(user_id: int, api_key: str) -> bool:
    conn = db.get_connection()
    try:
        cursor = conn.execute('UPDATE users SET api_key = ? WHERE id = ?', (api_key, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def name_or_key_taken(name: str = None, api_key: str = None, exclude_id: int = None):
    """返回 'name' / 'api_key' 表示已被其他用户占用，否则返回 None"""
    conn = db.get_connection()
    try:
        for column, value in (('name', name), ('api_key', api_key)):
            if value is None:
                continue
            row = conn.execute(f'SELECT id FROM users WHERE {column} = ?', (value,)).fetchone()
            if row and row['id'] != exclude_id:
                return column
        return None
    finally:
        conn.close()
