# ----------------------------------------
# - mode: python -
# - author: helloplhm-qwq -
# - name: lx.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

from . import Httpx
from . import config
from . import scheduler
from .log import log
from aiohttp.web import Response
import ujson as json
import re
import sqlite3
from common.utils import createMD5
import os

logger = log('lx_script')

jsd_mirror_list = [
    'https://cdn.jsdelivr.net',
    'https://gcore.jsdelivr.net',
    'https://fastly.jsdelivr.net',
    'https://jsd.cdn.zzko.cn',
    'https://jsdelivr.b-cdn.net',
]
github_raw_mirror_list = [
    'https://raw.githubusercontent.com',
    'https://mirror.ghproxy.com/https://raw.githubusercontent.com',
    'https://ghraw.gkcoll.xyz',
    'https://raw.fgit.mxtrans.net',
    'https://github.moeyy.xyz/https://raw.githubusercontent.com',
    'https://raw.fgit.cf',
]

async def get_response(retry=0):
    if retry > 21:
        logger.warning('请求源脚本内容失败')
        return
    baseurl = '/nanci0406/Linux_Tools/main/lx-music-source-example.js'
    jsdbaseurl = '/gh/nanci0406/Linux_Tools@main/lx-music-source-example.js'
    try:
        i = retry
        if i > 10:
            i = i - 11
        if i < 5:
            req = await Httpx.AsyncRequest(jsd_mirror_list[retry] + jsdbaseurl)
        elif i < 11:
            req = await Httpx.AsyncRequest(github_raw_mirror_list[retry - 5] + baseurl)
        if not req.text.startswith('/*!'):
            logger.info('疑似请求到了无效的内容，忽略')
            raise Exception from None
    except Exception as e:
        if isinstance(e, RuntimeError) and 'Session is closed' in str(e):
            logger.error('脚本更新失败，clientSession已被关闭')
            return
        return await get_response(retry + 1)
    return req

async def get_script():
    req = await get_response()
    if req.status == 200:
        with open('./lx-music-source-example.js', 'w', encoding='utf-8') as f:
            f.write(req.text)
        logger.info('更新源脚本成功')
    else:
        logger.warning('请求源脚本内容失败')

async def generate_script_response(request):
    # 从请求中获取 key
    request_key = request.query.get('key')
    logger.info(f"尝试使用 key: {request_key} 验证用户")  # 日志记录 key

    if not request_key:
        return {'code': 6, 'msg': 'key验证失败', 'data': None}, 403

    # 连接到 SQLite 数据库并查询 key 和对应的 user
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM users WHERE key = ?", (request_key,))
        result = cursor.fetchone()
        conn.close()

        logger.info(f"查询结果: {result}")  # 记录查询结果
    except sqlite3.Error as e:
        logger.error(f"数据库错误: {e}")  # 记录数据库错误
        return {'code': 4, 'msg': '数据库错误', 'data': None}, 500

    # 如果数据库中找不到 key，返回 403 错误
    if not result:
        logger.warning(f"未找到对应的用户，key: {request_key}")  # 记录未找到用户的情况
        return {'code': 6, 'msg': 'key验证失败', 'data': None}, 403

    db_user = result[0]  # 获取数据库中的 user 值
    #

    # key 验证通过，执行脚本生成逻辑
    try:
        with open('./lx-music-source-example.js', 'r', encoding='utf-8') as f:
            script = f.read()
    except FileNotFoundError:
        return {'code': 4, 'msg': '本地无源脚本', 'data': None}, 400

    # 处理脚本内容
    script_lines = script.split('\n')
    new_script_lines = []
    for line in script_lines:
        oline = line
        line = line.strip()
        if line.startswith('const API_URL'):
            new_script_lines.append(f'const API_URL = "{ "https" if config.read_config("common.ssl_info.is_https") else "http" }://{request.host}"')
        elif line.startswith('const API_KEY'):
            new_script_lines.append(f'const API_KEY = `{request_key}`')
        elif line.startswith('const USER_NAME'):  # 确保填充 USER_NAME
            new_script_lines.append(f'const USER_NAME = `{db_user}`')
        elif line.startswith("* @name"):
            new_script_lines.append(" * @name " + config.read_config("common.download_config.name"))
        elif line.startswith("* @description"):
            new_script_lines.append(" * @description " + config.read_config("common.download_config.intro"))
        elif line.startswith("* @author"):
            new_script_lines.append(" * @author " + config.read_config("common.download_config.author"))
        elif line.startswith("* @version"):
            new_script_lines.append(" * @version " + config.read_config("common.download_config.version"))
        elif line.startswith("const DEV_ENABLE "):
            new_script_lines.append("const DEV_ENABLE = " + str(config.read_config("common.download_config.dev")).lower())
        elif line.startswith("const UPDATE_ENABLE "):
            new_script_lines.append("const UPDATE_ENABLE = " + str(config.read_config("common.download_config.update")).lower())
        else:
            new_script_lines.append(oline)

    r = '\n'.join(new_script_lines)
    r = re.sub(r'const MUSIC_QUALITY = {[^}]+}', f'const MUSIC_QUALITY = JSON.parse(\'{json.dumps(config.read_config("common.download_config.quality"))}\')', r)

    # 用于检查更新
    if config.read_config("common.download_config.update"):
        md5 = createMD5(r)
        r = r.replace(r"const SCRIPT_MD5 = ''", f"const SCRIPT_MD5 = '{md5}'")
        if request.query.get('checkUpdate'):
            if request.query.get('checkUpdate') == md5:
                return {'code': 0, 'msg': 'success', 'data': None}, 200
            url = f"{'https' if config.read_config('common.ssl_info.is_https') else 'http'}://{request.host}/script"
            update_url = f"{url}{('?key=' + request_key) if request_key else ''}"
            update_msg = config.read_config('common.download_config.updateMsg').format(updateUrl=update_url, url=url, key=request_key).replace('\\n', '\n')
            return {'code': 0, 'msg': 'success', 'data': {'updateMsg': update_msg, 'updateUrl': update_url}}, 200

    return Response(text=r, content_type='text/javascript',
                    headers={
                        'Content-Disposition': f'''attachment; filename={
                            config.read_config("common.download_config.filename")
                            if config.read_config("common.download_config.filename").endswith(".js")
                            else (config.read_config("common.download_config.filename") + ".js")}'''
                    })