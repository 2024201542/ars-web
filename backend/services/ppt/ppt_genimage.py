"""万相出图：没配图时按内容生成一张。

用你阿里云那把 key（DashScope 的**异步**文生图接口）：
1. POST /api/v1/services/aigc/text2image/image-synthesis（带 `X-DashScope-Async: enable`）→ 拿 task_id
2. 轮询 GET /api/v1/tasks/{task_id} → 拿图片 URL
3. 下载落盘，交给 `ppt_image` 当配图素材

注意：出图要几十秒，所以只在用户明确勾选"自动配图"时才调用。
"""

from __future__ import annotations

import asyncio
import pathlib
import uuid
from typing import Optional

import httpx

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
GENERATED_DIR = BACKEND_DIR / "generated" / "ppt_images"

SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
DEFAULT_MODEL = "wanx2.1-t2i-turbo"


def _prompt_for_title(title: str, orient: str = "landscape") -> str:
    size_hint = "横幅构图" if orient == "landscape" else "竖幅构图"
    return (
        f"为学术汇报幻灯片配一张插图，主题：{title}。"
        f"风格：简洁、扁平、克制的学术风，低饱和配色，不要出现文字与水印，{size_hint}。"
    )


async def generate_image(user_id: str, title: str, *, model: str = DEFAULT_MODEL,
                         out_path: Optional[pathlib.Path] = None,
                         size: str = "1024*1024", timeout_s: int = 120) -> tuple[Optional[pathlib.Path], str]:
    """按标题生成一张配图，返回 (文件路径, 错误信息)。"""
    from services.state_tracker import tracker

    key = (await tracker.get_setting("qwen_api_key", user_id) or "").strip()
    if not key:
        return None, "阿里云（通义千问）还没配 API Key"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "X-DashScope-Async": "enable"}
    body = {"model": model, "input": {"prompt": _prompt_for_title(title)},
            "parameters": {"size": size, "n": 1}}

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(SUBMIT_URL, json=body, headers=headers)
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        if resp.status_code != 200:
            return None, f"提交失败 HTTP {resp.status_code}: {resp.text[:160]}"
        task_id = ((resp.json().get("output") or {}).get("task_id")) or ""
        if not task_id:
            return None, f"没有拿到 task_id：{resp.text[:160]}"

        waited = 0
        while waited < timeout_s:
            await asyncio.sleep(4)
            waited += 4
            try:
                poll = await client.get(TASK_URL.format(task_id=task_id),
                                        headers={"Authorization": f"Bearer {key}"})
            except Exception:
                continue
            if poll.status_code != 200:
                continue
            out = poll.json().get("output") or {}
            status = out.get("task_status")
            if status == "SUCCEEDED":
                results = out.get("results") or []
                url = (results[0] or {}).get("url") if results else ""
                if not url:
                    return None, "任务成功但没返回图片地址"
                target = out_path or (GENERATED_DIR / f"wanx_{uuid.uuid4().hex[:8]}.png")
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    image = await client.get(url, timeout=90)
                    target.write_bytes(image.content)
                except Exception as exc:
                    return None, f"下载图片失败：{exc}"
                return target, ""
            if status in ("FAILED", "CANCELED"):
                return None, f"任务失败：{out.get('message') or status}"
    return None, f"等待超时（{timeout_s} 秒）"
