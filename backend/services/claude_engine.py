"""Claude Code CLI 子进程引擎 —— 用 Claude Code 原生能力驱动 ARS 会话。

架构：
- 认证凭据通过环境变量 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL 传给子进程。
  Claude CLI 原生读取这些环境变量，完全不需要修改 ~/.claude/settings.json。
- 持久化会话：首次消息用 --session-id 创建会话，后续用 --resume 恢复。
  Claude CLI 原生管理对话历史和上下文。
- ARS 技能：--add-dir 暴露给 Claude Code，原生 /skill 调用。
- 输出：--print --verbose --output-format=stream-json 实时转发前端 SSE。

非 Anthropic 模型（DeepSeek/Kimi/GLM/Qwen）：ANTHROPIC_BASE_URL 指向本地 proxy.py，
由 proxy.py 将 Anthropic 格式翻译为 OpenAI 格式后转发到实际 Provider。
"""

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from config import ARS_SKILLS_PATH, WORKSPACE_DIR
from services.state_tracker import tracker as state_tracker


def _find_claude_bin() -> str:
    env_bin = os.environ.get("CLAUDE_BIN", "")
    if env_bin and Path(env_bin).exists():
        return env_bin
    which = shutil.which("claude")
    if which:
        return which

    candidates = [
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]

    # 扫描 nvm 安装的 Claude CLI（支持多个 Node 版本）
    nvm_dir = os.path.expanduser("~/.nvm/versions/node")
    if Path(nvm_dir).is_dir():
        try:
            for node_ver in sorted(Path(nvm_dir).iterdir(), reverse=True):
                p = node_ver / "bin" / "claude"
                if p.is_file():
                    candidates.append(str(p))
        except OSError:
            pass

    for p in candidates:
        if Path(p).exists():
            return p

    import logging
    logging.getLogger(__name__).warning("无法找到 claude CLI，请设置 CLAUDE_BIN 环境变量")
    return "claude"


CLAUDE_BIN = _find_claude_bin()


