import _env  # noqa: F401  必须最先导入

import os
import time
import unittest

from common import config


def read_file_value(text, key):
    for line in text.splitlines():
        if line.strip().startswith(key + ':'):
            return line.split(':', 1)[1].strip().strip("'\"")
    return None


class WriteConfigTest(unittest.TestCase):
    def test_write_config_updates_memory_and_file(self):
        config.write_config('module.tx.user.qqmusic_key', 'OLD')
        config.write_config('module.tx.user.qqmusic_key', 'NEW')
        self.assertEqual(config.read_config('module.tx.user.qqmusic_key'), 'NEW')
        self.assertIn('NEW', config.read_config_text())

    def test_batch_writes_all_keys_atomically(self):
        config.write_config_batch({
            'module.tx.user.refresh_key': 'RK',
            'module.tx.user.refresh_token': 'RT',
        })
        self.assertEqual(config.read_config('module.tx.user.refresh_key'), 'RK')
        self.assertEqual(config.read_config('module.tx.user.refresh_token'), 'RT')
        text = config.read_config_text()
        self.assertIn('RK', text)
        self.assertIn('RT', text)
        self.assertFalse(os.path.exists('./config/config.yml.tmp'))

    def test_batch_without_memory_sync_only_touches_file(self):
        config.write_config('module.tx.user.openid', 'MEM')
        config.write_config_batch({'module.tx.user.openid': 'FILE_ONLY'}, sync_memory=False)
        self.assertEqual(config.read_config('module.tx.user.openid'), 'MEM')
        self.assertIn('FILE_ONLY', config.read_config_text())
        # 热重载后读取到文件中的值
        config.reload_config()
        self.assertEqual(config.read_config('module.tx.user.openid'), 'FILE_ONLY')


class BanListTest(unittest.TestCase):
    def setUp(self):
        config.write_data('banList', [])
        config.write_data('banListRaw', [])

    def test_ban_expires_at_end_timestamp(self):
        config.ban_ip('10.0.0.1', 3600)
        entry = config.read_data('banList')[0]
        self.assertTrue(entry['expire'])
        self.assertAlmostEqual(entry['expire_time'], time.time() + 3600, delta=5)
        self.assertTrue(config.check_ip_banned('10.0.0.1'))

    def test_other_ips_entries_do_not_hide_a_ban(self):
        config.ban_ip('10.0.0.2', 3600)
        config.ban_ip('10.0.0.3', 3600)
        self.assertTrue(config.check_ip_banned('10.0.0.3'))
        self.assertTrue(config.check_ip_banned('10.0.0.2'))
        self.assertFalse(config.check_ip_banned('10.0.0.4'))

    def test_expired_ban_is_removed(self):
        config.ban_ip('10.0.0.5', 3600)
        banlist = config.read_data('banList')
        banlist[0]['expire_time'] = int(time.time()) - 1
        config.write_data('banList', banlist)
        self.assertFalse(config.check_ip_banned('10.0.0.5'))
        self.assertEqual(config.read_data('banList'), [])
        self.assertNotIn('10.0.0.5', config.read_data('banListRaw'))

    def test_non_positive_length_is_permanent(self):
        config.ban_ip('10.0.0.6', 0)
        entry = config.read_data('banList')[0]
        self.assertFalse(entry['expire'])
        self.assertTrue(config.check_ip_banned('10.0.0.6'))

    def test_one_entry_per_ip(self):
        config.ban_ip('10.0.0.7', 100)
        config.ban_ip('10.0.0.7', 200)
        self.assertEqual(len([b for b in config.read_data('banList') if b['ip'] == '10.0.0.7']), 1)


if __name__ == '__main__':
    unittest.main()
