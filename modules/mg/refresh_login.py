# ----------------------------------------
# - mode: python - 
# - author: helloplhm-qwq - 
# - name: refresh_login.py - 
# - project: lx-music-api-server - 
# - license: MIT - 
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

from common import Httpx
from common import config
from common.exceptions import FailedException
from common import scheduler
from common import variable
from common import log

logger = log.log("migu_refresh_login")

async def do_account_refresh(user_info = None, index = None):
    if index is not None:
        users = config.read_config("module.cookiepool.mg") or []
        if index >= len(users):
            logger.warning(f'咪咕账号池刷新登录失败: 账号索引不存在({index})')
            return
        user_info = users[index]
    elif user_info is None:
        user_info = config.read_config("module.mg.user")
    if not user_info:
        return
    req = await Httpx.AsyncRequest("https://m.music.migu.cn/migumusic/h5/user/auth/userActiveNotice", {
        "method": "POST",
        "body": "",
        "headers": {
            "User-Agent": user_info["useragent"],
            "by": user_info["by"],
            "Cookie": "SESSION=" + user_info["session"],
            "Referer": "https://m.music.migu.cn/v4/my",
            "Origin": "https://m.music.migu.cn",
        },
    })

    body = req.json()

    if (int(body["code"]) != 200):
        raise FailedException("咪咕session保活失败: " + str(body["msg"]))
    return logger.info("咪咕session保活成功")

if (variable.use_cookie_pool):
    users = config.read_config("module.cookiepool.mg") or []
    for index, u in enumerate(users):
        ref = u.get("refresh_login") if u.get("refresh_login") else {
            "enable": False,
            "interval": 86400
        }
        if (ref.get("enable")):
            scheduler.append("migu_refresh_login_pooled_" + str(index), do_account_refresh, ref.get("interval", 86400), {"index": index})
else:
    ref = config.read_config("module.mg.user.refresh_login") or {}
    if (ref.get("enable")):
        scheduler.append("migu_refresh_login", do_account_refresh, ref.get("interval", 86400))
