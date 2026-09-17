"""导出文件定时清理服务"""

import asyncio
import pathlib
import time
from typing import Optional

EXPORT_DIR = pathlib.Path(__file__).parent.parent / "data" / "exports"
MAX_AGE_SECONDS = 24 * 3600  # 24 小时后清理
CLEANUP_INTERVAL = 3600       # 每小时检查一次

_cleanup_task: Optional[asyncio.Task] = None


async def _cleanup():
    """清理过期导出文件。"""
    export_dir = EXPORT_DIR
    if not export_dir.exists():
        return
    now = time.time()
    removed = 0
    for f in export_dir.iterdir():
        if f.is_file():
            try:
                if now - f.stat().st_mtime > MAX_AGE_SECONDS:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    if removed:
        from logging_config import get_logger
        get_logger(__name__).info("清理了 %d 个过期导出文件", removed)


async def _cleanup_loop():
    """后台清理循环。"""
    from logging_config import get_logger
    logger = get_logger(__name__)
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            await _cleanup()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"导出文件清理失败: {e}")


def start_cleanup_scheduler():
    """启动后台清理任务。在 lifespan 中调用，返回 task 以便取消。"""
    global _cleanup_task
    _cleanup_task = asyncio.create_task(_cleanup_loop())


async def stop_cleanup_scheduler():
    """停止后台清理任务。在 lifespan 中用 yield 后的清理阶段调用。"""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None
