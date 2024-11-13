# ----------------------------------------
# - mode: python - 
# - author: helloplhm-qwq - 
# - name: utils.py - 
# - project: lx-music-api-server - 
# - license: MIT - 
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from common import utils
from common import config
from common import Httpx
import json

createObject = utils.CreateObject


tools = createObject({
    "signkey": config.read_config("module.kg.client.signatureKey"),
    "pidversec": config.read_config("module.kg.client.pidversionsecret"),
    "clientver": config.read_config("module.kg.client.clientver"),
    "x-router": config.read_config("module.kg.tracker.x-router"),
    "url": config.read_config("module.kg.tracker.host") + config.read_config("module.kg.tracker.path"),
    "version": config.read_config("module.kg.tracker.version"),
    "extra_params": config.read_config("module.kg.tracker.extra_params"),
    "appid": config.read_config("module.kg.client.appid"),
    'mid': config.read_config('module.kg.user.mid'),
    "pid": config.read_config("module.kg.client.pid"),
    'qualityHashMap': {
        '128k': 'hash_128',
        '320k': 'hash_320',
        'flac': 'hash_flac',
        'flac24bit': 'hash_high',
        'master': 'hash_128',
    },
    'qualityMap': {
        '128k': '128',
        '320k': '320',
        'flac': 'flac',
        'flac24bit': 'high',
        'master': 'viper_atmos',
    },
})

def buildSignatureParams(dictionary, body = ""):
    joined_str = ''.join([f'{k}={v}' for k, v in dictionary.items()])
    return joined_str + body

def buildRequestParams(dictionary: dict):
    joined_str = '&'.join([f'{k}={v}' for k, v in dictionary.items()])
    return joined_str

def sign(params, body = "", signkey = tools["signkey"]):
    if (isinstance(body, dict)):
        body = json.dumps(body)
    params = utils.sortDict(params)
    params = buildSignatureParams(params, body)
    return utils.createMD5(signkey + params + signkey)

async def signRequest(url, params, options, signkey = tools["signkey"]):
    params['signature'] = sign(params, options.get("body") if options.get("body") else (options.get("data") if options.get("data") else (options.get("json") if options.get("json") else "")), signkey)
    url = url + "?" + buildRequestParams(params)
    return await Httpx.AsyncRequest(url, options)

def getKey(hash_, user_info):
    return utils.createMD5(hash_.lower() + tools.pidversec + tools.appid + user_info['mid'] + user_info['userid'])

def aes_sign(plain_text, key=b'90b8382a1bb4ccdcf063102053fd75b8', iv=b'f063102053fd75b8'):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    crypto = cipher.encrypt(pad(plain_text.encode(), AES.block_size))
    return crypto.hex()
