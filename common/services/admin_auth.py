import secrets
import time

from common import variable
from common import db


COOKIE_NAME = 'lx_admin_session'


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    variable.admin_sessions[token] = {
        'username': username,
        'created_at': int(time.time()),
    }
    return token


def get_session(request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return variable.admin_sessions.get(token)


def destroy_session(request):
    token = request.cookies.get(COOKIE_NAME)
    if token and token in variable.admin_sessions:
        variable.admin_sessions.pop(token, None)


def authenticate_admin(username: str, password: str):
    conn = db.get_connection()
    try:
        row = conn.execute(
            'SELECT username, password_hash FROM admins WHERE username = ?',
            (username,),
        ).fetchone()
        if not row:
            return False
        return row['password_hash'] == db.hash_password(password)
    finally:
        conn.close()


def list_admins():
    conn = db.get_connection()
    try:
        rows = conn.execute(
            'SELECT id, username, created_at, last_login_at FROM admins ORDER BY id ASC'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_admin_password(admin_id: int, new_password: str):
    password = new_password.strip()
    if not password:
        raise ValueError('新密码不能为空')
    conn = db.get_connection()
    try:
        row = conn.execute('SELECT id FROM admins WHERE id = ?', (admin_id,)).fetchone()
        if not row:
            raise ValueError('管理员不存在')
        conn.execute(
            'UPDATE admins SET password_hash = ? WHERE id = ?',
            (db.hash_password(password), admin_id),
        )
        conn.commit()
    finally:
        conn.close()
