import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time

from .log import log


logger = log('app_db')
DB_PATH = './app.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# 密码哈希：加盐 + scrypt(OpenSSL 不支持 scrypt 时退回 PBKDF2-HMAC-SHA256)。
# 存储格式 "算法$参数...$盐(base64)$哈希(base64)"，便于以后调整参数；
# 旧版本存的是无盐 sha256 十六进制串，仍可校验，登录成功后会自动升级。
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
PBKDF2_ITERATIONS = 600000


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    raw = password.encode('utf-8')
    if hasattr(hashlib, 'scrypt'):
        try:
            digest = hashlib.scrypt(raw, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
            return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}'
        except (ValueError, MemoryError):
            pass  # 当前 OpenSSL 限制了内存，退回 PBKDF2
    digest = hashlib.pbkdf2_hmac('sha256', raw, salt, PBKDF2_ITERATIONS, dklen=32)
    return f'pbkdf2${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}'


def verify_password(password: str, stored: str):
    """
    校验密码

    @return: (是否匹配, 是否需要升级哈希)
    """
    raw = password.encode('utf-8')
    stored = stored or ''
    try:
        if stored.startswith('scrypt$'):
            _, n, r, p, salt, digest = stored.split('$')
            expected = base64.b64decode(digest)
            actual = hashlib.scrypt(raw, salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
            return hmac.compare_digest(actual, expected), False
        if stored.startswith('pbkdf2$'):
            _, iterations, salt, digest = stored.split('$')
            expected = base64.b64decode(digest)
            actual = hashlib.pbkdf2_hmac('sha256', raw, base64.b64decode(salt), int(iterations), dklen=len(expected))
            return hmac.compare_digest(actual, expected), False
    except (ValueError, TypeError, MemoryError):
        return False, False
    # 旧版本：无盐 sha256
    legacy = hashlib.sha256(raw).hexdigest()
    try:
        if hmac.compare_digest(legacy, stored):
            return True, True
    except TypeError:  # 存储值含非 ASCII 字符，必然不是旧版哈希
        pass
    return False, False


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
        checked_at INTEGER NOT NULL,
        admin_detail TEXT
    )''')
    # 旧版本创建的表没有 admin_detail 列(仅管理员可见的详细信息)
    columns = [row[1] for row in cursor.execute('PRAGMA table_info(module_health)').fetchall()]
    if 'admin_detail' not in columns:
        cursor.execute('ALTER TABLE module_health ADD COLUMN admin_detail TEXT')
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
    env_password = os.getenv('LX_ADMIN_PASSWORD')
    password = env_password or secrets.token_urlsafe(10)
    username = os.getenv('LX_ADMIN_USERNAME') or 'admin'
    cursor.execute(
        'INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, ?)',
        (username, hash_password(password), int(time.time())),
    )
    conn.commit()
    if env_password:
        # 密码是使用者自己指定的，不写进日志
        logger.warning(f'已创建管理员账号 {username}，密码取自环境变量 LX_ADMIN_PASSWORD')
    else:
        logger.warning(f'已创建默认管理员账号 {username}，密码：{password}')


def init_db():
    conn = get_connection()
    try:
        _create_tables(conn)
        _migrate_legacy_users(conn)
        _ensure_default_admin(conn)
    finally:
        conn.close()
