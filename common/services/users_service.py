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
