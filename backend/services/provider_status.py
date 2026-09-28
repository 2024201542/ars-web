"""最近一次模型厂商返回的错误，供对话引擎及时停下来告诉用户。"""

import time

from typing import Optional

_last = {"at": 0.0, "status": 0, "message": ""}


def note(status: int, message: str) -> None:
    _last["at"] = time.time()
    _last["status"] = int(status or 0)
    _last["message"] = (message or "")[:400]


def since(started_at: float) -> Optional[dict]:
    if _last["at"] < started_at or not _last["status"]:
        return None
    return dict(_last)
