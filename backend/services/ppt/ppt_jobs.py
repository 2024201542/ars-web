"""进程内的后台任务。同一个 key 同时只跑一个。

重启进程后登记会丢，进度以写进文件的字段为准。
"""

from __future__ import annotations

import asyncio
import time
import uuid

_jobs: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}


def start(key: str, coro_factory) -> str:
    """已有同 key 任务在跑时返回原来的 job_id。coro_factory(progress) 返回协程。"""
    current = _jobs.get(key)
    if current and current.get("status") == "running":
        return current["job_id"]
    job_id = uuid.uuid4().hex[:12]
    record = {
        "job_id": job_id,
        "status": "running",
        "done": 0,
        "total": 0,
        "current_page": 0,
        "errors": [],
        "started_at": time.time(),
    }
    _jobs[key] = record

    async def runner() -> None:
        try:
            await coro_factory(record)
            if record.get("status") == "running":
                record["status"] = "done"
        except Exception as exc:
            record["status"] = "failed"
            record["errors"].append({"page": record.get("current_page") or 0, "error": str(exc)})

    _tasks[key] = asyncio.get_running_loop().create_task(runner())
    return job_id


def status(key: str) -> dict:
    job = _jobs.get(key)
    if not job:
        return {
            "status": "none",
            "done": 0,
            "total": 0,
            "current_page": 0,
            "errors": [],
            "started_at": 0,
            "job_id": "",
        }
    return job


async def wait(key: str) -> None:
    task = _tasks.get(key)
    if task is not None:
        await task
