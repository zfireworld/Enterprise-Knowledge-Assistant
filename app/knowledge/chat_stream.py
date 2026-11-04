"""以 SSE 推送知识问答进度和经过校验的最终结果。"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from app.knowledge.service import KnowledgeService


async def chat_event_stream(service: KnowledgeService, question: str,
                            history: list[dict[str, Any]]) -> AsyncIterator[str]:
    """推送决策阶段和最终结果；连接断开时取消本次问答。"""
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    def progress(data: dict[str, Any]) -> None:
        """将决策阶段加入当前连接的事件队列。"""
        queue.put_nowait(("progress", data))

    async def run() -> None:
        """执行问答并将结果或异常发送给消费者。"""
        try:
            result = await service.ask_async(question, history, on_progress=progress)
            await queue.put(("final", result))
        except Exception as exc:
            await queue.put(("failure", {"message": f"问答执行失败：{exc}"}))

    task = asyncio.create_task(run())
    try:
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if event in {"final", "failure"}:
                return
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
