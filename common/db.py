import os
import sqlite3
import time
import secrets
import hashlib

from .log import log


logger = log('app_db')
DB_PATH = './app.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def _create_tables(conn):
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        api_key TEXT UNIQUE NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        last_used_at INTEGER
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        last_login_at INTEGER
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS parse_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        source TEXT,
        method TEXT,
        song_id TEXT,
        quality TEXT,
        success INTEGER NOT NULL,
        error_message TEXT,
        client_ip TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS module_health (
        source TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        detail TEXT,
        checked_at INTEGER NOT NULL
    )''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_parse_logs_user_time ON parse_logs(user_id, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_parse_logs_source_time ON parse_logs(source, created_at DESC)')
    conn.commit()


def _migrate_legacy_users(conn):
    if not os.path.exists('./users.db'):
        return
    cursor = conn.cursor()
    count = cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if count != 0:
        return
    legacy = sqlite3.connect('./users.db')
    try:
        legacy_cursor = legacy.cursor()
        rows = legacy_cursor.execute('SELECT name, key FROM users').fetchall()
        now = int(time.time())
        for name, api_key in rows:
            cursor.execute(
                'INSERT OR IGNORE INTO users (name, api_key, enabled, created_at) VALUES (?, ?, 1, ?)',
                (name, api_key, now),
            )
        conn.commit()
        if rows:
            logger.info(f'已迁移 {len(rows)} 个旧用户到 app.db')
    except sqlite3.Error:
        logger.warning('迁移旧 users.db 失败，已忽略')
    finally:
        legacy.close()


def _ensure_default_admin(conn):
    cursor = conn.cursor()
    row = cursor.execute('SELECT COUNT(*) FROM admins').fetchone()
    if row[0] != 0:
        return
    password = os.getenv('LX_ADMIN_PASSWORD') or secrets.token_urlsafe(10)
    username = os.getenv('LX_ADMIN_USERNAME') or 'admin'
    cursor.execute(
        'INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, ?)',
        (username, hash_password(password), int(time.time())),
    )
    conn.commit()
    logger.warning(f'已创建默认管理员账号 {username}，密码：{password}')


def init_db():
    conn = get_connection()
    try:
        _create_tables(conn)
        _migrate_legacy_users(conn)
        _ensure_default_admin(conn)
    finally:
        conn.close()
