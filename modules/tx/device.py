# ----------------------------------------
# - mode: python -
# - name: device.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.
#
# 模拟一台安卓手机的设备信息，用于 QQ 音乐手机验证码登录时构造请求里的 comm 字段。
# 字段设计参考 MIT 许可的 MeoProject/lx-music-api-server (utils/platform/tx/device.py)。

import binascii
import hashlib
import json
import os
import random
import string
import time
from dataclasses import asdict, dataclass, field
from uuid import uuid4

DEVICE_PATH = './config/tx_device.json'

# 获取到的 QIMEI 缓存多久(秒)，过期后重新获取
QIMEI_CACHE_SECONDS = 24 * 3600


def random_imei() -> str:
    """生成带校验位的随机 IMEI"""
    digits = []
    total = 0
    for i in range(14):
        num = random.randint(0, 9)
        if (i + 2) % 2 == 0:
            num *= 2
            if num >= 10:
                num = (num % 10) + 1
        total += num
        digits.append(str(num))
    digits.append(str((total * 9) % 10))
    return ''.join(digits)


@dataclass
class OSVersion:
    incremental: str = '5891938'
    release: str = '10'
    codename: str = 'REL'
    sdk: int = 29


@dataclass
class Device:
    display: str = field(default_factory=lambda: f'QMAPI.{random.randint(100000, 999999)}.001')
    product: str = 'iarim'
    device: str = 'sagit'
    board: str = 'eomam'
    model: str = 'MI 6'
    fingerprint: str = field(
        default_factory=lambda: f'xiaomi/iarim/sagit:10/eomam.200122.001/{random.randint(1000000, 9999999)}:user/release-keys')
    boot_id: str = field(default_factory=lambda: str(uuid4()))
    proc_version: str = field(
        default_factory=lambda: 'Linux 5.4.0-54-generic-' + ''.join(
            random.choices(string.ascii_letters + string.digits, k=8)) + ' (android-build@google.com)')
    imei: str = field(default_factory=random_imei)
    brand: str = 'Xiaomi'
    android_id: str = field(default_factory=lambda: binascii.hexlify(os.urandom(8)).decode())
    open_udid: str = field(default_factory=lambda: hashlib.md5(os.urandom(16)).hexdigest())
    version: OSVersion = field(default_factory=OSVersion)
    # 申请到的 QIMEI(q16/q36)及其获取时间
    qimei: dict = field(default_factory=dict)
    qimei_time: int = 0

    def qimei_fresh(self, now=None) -> bool:
        now = time.time() if now is None else now
        return bool(self.qimei.get('q36')) and now - self.qimei_time < QIMEI_CACHE_SECONDS


def load_device(path: str = None) -> Device:
    """读取保存的设备信息；文件不存在或损坏时生成一台新的并保存"""
    path = path or DEVICE_PATH
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['version'] = OSVersion(**data['version'])
        return Device(**data)
    except (OSError, ValueError, TypeError, KeyError):
        device = Device()
        save_device(device, path)
        return device


def save_device(device: Device, path: str = None):
    path = path or DEVICE_PATH
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(asdict(device), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
