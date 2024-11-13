# ----------------------------------------
# - mode: python - 
# - author: helloplhm-qwq - 
# - name: utils.py - 
# - project: lx-music-api-server - 
# - license: MIT - 
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

import hashlib
import platform
import binascii
import builtins
import base64
import zlib
import time
import re
import xmltodict
import ipaddress
from urllib.parse import quote, unquote, urlparse
from typing import Union

def createBase64Encode(data_bytes):
    encoded_data = base64.b64encode(data_bytes)
    return encoded_data.decode('utf-8')

def createHexEncode(data_bytes):
    hex_encoded = binascii.hexlify(data_bytes)
    return hex_encoded.decode('utf-8')

def createBase64Decode(data):
    decoded_data = base64.b64decode(data)
    return decoded_data

def createHexDecode(data):
    decoded_data = binascii.unhexlify(data.decode('utf-8'))
    return decoded_data

def handleInflateRawSync(data):
    decompress_obj = zlib.decompressobj(-zlib.MAX_WBITS)
    decompressed_data = decompress_obj.decompress(data) + decompress_obj.flush()
    return decompressed_data

def require(module):
    index = 0
    module_array = module.split('.')
    for m in module_array:
        if index == 0:
            _module = __import__(m)
            index += 1
        else:
            _module = getattr(_module, m)
            index += 1
    return _module

def setGlobal(obj, key = ''):
    setattr(builtins, obj.__name__ if (not key) else key, obj)

def filterFileName(filename):
    if platform.system() == 'Windows' or platform.system() == 'Cygwin':
        # Windows不合法文件名字符
        illegal_chars = r'[<>:"/\\|?*\x00-\x1f]'
    else:
        # 不合法文件名字符
        illegal_chars = r'[/\x00-\x1f]'
    # 将不合法字符替换为下划线
    return re.sub(illegal_chars, '_', filename)

def createMD5(s: Union[str, bytes]):
    if (isinstance(s, str)):
        s = s.encode("utf-8")
    return hashlib.md5(s).hexdigest()

def createFileMD5(path):
    with open(path, 'rb') as f:
        md5 = hashlib.md5()
        for chunk in iter(lambda: f.read(4096), b""):
            md5.update(chunk)
        return md5.hexdigest()

def readFile(path, mode = "text"):
    try:
        fileObj = open(path, "rb")
    except FileNotFoundError:
        return "file not found"
    content = fileObj.read()
    if mode == "base64":
        return createBase64Encode(content)
    elif mode == "hex":
        return createHexEncode(content)
    elif mode == "text":
        return content.decode("utf-8")
    else:
        return "unsupported mode"

def unique_list(list_in):
    unique_list = []
    [unique_list.append(x) for x in list_in if x not in unique_list]
    return unique_list

def encodeURIComponent(component):
    if (isinstance(component, str)):
        component = component.encode('utf-8')
    elif (not isinstance(component, bytes)):
        raise TypeError('component must be str or bytes')
    return quote(component)

def decodeURIComponent(component):
    return unquote(component)

def encodeURI(uri):
    parse_result = urlparse(uri)
    params = {}
    for q in parse_result.query.split('&'):
        k, v = q.split('=')
        v = encodeURIComponent(v)
        params[k] = v
    query = '&'.join([f'{k}={v}' for k, v in params.items()])
    return parse_result._replace(query=query).geturl()

def decodeURI(uri):
    parse_result = urlparse(uri)
    params = {}
    for q in parse_result.query.split('&'):
        k, v = q.split('=')
        v = decodeURIComponent(v)
        params[k] = v
    query = '&'.join([f'{k}={v}' for k, v in params.items()])
    return parse_result._replace(query=query).geturl()

def sortDict(dictionary):
    sorted_items = sorted(dictionary.items())
    sorted_dict = {k: v for k, v in sorted_items}
    return sorted_dict

def mergeDict(dict1, dict2):
    merged_dict = dict2.copy()
    merged_dict.update(dict1)
    return merged_dict

class CreateObject(dict):
    def __init__(self, d):
        super().__init__(d)
        self._raw = d
        for key, value in d.items():
            if isinstance(value, dict):
                setattr(self, key, CreateObject(value))
            else:
                setattr(self, key, value)

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key != "_raw":
            self._raw[key] = value

    def to_dict(self):
        result = {}
        for key, value in self.items():
            if isinstance(value, CreateObject):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result

    def __getattr__(self, UNUSED):
        return None

def dump_xml(data):
    return xmltodict.unparse(data)

def load_xml(data):
    return xmltodict.parse(data)

def sizeFormat(size):
    if size < 1024:
        return f"{size}B"
    elif size < 1024**2:
        return f"{round(size / 1024, 2)}KB"
    elif size < 1024**3:
        return f"{round(size / 1024**2, 2)}MB"
    elif size < 1024**4:
        return f"{round(size / 1024**3, 2)}GB"
    elif size < 1024**5:
        return f"{round(size / 1024**4, 2)}TB"
    else:
        return f"{round(size / 1024**5, 2)}PB"

def timeLengthFormat(t):
    try:
        t = int(t)
    except:
        return '//'
    hour = t // 3600
    minute = (t % 3600) // 60
    second = t % 60
    return f"{((('0' + str(hour)) if (len(str(hour)) == 1) else str(hour)) + ':') if (hour > 0) else ''}{minute:02}:{second:02}"

def timestamp_format(t):
    if (not isinstance(t, int)):
        t = int(t)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))

def is_local_ip(ip):
    try:
        i = ipaddress.ip_address(ip)
        return i.is_private
    except:
        return False

setGlobal(require)