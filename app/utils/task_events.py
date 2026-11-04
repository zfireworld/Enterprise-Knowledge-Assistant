"""在后台线程和异步 SSE 连接之间传递任务状态变化。"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any


class TaskEvents:
    """按任务广播状态变更；订阅者只保存一次待处理通知。"""

    def __init__(self) -> None:
        """初始化线程安全的订阅表。"""
        self._lock = threading.Lock()
        self._listeners: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[None]]]] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue[None]:
        """注册当前事件循环的订阅者并返回通知队列。"""
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        with self._lock:
            self._listeners.setdefault(task_id, set()).add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[None]) -> None:
        """移除订阅者，避免断线后累积队列。"""
        loop = asyncio.get_running_loop()
        with self._lock:
            listeners = self._listeners.get(task_id, set())
            listeners.discard((loop, queue))
            if not listeners:
                self._listeners.pop(task_id, None)

    def notify(self, task_id: str) -> None:
        """从任意线程通知当前任务订阅者；状态本身由调用方保存。"""
        with self._lock:
            listeners = tuple(self._listeners.get(task_id, ()))
        for loop, queue in listeners:
            try:
                loop.call_soon_threadsafe(self._signal, queue)
            except RuntimeError:
                continue  # 连接关闭时事件循环可能已退出。

    @staticmethod
    def _signal(queue: asyncio.Queue[None]) -> None:
        """合并尚未处理的通知，避免慢客户端占用无限内存。"""
        if not queue.full():
            queue.put_nowait(None)


task_events = TaskEvents()


async def task_event_stream(task_id: str, snapshot: Callable[[str], dict[str, Any] | None],
                            events: TaskEvents = task_events) -> AsyncIterator[str]:
    """先发送当前快照，再推送变化；完成或失败后关闭连接。"""
    queue = events.subscribe(task_id)
    last_payload = ""
    try:
        while True:
            current = snapshot(task_id)
            if current is None:
                yield 'event: missing\ndata: {"detail":"任务不存在或服务已重启"}\n\n'
                return
            payload = json.dumps(current, ensure_ascii=False)
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if current.get("status") in {"completed", "failed"}:
                return
            try:
                await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        events.unsubscribe(task_id, queue)
