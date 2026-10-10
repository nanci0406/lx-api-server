import secrets
import time

from common import variable
from common import db


COOKIE_NAME = 'lx_admin_session'

# 会话有效期：连续 SESSION_IDLE_SECONDS 无操作，或登录满 SESSION_MAX_SECONDS 后需要重新登录
SESSION_IDLE_SECONDS = 4 * 3600
SESSION_MAX_SECONDS = 24 * 3600

# 登录失败限制：同一 IP 在 LOGIN_WINDOW_SECONDS 内失败 LOGIN_MAX_FAILURES 次后暂时拒绝登录
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60

MIN_PASSWORD_LENGTH = 8

_login_failures = {}

# 用户不存在时也做一次哈希校验，避免通过响应时间判断用户名是否存在
_DUMMY_HASH = None


def _session_expired(session, now):
    return (now - session['created_at'] > SESSION_MAX_SECONDS
            or now - session.get('last_seen', session['created_at']) > SESSION_IDLE_SECONDS)


def _purge_expired_sessions(now):
    for token in [t for t, s in variable.admin_sessions.items() if _session_expired(s, now)]:
        variable.admin_sessions.pop(token, None)


def create_session(username: str) -> str:
    now = int(time.time())
    _purge_expired_sessions(now)
    token = secrets.token_urlsafe(32)
    variable.admin_sessions[token] = {
        'username': username,
        'created_at': now,
        'last_seen': now,
    }
    return token


def get_session(request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    session = variable.admin_sessions.get(token)
    if not session:
        return None
    now = int(time.time())
    if _session_expired(session, now):
        variable.admin_sessions.pop(token, None)
        return None
    session['last_seen'] = now
    return session


def destroy_session(request):
    token = request.cookies.get(COOKIE_NAME)
    if token and token in variable.admin_sessions:
        variable.admin_sessions.pop(token, None)


def destroy_other_sessions(username: str, keep_token: str = None):
    """让某个管理员除 keep_token 之外的所有会话失效(例如改密码之后)"""
    for token in [t for t, s in variable.admin_sessions.items()
                  if s['username'] == username and t != keep_token]:
        variable.admin_sessions.pop(token, None)


def login_blocked(client_ip: str, now: float = None) -> bool:
    """该 IP 近期登录失败次数过多时返回 True"""
    now = time.time() if now is None else now
    recent = [t for t in _login_failures.get(client_ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    if recent:
        _login_failures[client_ip] = recent
    else:
        _login_failures.pop(client_ip, None)
    return len(recent) >= LOGIN_MAX_FAILURES


def record_login_failure(client_ip: str, now: float = None):
    now = time.time() if now is None else now
    # 顺手清理其他 IP 已过期的记录，避免字典无限增长
    for ip in [ip for ip, times in _login_failures.items() if all(now - t >= LOGIN_WINDOW_SECONDS for t in times)]:
        _login_failures.pop(ip, None)
    _login_failures.setdefault(client_ip, []).append(now)


def clear_login_failures(client_ip: str):
    _login_failures.pop(client_ip, None)


def authenticate_admin(username: str, password: str):
    global _DUMMY_HASH
    conn = db.get_connection()
    try:
        row = conn.execute(
            'SELECT id, username, password_hash FROM admins WHERE username = ?',
            (username,),
        ).fetchone()
        if not row:
            if _DUMMY_HASH is None:
                _DUMMY_HASH = db.hash_password(secrets.token_urlsafe(16))
            db.verify_password(password, _DUMMY_HASH)
            return False
        matched, needs_upgrade = db.verify_password(password, row['password_hash'])
        if not matched:
            return False
        if needs_upgrade:
            conn.execute('UPDATE admins SET password_hash = ? WHERE id = ?',
                         (db.hash_password(password), row['id']))
        conn.execute('UPDATE admins SET last_login_at = ? WHERE id = ?', (int(time.time()), row['id']))
        conn.commit()
        return True
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
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'新密码至少需要 {MIN_PASSWORD_LENGTH} 位')
    conn = db.get_connection()
    try:
        row = conn.execute('SELECT id, username FROM admins WHERE id = ?', (admin_id,)).fetchone()
        if not row:
            raise ValueError('管理员不存在')
        conn.execute(
            'UPDATE admins SET password_hash = ? WHERE id = ?',
            (db.hash_password(password), admin_id),
        )
        conn.commit()
        return row['username']
    finally:
        conn.close()
