import _env  # noqa: F401

import asyncio
import unittest
from unittest import mock

from common import scheduler


class FakeTime:
    def __init__(self, now=1_000_000):
        self.now = now

    def time(self):
        return self.now


class SchedulerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        scheduler.clear()
        scheduler._states.clear()
        self.clock = FakeTime()
        patcher = mock.patch.object(scheduler, 'time', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(scheduler.clear)

    def task(self, name='t', interval=1000, results=None):
        results = list(results or [None])
        calls = []

        async def fn():
            calls.append(self.clock.now)
            result = results.pop(0) if len(results) > 1 else results[0]
            if isinstance(result, Exception):
                raise result
            return result

        scheduler.append(name, fn, interval)
        return scheduler.tasks[-1], calls

    async def test_first_run_is_immediate_and_success_waits_full_interval(self):
        t, calls = self.task(interval=1000)
        self.assertTrue(t.check_available())
        await t.run()
        self.assertEqual(len(calls), 1)
        self.assertEqual(t.state.next_run, self.clock.now + 1000)
        self.assertFalse(t.check_available())
        self.clock.now += 1000
        self.assertTrue(t.check_available())

    async def test_failures_back_off_and_are_capped_by_interval(self):
        t, _ = self.task(interval=100000, results=[RuntimeError('boom')])
        expected = [60, 300, 1800, 7200, 7200]
        for index, delay in enumerate(expected, start=1):
            await t.run()
            self.assertEqual(t.state.consecutive_failures, index)
            self.assertEqual(t.state.next_run, self.clock.now + delay)
            self.assertEqual(t.state.last_error, 'boom')
        # 重试间隔不会超过任务自身的执行间隔
        capped, _ = self.task(name='short', interval=30, results=[RuntimeError('x')])
        await capped.run()
        self.assertEqual(capped.state.next_run, self.clock.now + 30)

    async def test_returning_false_is_a_failure_and_success_resets(self):
        t, _ = self.task(interval=1000, results=[False, None])
        await t.run()
        self.assertEqual(t.state.consecutive_failures, 1)
        self.assertIsNotNone(t.state.last_failure_at)
        self.clock.now += 60
        self.assertTrue(t.check_available())
        await t.run()
        self.assertEqual(t.state.consecutive_failures, 0)
        self.assertIsNone(t.state.last_error)
        self.assertEqual(t.state.next_run, self.clock.now + 1000)

    async def test_reregistering_keeps_state_and_does_not_rerun_immediately(self):
        t, _ = self.task(name='keep', interval=1000)
        await t.run()
        scheduler.clear()  # 配置热重载：清空后重新注册同名任务
        t2, _ = self.task(name='keep', interval=1000)
        self.assertFalse(t2.check_available())
        self.assertIs(t.state, t2.state)

    async def test_reregistering_applies_new_interval(self):
        t, _ = self.task(name='iv', interval=1000)
        await t.run()
        scheduler.clear()
        t2, _ = self.task(name='iv', interval=10)
        self.clock.now += 10
        self.assertTrue(t2.check_available())

    async def test_retry_schedule_survives_reregistering(self):
        t, _ = self.task(name='retry', interval=1000, results=[RuntimeError('boom')])
        await t.run()
        next_run = t.state.next_run
        scheduler.clear()
        t2, _ = self.task(name='retry', interval=1000)
        self.assertEqual(t2.state.next_run, next_run)
        self.assertEqual(t2.state.consecutive_failures, 1)

    async def test_running_task_is_not_available(self):
        t, _ = self.task()
        t.state.running = True
        self.assertFalse(t.check_available())

    async def test_get_status_lists_registered_tasks(self):
        t, _ = self.task(name='status')
        await t.run()
        status = scheduler.get_status()
        self.assertEqual([s['name'] for s in status], ['status'])
        self.assertEqual(status[0]['consecutive_failures'], 0)
        self.assertEqual(status[0]['last_success_at'], self.clock.now)

    async def test_runner_runs_tasks_without_blocking_each_other(self):
        gate = asyncio.Event()
        done = []

        async def slow():
            await gate.wait()

        async def fast():
            done.append('fast')

        scheduler.append('slow', slow, 1000)
        scheduler.append('fast', fast, 1000)
        runner = asyncio.create_task(scheduler.thread_runner())
        try:
            for _ in range(50):
                if done:
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(done, ['fast'])  # slow 还卡着，fast 照样执行
        finally:
            scheduler.running_event.set()
            gate.set()
            await asyncio.wait_for(runner, 5)
            scheduler.running_event.clear()


if __name__ == '__main__':
    unittest.main()
