# ----------------------------------------
# - mode: python -
# - author: helloplhm-qwq -
# - name: scheduler.py -
# - project: lx-music-api-server -
# - license: MIT -
# ----------------------------------------
# This file is part of the "lx-music-api-server" project.

# 一个简单的循环任务调度器
#
# 任务函数的约定：
#   - 正常返回(含返回 None)视为成功；
#   - 抛出异常，或显式返回 False 视为失败。
# 失败后不会干等一个完整周期，而是按 RETRY_DELAYS 退避重试(不超过任务自身的 interval)，
# 连续成功后恢复正常周期。任务状态按任务名保存，配置热重载重新注册任务时不会丢失，
# 也不会因为重建任务而立刻重复执行。

import time
import asyncio
import traceback
from .utils import timestamp_format
from . import log

logger = log.log("scheduler")
running_event = asyncio.Event()
tasks = []

# 连续失败后的重试间隔(秒)，超出长度后沿用最后一个值
RETRY_DELAYS = (60, 300, 1800, 7200)

# 任务状态(按任务名保存，热重载后保留)
_states = {}
# 正在执行的任务，持有强引用以免被垃圾回收
_running_tasks = set()
_runner_task = None


class TaskState:
    def __init__(self):
        self.latest_execute = 0  # 最近一次开始执行的时间
        self.next_run = 0  # 下次可执行的时间，0 表示尚未执行过，立即执行
        self.last_success_at = None
        self.last_failure_at = None
        self.last_error = None
        self.consecutive_failures = 0
        self.running = False


class taskWrapper:
    def __init__(self, name, function, interval = 86400, args = None, latest_execute = 0):
        self.function = function
        self.interval = int(interval)
        self.name = name
        self.args = args or {}
        self.state = _states.setdefault(name, TaskState())
        if latest_execute:
            self.state.latest_execute = latest_execute
        # 重新注册(如配置热重载)时按最新间隔重新计算下次执行时间；
        # 处于失败重试中的任务保持原有的重试计划
        if self.state.consecutive_failures == 0 and self.state.latest_execute:
            self.state.next_run = self.state.latest_execute + self.interval

    @property
    def latest_execute(self):
        return self.state.latest_execute

    def check_available(self):
        return (not self.state.running) and time.time() >= self.state.next_run

    async def run(self):
        state = self.state
        state.running = True
        state.latest_execute = int(time.time())
        started = state.latest_execute
        error = None
        try:
            logger.info(f"task {self.name} run start")
            result = await self.function(**self.args)
            if result is False:
                error = '任务返回失败'
        except asyncio.CancelledError:
            state.running = False
            raise
        except Exception as e:
            error = str(e) or type(e).__name__
            logger.error(traceback.format_exc())
        now = time.time()
        if error is None:
            state.consecutive_failures = 0
            state.last_success_at = now
            state.last_error = None
            state.next_run = started + self.interval
            logger.info(f'task {self.name} run success, next execute: {timestamp_format(state.next_run)}')
        else:
            state.consecutive_failures += 1
            state.last_failure_at = now
            state.last_error = error
            delay = RETRY_DELAYS[min(state.consecutive_failures - 1, len(RETRY_DELAYS) - 1)]
            state.next_run = now + min(delay, self.interval)
            logger.error(f"task {self.name} run failed ({state.consecutive_failures} in a row), "
                         f"retry at: {timestamp_format(state.next_run)}")
        state.running = False

    def __str__(self):
        return f'SchedulerTaskWrapper(name="{self.name}", interval={self.interval}, function={self.function}, args={self.args}, latest_execute={self.latest_execute})'

def append(name, task, interval = 86400, args = None):
    global tasks
    tasks = [t for t in tasks if t.name != name]
    wrapper = taskWrapper(name, task, interval, args)
    logger.debug(f"new task ({name}) registered")
    return tasks.append(wrapper)

def clear():
    # 只清空待执行列表，_states 保留以便重新注册后沿用执行记录
    global tasks
    tasks.clear()

def get_status():
    """返回当前已注册任务的运行状态，供后台展示"""
    return [{
        'name': t.name,
        'interval': t.interval,
        'running': t.state.running,
        'latest_execute': t.state.latest_execute or None,
        'next_run': t.state.next_run or None,
        'last_success_at': t.state.last_success_at,
        'last_failure_at': t.state.last_failure_at,
        'last_error': t.state.last_error,
        'consecutive_failures': t.state.consecutive_failures,
    } for t in tasks]

def run_now(name):
    """让已注册的任务在下一轮(约 1 秒内)立即执行；任务不存在或正在执行时返回 False"""
    for t in tasks:
        if t.name == name:
            if t.state.running:
                return False
            t.state.next_run = 0
            return True
    return False

def _spawn(wrapper):
    task = asyncio.ensure_future(wrapper.run())
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)

async def thread_runner():
    global tasks, running_event
    while not running_event.is_set():
        for t in list(tasks):
            if (t.check_available() and not running_event.is_set()):
                # 先标记运行中再交给事件循环，避免下一轮重复调度；各任务互不阻塞
                t.state.running = True
                _spawn(t)
        await asyncio.sleep(1)

async def run():
    global _runner_task
    logger.debug("scheduler thread starting...")
    _runner_task = asyncio.create_task(thread_runner())
    logger.info(f"scheduler loaded {len(tasks)} task(s): {', '.join([t.name for t in tasks]) if tasks else 'none'}")
    logger.debug("schedluer thread load success")
