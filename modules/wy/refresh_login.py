# ----------------------------------------
# - mode: python -
# - author: lerdb -
# - name: refresh_login.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

from common import Httpx, variable
from common import scheduler
from common import config
from common import log
from common.exceptions import FailedException
from time import time
from random import randint
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from .encrypt import eapiEncrypt
import ujson as json

logger = log.log("wy_refresh_login")


def cookieStr2Dict(cookieStr):
    cookieDict = {}
    for line in cookieStr.split(";"):
        if line.strip() == "":
            continue
        try:
            name, value = line.strip().split("=", 1)
            cookieDict[name] = value
        except:
            continue
    return cookieDict


def cookieDict2Str(cookieDict):
    cookieStr = ""
    for name, value in cookieDict.items():
        cookieStr += f"{name}={value}; "
    return cookieStr


def parseSetCookie(set_cookie_headers):
    """
    解析响应里的 Set-Cookie，返回 {名称: 值}

    已被服务端删除(值为空、Max-Age<=0)或已经过期的 cookie 会被忽略，
    否则会把还能用的登录凭证替换成无效值。
    """
    result = {}
    for line in set_cookie_headers or []:
        parts = [p.strip() for p in line.split(";")]
        if not parts or "=" not in parts[0]:
            continue
        name, value = parts[0].split("=", 1)
        name = name.strip()
        if not name or not value:
            continue
        attrs = {}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                attrs[k.strip().lower()] = v.strip()
        try:
            if int(attrs["max-age"]) <= 0:
                continue
        except (KeyError, ValueError):
            pass
        if "max-age" not in attrs and "expires" in attrs:
            try:
                expires = parsedate_to_datetime(attrs["expires"].replace("-", " ") if attrs["expires"].count("-") == 2 else attrs["expires"])
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= datetime.now(timezone.utc):
                    continue
            except (TypeError, ValueError):
                pass
        result[name] = value
    return result


def mergeCookies(cookie_str, updates):
    """把新的 cookie 合并进原来的 cookie 字符串：同名的替换，原来没有的追加，其余保持不变"""
    cookie_dict = cookieStr2Dict(cookie_str)
    cookie_dict.update(updates)
    return "; ".join(f"{name}={value}" for name, value in cookie_dict.items())


def _get_pool_cookies():
    return config.read_config("module.cookiepool.wy") or []


async def refresh(cookie: str = None, index = None):
    """
    网易云刷新登录

    刷新接口会通过 Set-Cookie 返回新的登录凭证(MUSIC_U 等)，必须写回配置，
    否则服务一直在用旧凭证，到旧凭证自己过期时登录就失效了。

    @param cookie: 网易云音乐cookie
    @param index: cookie 池模式下账号在池中的下标
    """
    if index is not None:
        cookies = _get_pool_cookies()
        if index >= len(cookies):
            logger.warning(f'网易云账号池刷新登录失败: 账号索引不存在({index})')
            return
        cookie = cookies[index].get("cookie")
    elif cookie is None:
        cookie = config.read_config("module.wy.user.cookie")
    if not cookie:
        return
    used_cookie = cookie
    cookie = cookieStr2Dict(cookie)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    }
    baseUrl = "http://interface.music.163.com/eapi/"
    path = "/api/login/token/refresh"
    header = {
        "osver": cookie.get("osver", "17.4.1"),
        "deviceId": cookie.get("deviceId",""),
        "os": cookie.get("os","ios"),
        "appver": cookie.get("appver", ("9.0.65" if cookie.get("os") != "pc" else "")),
        "versioncode": cookie.get("versioncode", "140"),
        "mobilename": cookie.get("mobilename", ""),
        "buildver": cookie.get("buildver", str(time())[:10]),
        "resolution": cookie.get("resolution", "1920x1080"),
        "__csrf": cookie.get("__csrf", ""),
        "channel": cookie.get("channel", ""),
        "requestId": str(time() * 1000)[:13] + "_" + f"{randint(0, 9999):0>4}",
    }
    if cookie.get("MUSIC_U"):
        header["MUSIC_U"] = cookie.get("MUSIC_U")
    if cookie.get("MUSIC_A"):
        header["MUSIC_A"] = cookie.get("MUSIC_A")
    headers["Cookie"] = cookieDict2Str(header)

    req = await Httpx.AsyncRequest(
        baseUrl + path[5:],
        {
            "method": "POST",
            "headers": headers,
            "form": eapiEncrypt(path, json.dumps({"header": header, "e_r": False})),
        }
    )
    body = req.json()
    if int(body["code"]) != 200:
        raise FailedException("网易云刷新登录失败(code: " + str(body["code"]) + ")")

    updates = parseSetCookie(req.set_cookies)
    if not updates:
        logger.warning("网易云刷新登录成功，但服务端没有返回新的 cookie，未更新配置")
        return

    # 请求期间配置可能被管理员修改，这时不能用旧 cookie 刷出来的结果覆盖
    if index is not None:
        cookies = _get_pool_cookies()
        if index >= len(cookies) or cookies[index].get("cookie") != used_cookie:
            logger.warning("网易云账号的 cookie 在刷新期间已被修改，本次刷新结果已丢弃")
            return
        cookies[index]["cookie"] = mergeCookies(used_cookie, updates)
        config.write_config("module.cookiepool.wy", cookies)
    else:
        if config.read_config("module.wy.user.cookie") != used_cookie:
            logger.warning("网易云账号的 cookie 在刷新期间已被修改，本次刷新结果已丢弃")
            return
        config.write_config("module.wy.user.cookie", mergeCookies(used_cookie, updates))
    logger.info("网易云刷新登录成功，已更新 cookie: " + ", ".join(updates))

if (variable.use_cookie_pool):
    cookies = config.read_config("module.cookiepool.wy") or []
    for index, c in enumerate(cookies):
        ref = c.get("refresh_login") if c.get("refresh_login") else {
            "enable": False,
            "interval": 86400
        }
        if (ref.get("enable")):
            scheduler.append("wy_refresh_login_pooled_" + str(index), refresh, ref.get("interval", 86400), {"index": index})
else:
    ref = config.read_config("module.wy.user.refresh_login") or {}
    if (ref.get("enable")):
        scheduler.append("wy_refresh_login", refresh, ref.get("interval", 86400))
