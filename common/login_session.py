# ----------------------------------------
# - mode: python -
# - name: login_session.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 后台扫码/验证码登录的会话管理(QQ 音乐、网易云共用)。
# 会话只保存在内存里，归发起登录的管理员所有；登录得到的凭证在点击"保存"之前不会写入配置。

import asyncio
import secrets
import time

QR_TIMEOUT = 180  # 二维码有效时间，超时后会话结束
RESULT_TTL = 600  # 登录完成后凭证在内存里最多保留多久，期间需要在后台点"保存"
MAX_ACTIVE_SESSIONS = 5  # 同时进行中的扫码登录上限


class LoginError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code


class LoginSession:
    """
    一次登录。kind 为 qq / wx / phone(QQ 音乐) 或 wy(网易云)；
    credential 是登录得到的凭证，至少包含 uin(账号 ID) 和 nick(昵称)，由各平台的模块填写
    """

    def __init__(self, kind, owner):
        self.id = secrets.token_urlsafe(16)
        self.kind = kind
        self.owner = owner  # 发起登录的管理员用户名，只有本人能查看和保存
        self.created_at = time.time()
        self.finished_at = None
        self.state = 'scan'  # scan / conf / done / timeout / refuse / error / cancelled / applied
        self.message = ''
        self.credential = None
        self.image = b''
        self.mimetype = ''
        self.task = None
        self.http = None  # 扫码会话持有的 HTTP 会话，结束或取消时必须关闭

    @property
    def platform(self):
        return 'wy' if self.kind == 'wy' else 'tx'

    @property
    def finished(self):
        return self.state not in ('scan', 'conf')

    def finish(self, state, message=''):
        self.state = state
        self.message = message
        self.finished_at = time.time()

    def public(self):
        """给前端看的状态：不包含凭证本身"""
        info = {'id': self.id, 'kind': self.kind, 'platform': self.platform, 'state': self.state,
                'message': self.message}
        if self.credential:
            credential = self.credential
            has_refresh = credential.get('has_refresh')
            if has_refresh is None:
                has_refresh = bool(credential.get('refresh_key') or credential.get('refresh_token'))
            info['account'] = {'uin': credential['uin'], 'nick': credential.get('nick', ''),
                               'has_refresh': bool(has_refresh)}
        return info


_sessions = {}
_closing = set()


def stop_session(ls):
    """停止后台轮询并关闭它的 HTTP 会话。任务还没开始执行就被取消时，任务里的 finally 不会运行，所以这里要补一次关闭"""
    if ls.task and not ls.task.done():
        ls.task.cancel()
    if ls.http is not None:
        closing = asyncio.ensure_future(ls.http.close())
        _closing.add(closing)
        closing.add_done_callback(_closing.discard)
        ls.http = None


def purge(now=None):
    """清理超时的会话：扫码阶段最多 QR_TIMEOUT，完成后凭证最多保留 RESULT_TTL"""
    now = time.time() if now is None else now
    for sid, ls in list(_sessions.items()):
        expired = (now - ls.created_at > QR_TIMEOUT + RESULT_TTL) or \
                  (ls.finished_at is not None and now - ls.finished_at > RESULT_TTL)
        if expired:
            stop_session(ls)
            _sessions.pop(sid, None)


def ensure_capacity():
    purge()
    if len([s for s in _sessions.values() if not s.finished]) >= MAX_ACTIVE_SESSIONS:
        raise LoginError('同时进行的扫码登录太多，请稍后再试')


def register(ls):
    _sessions[ls.id] = ls
    return ls


def get_session(sid, owner):
    ls = _sessions.get(sid)
    if ls and ls.owner == owner:
        return ls
    return None


def cancel_session(sid, owner):
    ls = get_session(sid, owner)
    if not ls:
        return False
    stop_session(ls)
    if not ls.finished:
        ls.finish('cancelled', '已取消')
    return True