class ClaudeEngine:
    """管理 Claude CLI 子进程，提供流式对话能力。"""

    def __init__(self):
        self._active: dict[str, asyncio.subprocess.Process] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def chat(
        self,
        session_id: str,
        message: str,
        cancel_event: asyncio.Event,
        skill_name: str = "",
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        is_first: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """启动 Claude CLI 子进程对话。

        首次消息：--session-id {session_id}  创建持久会话
        后续消息：--resume {session_id}      恢复会话，Claude 原生记住上下文

        用 asyncio.Lock 确保同一会话不会并发启动多个 CLI 进程。
        """
        lock = self._get_lock(session_id)

        async with lock:
            # ── 构建命令 ──────────────────────────────────────────
            session_flag = "--session-id" if is_first else "--resume"

            # 各技能的简洁系统提示
            skill_prompts = {
                "deep-research": "你是一个学术深度研究助手。帮助用户搜索文献、分析信息、撰写研究报告。",
                "academic-paper": "你是一个学术论文撰写助手。帮助用户撰写、修改、格式化学术论文。",
                "academic-paper-reviewer": "你是一个学术论文评审助手。从多角度评审论文质量。",
                "academic-pipeline": "你是一个全流程学术研究助手。协调从研究到定稿的完整工作流。",
                "kimi-cnki-search": "你是一个中文学术文献检索助手。帮助检索 CNKI/CSSCI 等中文数据库。",
            }
            system_guide = skill_prompts.get(skill_name, "你是一个学术研究助手。")
            system_guide += (
                "请纯文本格式直接回答用户的问题，使用 Markdown 排版（标题、表格、列表可用），"
                "但绝对不要输出任何以下内容：技能列表、触发条件、路由说明、使用指南、"
                "版本号、更新日志、CLI 命令、Agent 列表、模式列表、文件路径。"
                "把用户当作学者/研究者来对话，忘记你是 AI 助手的身份。"
                "你运行在专属的工作区目录中。当用户明确要求生成或保存文件时，"
                "可以使用 Bash 工具在当前目录创建文件（cat > file, echo, tee 等）。"
                "不要把普通对话内容自动保存为文件，只在用户明确要求时才创建文件。"
            )

            # 确保工作区目录存在
            ws_dir = WORKSPACE_DIR / session_id
            ws_dir.mkdir(parents=True, exist_ok=True)

            cmd = [
                CLAUDE_BIN,
                "--bare",
                "-p",
                "--verbose",
                "--output-format", "stream-json",
                "--allowedTools", "WebSearch,WebFetch,Read,Bash",
                "--system-prompt", system_guide,
                session_flag, session_id,
                message,
                "--add-dir", str(ARS_SKILLS_PATH),
                "--add-dir", str(WORKSPACE_DIR / session_id),
            ]

            if model:
                cmd.insert(1, "--model")
                cmd.insert(2, model)

            child_env = {
                **os.environ,
                "NO_COLOR": "1",
                "TERM": "dumb",
            }
            if api_key:
                child_env["ANTHROPIC_AUTH_TOKEN"] = api_key
                child_env["ANTHROPIC_API_KEY"] = api_key
            if base_url:
                child_env["ANTHROPIC_BASE_URL"] = base_url

            # ── 启动子进程（cwd 指向工作区，Write 工具默认写入该目录） ──
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env,
                cwd=str(ws_dir),
            )
            self._active[session_id] = proc

            try:
                stdout = proc.stdout
                if stdout is None:
                    yield {"event": "error", "data": {"code": "SUBPROCESS_ERROR", "message": "子进程无 stdout"}}
                    return

                buffer = b""
                while True:
                    if cancel_event.is_set():
                        proc.terminate()
                        yield {"event": "error", "data": {"code": "STOPPED", "message": "用户中断"}}
                        return

                    try:
                        chunk = await asyncio.wait_for(stdout.read(4096), timeout=15)
                    except asyncio.TimeoutError:
                        yield {"event": "heartbeat", "data": {}}
                        continue

                    if not chunk:
                        break

                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        parsed = self._parse_event(evt)
                        if parsed:
                            yield parsed

                if buffer.strip():
                    try:
                        evt = json.loads(buffer)
                        parsed = self._parse_event(evt)
                        if parsed:
                            yield parsed
                    except json.JSONDecodeError:
                        pass

                try:
                    _, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=1)
                    if stderr_data:
                        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                        if stderr_text and "Error:" in stderr_text:
                            yield {"event": "error", "data": {"code": "CLI_ERROR", "message": stderr_text}}
                            return
                except asyncio.TimeoutError:
                    proc.terminate()

                await proc.wait()

                try:
                    await self._save_claude_response(session_id)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("jsonl fallback save failed: %s", e)
                yield {"event": "done", "data": {"message": "Claude 回应完成"}}

            except asyncio.CancelledError:
                proc.terminate()
                yield {"event": "error", "data": {"code": "STOPPED", "message": "任务取消"}}
            except Exception as e:
                proc.terminate()
                yield {"event": "error", "data": {"code": "ENGINE_ERROR", "message": str(e)}}
            finally:
                self._active.pop(session_id, None)

    def _parse_event(self, evt: dict) -> Optional[dict]:
        evt_type = evt.get("type", "")
        event = evt.get("event", {})
        inner_type = event.get("type", "")

        if inner_type == "content_block_delta":
            delta = event.get("delta", {}).get("text", "")
            if delta:
                return {"event": "message", "data": {"delta": delta}}
            return None

        if inner_type in ("content_block_start", "content_block_stop"):
            return None

        # ── system 事件 ──
        if evt_type == "system":
            sub = evt.get("subtype", "")
            if sub == "thinking_tokens":
                return {"event": "progress", "data": {"tokens": evt.get("estimated_tokens", 0), "phase": "thinking"}}
            if sub == "init":
                return {"event": "progress", "data": {"tokens": 0, "phase": "init"}}
            return None

        if inner_type == "tool_use":
            name = event.get("name", "unknown")
            tool_input = event.get("input", {})
            desc = f"调用工具: {name}"
            if isinstance(tool_input, dict) and tool_input:
                desc += f" ({json.dumps(tool_input, ensure_ascii=False)[:200]})"
            return {"event": "phase_start", "data": {"phase": "tool", "description": desc, "skill": ""}}

        if inner_type == "tool_result":
            content = event.get("content", "")
            if isinstance(content, list):
                content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
            if content:
                return {"event": "message", "data": {"delta": f"\n\n> **工具输出**: {str(content)[:500]}\n\n"}}
            return None

        if evt_type == "result" and evt.get("is_error"):
            return {"event": "error", "data": {"code": "CLI_ERROR", "message": evt.get("result", "未知错误")}}

        if evt_type == "assistant":
            content_list = evt.get("message", {}).get("content", [])
            full_text = "".join(
                c.get("text", "") for c in content_list
                if isinstance(c, dict) and c.get("type") == "text"
            )
            if full_text:
                return {"event": "message", "data": {"delta": full_text}}
            return None

        return None

    async def _save_claude_response(self, session_id: str):
        """从 Claude CLI 会话存储提取最新回复并保存到数据库。

        使用显式的 workspace 路径而非 os.getcwd()，避免异步环境下
        因工作目录被其他协程切换导致路径推导错误。
        """
        try:
            # Claude CLI 的文件命名规则：移除路径开头的 /，将 / 替换为 -，
            # 并在最前面加 -。如 /path/to/ws → -path-to-ws
            ws_dir = WORKSPACE_DIR / session_id
            sanitized = str(ws_dir.resolve()).lstrip("/").replace("/", "-")
            project_name = f"-{sanitized}"
            session_file = Path.home() / ".claude" / "projects" / project_name / f"{session_id}.jsonl"

            if not session_file.exists():
                projects = Path.home() / ".claude" / "projects"
                found = None
                if projects.is_dir():
                    for cand in projects.glob(f"*/{session_id}.jsonl"):
                        found = cand
                        break
                if not found:
                    import logging
                    logging.getLogger(__name__).info(
                        "claude session jsonl missing: expected %s", session_file
                    )
                    return
                session_file = found

            lines = session_file.read_text().strip().split("\n")
            last_assistant_content = ""
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entry_type = entry.get("type", "")
                if entry_type == "assistant":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = "".join(
                            c.get("text", "") for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        )
                    if content:
                        last_assistant_content = content
                        break
                elif entry_type == "user":
                    break

            # chat.py 已按流式 delta 落库；此处仅确认 jsonl 可读，避免重复插入
            if last_assistant_content:
                import logging
                logging.getLogger(__name__).info(
                    "jsonl assistant len=%s session=%s (db write skipped; owned by chat.py)",
                    len(last_assistant_content),
                    session_id,
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("save_claude_response error: %s", e)


engine = ClaudeEngine()
