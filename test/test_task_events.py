"""验证导入进度 SSE 的状态、线程通知及断线清理。"""

import asyncio
import json
import unittest

from fastapi.testclient import TestClient

from app.knowledge import web_api
from app.utils.task_events import TaskEvents, task_event_stream


def event_data(event: str) -> dict:
    """读取 SSE 消息中的 JSON 数据。"""
    return json.loads(next(line[6:] for line in event.splitlines() if line.startswith("data: ")))


class TaskEventTests(unittest.IsolatedAsyncioTestCase):
    """验证独立订阅者和后台线程之间的状态传递。"""

    async def test_updates_and_terminal_state_from_thread(self) -> None:
        """订阅后状态由后台线程更新，结束事件后自动释放订阅。"""
        events = TaskEvents()
        task = {"status": "pending"}
        stream = task_event_stream("a", lambda _: task.copy(), events)
        self.assertEqual(event_data(await anext(stream))["status"], "pending")

        def update() -> None:
            """模拟同步后台线程更新状态并通知。"""
            task.update(status="processing", step="解析")
            events.notify("a")

        await asyncio.to_thread(update)
        self.assertEqual(event_data(await asyncio.wait_for(anext(stream), 1))["step"], "解析")
        task.update(status="completed")
        events.notify("a")
        self.assertEqual(event_data(await asyncio.wait_for(anext(stream), 1))["status"], "completed")
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)
        self.assertFalse(events._listeners)

    async def test_late_subscriber_and_failed_task(self) -> None:
        """任务在连接前已失败时，首次快照包含错误并结束。"""
        events = TaskEvents()
        stream = task_event_stream("a", lambda _: {"status": "failed", "error": "写入失败"}, events)
        self.assertEqual(event_data(await anext(stream))["error"], "写入失败")
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)
        self.assertFalse(events._listeners)

    async def test_multiple_subscribers_and_disconnect(self) -> None:
        """同一任务两个连接独立接收通知，断开时释放订阅。"""
        events = TaskEvents()
        task = {"status": "processing"}
        first = task_event_stream("a", lambda _: task.copy(), events)
        second = task_event_stream("a", lambda _: task.copy(), events)
        await anext(first)
        await anext(second)
        task["status"] = "completed"
        await asyncio.to_thread(events.notify, "a")
        self.assertEqual(event_data(await asyncio.wait_for(anext(first), 1))["status"], "completed")
        self.assertEqual(event_data(await asyncio.wait_for(anext(second), 1))["status"], "completed")
        await first.aclose()
        await second.aclose()
        self.assertFalse(events._listeners)


class TaskEventsApiTests(unittest.TestCase):
    """验证网页 SSE 接口的初始快照和不存在任务。"""

    def test_completed_task_and_missing_task(self) -> None:
        """连接已完成的任务立即返回最终事件；未知任务返回 404。"""
        task_id = "test-completed-sse"
        web_api.importer.tasks[task_id] = {"id": task_id, "status": "completed", "chunks": 1}
        try:
            client = TestClient(web_api.app)
            response = client.get(f"/api/import/{task_id}/events")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
            self.assertEqual(event_data(response.text)["status"], "completed")
            self.assertEqual(client.get("/api/import/missing-sse/events").status_code, 404)
        finally:
            web_api.importer.tasks.pop(task_id, None)


if __name__ == "__main__":
    unittest.main()
