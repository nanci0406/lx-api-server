"""
测试环境：项目用相对路径读写 config/、logs/、*.db，并且在 import 时就会创建它们，
所以必须在 import 项目代码之前切换到一个临时目录，避免污染仓库工作区。
每个测试模块的第一行都要 `import _env`。
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'test-admin-password'

if not os.environ.get('LX_TEST_WORKDIR'):
    workdir = tempfile.mkdtemp(prefix='lx-test-')
    os.environ['LX_TEST_WORKDIR'] = workdir
    os.environ['LX_ADMIN_USERNAME'] = ADMIN_USERNAME
    os.environ['LX_ADMIN_PASSWORD'] = ADMIN_PASSWORD
    os.chdir(workdir)
    atexit.register(shutil.rmtree, workdir, ignore_errors=True)
