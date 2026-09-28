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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional, Union

from config import ARS_SKILLS_PATH, WORKSPACE_DIR
from services.provider_status import since as provider_error_since
from services.state_tracker import tracker as state_tracker


def _decode_cli_buffer(raw: bytes) -> tuple[str, str]:
    """返回 (文本, 编码)。Windows 上 CLI 管道有时是 UTF-16。"""
    if raw.startswith(b"\xff\xfe") or (len(raw) >= 4 and raw[1] == 0 and raw[3] == 0):
        if len(raw) % 2:
            raw = raw[:-1]
        return raw.decode("utf-16-le", errors="replace"), "utf-16-le"
    if raw.startswith(b"\xfe\xff") or (len(raw) >= 4 and raw[0] == 0 and raw[2] == 0):
        if len(raw) % 2:
            raw = raw[:-1]
        return raw.decode("utf-16-be", errors="replace"), "utf-16-be"
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _parse_cli_line(raw: bytes) -> Optional[dict]:
    """Claude CLI 在 Windows 上有时会把一行写成系统编码或 UTF-16。"""
    raw = raw.strip().lstrip(b"\xef\xbb\xbf")
    if not raw:
        return None
    text, _enc = _decode_cli_buffer(raw)
    text = text.strip("\ufeff\r\n ")
    if not text:
        return None
    try:
        evt = json.loads(text)
    except json.JSONDecodeError:
        try:
            evt = json.loads(raw.decode("gbk"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    return evt if isinstance(evt, dict) else None


def _provider_stop_message(status: int) -> str:
    if status in (401, 403):
        return "DeepSeek 拒绝了当前密钥，所以回答停在这里。请点左下角的模型名，到设置里重新保存 API Key，然后再发一次。"
    return f"模型没有开始回答（错误 {status}）。请到设置里检查密钥和当前模型。"


def _find_claude_bin() -> str:
    env_bin = os.environ.get("CLAUDE_BIN", "")
    if env_bin and Path(env_bin).exists():
        return env_bin
    which = shutil.which("claude")
    if which:
        # Windows: npm 的 claude.cmd 转调 bin/claude.exe；优先用 .exe 避免 asyncio 子进程问题
        if which.lower().endswith(".cmd") or which.lower().endswith(".bat"):
            exe = Path(which).resolve().parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
            if exe.exists():
                return str(exe)
        return which

    candidates = [
        str(Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
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


def claude_session_exists(session_id: str) -> bool:
    """本机会话是否已在 Claude CLI 里建立。协作副本只有数据库消息，没有这份会话。"""
    projects = Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return False
    return any(projects.glob(f"**/{session_id}.jsonl"))


def _safe_kill(proc: Union[asyncio.subprocess.Process, subprocess.Popen]) -> None:
    """终止子进程；进程已退出时忽略 ProcessLookupError。"""
    try:
        if proc.poll() is None if isinstance(proc, subprocess.Popen) else proc.returncode is None:
            proc.terminate()
    except ProcessLookupError:
        pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


async def _spawn_cli(cmd: list[str], env: dict, cwd: str):
    """启动 Claude CLI。Windows 上 uvicorn 使用 SelectorEventLoop，不支持 asyncio 子进程。"""
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )


async def _read_stdout_chunk(proc, timeout: float = 15.0) -> bytes:
    """读取一段 stdout；超时返回特殊 sentinel 由调用方发 heartbeat。"""
    if isinstance(proc, subprocess.Popen):
        assert proc.stdout is not None
        try:
            return await asyncio.wait_for(asyncio.to_thread(proc.stdout.read, 4096), timeout=timeout)
        except asyncio.TimeoutError:
            raise
    assert proc.stdout is not None
    return await asyncio.wait_for(proc.stdout.read(4096), timeout=timeout)


async def _read_stderr_text(proc, timeout: float = 2.0) -> str:
    if proc.stderr is None:
        return ""
    try:
        if isinstance(proc, subprocess.Popen):
            data = await asyncio.wait_for(asyncio.to_thread(proc.stderr.read), timeout=timeout)
        else:
            data = await asyncio.wait_for(proc.stderr.read(), timeout=timeout)
        return data.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        return ""


class ClaudeEngine:
    """管理 Claude CLI 子进程，提供流式对话能力。"""

    def __init__(self):
        self._active: dict[str, Union[asyncio.subprocess.Process, subprocess.Popen]] = {}
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
        user_id: str = "",
        allow_tools: bool = False,
        mode_line: str = "",
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
                "academic-pipeline": "你是一个全流程学术研究助手。一次只完成当前这一步，写完就停，等用户确认。",
                "kimi-cnki-search": "你是一个中文学术文献检索助手。帮助检索 CNKI/CSSCI 等中文数据库。",
            }
            system_guide = skill_prompts.get(skill_name, "你是一个学术研究助手。")
            system_guide += (
                "请纯文本格式直接回答用户的问题，使用 Markdown 排版（标题、表格、列表可用），"
                "但绝对不要输出任何以下内容：技能列表、触发条件、路由说明、使用指南、"
                "版本号、更新日志、CLI 命令、Agent 列表、模式列表、文件路径。"
                "把用户当作学者/研究者来对话，忘记你是 AI 助手的身份。"
            )
            if allow_tools:
                system_guide += (
                    "你运行在左侧文件树对应的目录中。用户明确要求修改某一篇文稿时，"
                    "先用 Read 读原文，再用 Edit 或 Write 直接改那个文件并保存，只限 .md、.txt、.bib、.tex。"
                    "不要改用户没点名的文件，不要改 PDF 或表格，不要运行命令。"
                    "Word（.docx）可以改：同目录有一份「原文件名.docx.txt」，里面是一段一行的正文。"
                    "要修改 Word，就改那份 txt 的全文，不要直接改 .docx 文件。"
                    "新建文稿放到 uploads 子目录；如果当前目录是用户打开的本机文件夹，就写在用户指定的位置。"
                    "不要把普通对话自动存成文件。改完用一两句话说明改了哪一篇、改了什么。"
                )
                if skill_name == "academic-pipeline" and mode_line:
                    system_guide += (
                        " 全流程这一步是用户点名要留下的文稿，必须按后面的路径用 Write 保存，"
                        "不要改旧文件，不要写到 uploads。"
                    )
                if mode_line:
                    system_guide += " " + mode_line
            else:
                system_guide += "这一次只回答问题，不要改文件，也不要新建文件。"

            # 确保工作区目录存在。打开了本机文件夹时，对话就在那个文件夹里读写。
            ws_dir = WORKSPACE_DIR / session_id
            ws_dir.mkdir(parents=True, exist_ok=True)
            local_root = None
            if user_id:
                try:
                    from services.workspace_manager import workspace_manager
                    local_root = await workspace_manager.get_local_root(user_id)
                except Exception:
                    local_root = None
            visible = local_root
            if not visible and user_id:
                from services.workspace_manager import user_dir
                visible = user_dir(user_id)
                visible.mkdir(parents=True, exist_ok=True)
            if visible and allow_tools:
                system_guide += f" 左侧文件所在目录是 {visible}。"

            from services.entry_prompt import FILE_TOOLS

            cmd = [CLAUDE_BIN]
            if model:
                cmd.extend(["--model", model])
            cmd.extend([
                "--bare",
                "-p",
                "--verbose",
                "--output-format", "stream-json",
                "--system-prompt-snapshot", "off",
                "--system-prompt", system_guide,
                session_flag, session_id,
                message,
                "--add-dir", str(ARS_SKILLS_PATH),
                "--add-dir", str(WORKSPACE_DIR / session_id),
            ])
            if allow_tools:
                cmd.extend([
                    "--restricted",
                    "--permission-mode", "acceptEdits",
                    "--tools", FILE_TOOLS,
                    "--allowedTools", FILE_TOOLS,
                ])
            else:
                cmd.extend(["--tools", ""])
            if local_root:
                cmd.extend(["--add-dir", str(local_root)])
                ws_dir = local_root
            elif user_id:
                from services.workspace_manager import user_dir
                cmd.extend(["--add-dir", str(user_dir(user_id))])
                ws_dir = user_dir(user_id)

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
            if model:
                child_env["ANTHROPIC_MODEL"] = model
                child_env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
                child_env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
                child_env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = model
            child_env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

            before_files = None
            word_sidecars: list = []
            if allow_tools:
                from services.edit_snapshot import snapshot_tree
                before_files = snapshot_tree(Path(ws_dir))
                from services.docx_text import prepare_docx_sidecars
                word_sidecars = prepare_docx_sidecars(Path(ws_dir))

            def settle_word():
                nonlocal word_sidecars
                if word_sidecars is None:
                    return
                pending = word_sidecars
                word_sidecars = None
                try:
                    from services.docx_text import finish_docx_sidecars, restore_broken_docx
                    if before_files is not None:
                        restore_broken_docx(Path(ws_dir), before_files)
                    finish_docx_sidecars(pending)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("write docx sidecars failed")

            # ── 启动子进程（cwd 指向工作区，Write 工具默认写入该目录） ──
            if not Path(CLAUDE_BIN).exists() and shutil.which(CLAUDE_BIN) is None:
                settle_word()
                yield {
                    "event": "error",
                    "data": {
                        "code": "CLAUDE_CLI_MISSING",
                        "message": (
                            "本机未安装 Claude Code CLI，无法发起对话。"
                            "请先安装 @anthropic-ai/claude-code，或设置环境变量 CLAUDE_BIN 指向 claude 可执行文件。"
                            "（ARS Web 的所有模型都通过 Claude CLI 调用，包括 DeepSeek。）"
                        ),
                    },
                }
                return

            try:
                proc = await _spawn_cli(cmd, child_env, str(ws_dir))
            except FileNotFoundError:
                settle_word()
                yield {
                    "event": "error",
                    "data": {
                        "code": "CLAUDE_CLI_MISSING",
                        "message": f"无法启动 Claude CLI（{CLAUDE_BIN}）。请安装 Claude Code 或设置 CLAUDE_BIN。",
                    },
                }
                return
            except NotImplementedError:
                settle_word()
                yield {
                    "event": "error",
                    "data": {
                        "code": "ENGINE_ERROR",
                        "message": "当前事件循环不支持子进程（Windows/uvicorn）。请重启后端或升级引擎。",
                    },
                }
                return
            self._active[session_id] = proc
            edits_sent = False

            def pop_edits():
                nonlocal edits_sent
                settle_word()
                if edits_sent or before_files is None:
                    return None
                edits_sent = True
                from services.edit_snapshot import commit_changes
                try:
                    return commit_changes(user_id or "", Path(ws_dir), before_files)
                except Exception:
                    return None

            try:
                if proc.stdout is None:
                    yield {"event": "error", "data": {"code": "SUBPROCESS_ERROR", "message": "子进程无 stdout"}}
                    return

                buffer = b""
                text_hold = ""
                encoding: Optional[str] = None
                saw_text = False
                started_at = datetime.now(timezone.utc).timestamp()
                while True:
                    if cancel_event.is_set():
                        _safe_kill(proc)
                        edits = pop_edits()
                        if edits:
                            yield {"event": "files_changed", "data": edits}
                        yield {"event": "error", "data": {"code": "STOPPED", "message": "用户中断"}}
                        return

                    provider_err = provider_error_since(started_at)
                    if provider_err:
                        _safe_kill(proc)
                        edits = pop_edits()
                        if edits:
                            yield {"event": "files_changed", "data": edits}
                        yield {
                            "event": "error",
                            "data": {
                                "code": "PROVIDER_AUTH" if provider_err["status"] in (401, 403) else "PROVIDER_ERROR",
                                "message": _provider_stop_message(provider_err["status"]),
                            },
                        }
                        return

                    try:
                        chunk = await _read_stdout_chunk(proc, timeout=15)
                    except asyncio.TimeoutError:
                        yield {"event": "heartbeat", "data": {}}
                        continue

                    if not chunk:
                        break

                    buffer += chunk
                    if encoding is None and len(buffer) >= 4:
                        _probe, encoding = _decode_cli_buffer(buffer[:4])
                    if encoding is None:
                        continue
                    if encoding.startswith("utf-16") and len(buffer) % 2 == 1:
                        data, buffer = buffer[:-1], buffer[-1:]
                    else:
                        data, buffer = buffer, b""
                    text_hold += data.decode(encoding, errors="replace")

                    while "\n" in text_hold:
                        line, text_hold = text_hold.split("\n", 1)
                        line = line.strip().lstrip("\ufeff")
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(evt, dict):
                            continue
                        parsed = self._parse_event(evt)
                        if parsed:
                            if parsed.get("event") == "message" and (parsed.get("data") or {}).get("delta"):
                                saw_text = True
                            yield parsed

                if text_hold.strip():
                    try:
                        evt = json.loads(text_hold.strip().lstrip("\ufeff"))
                    except json.JSONDecodeError:
                        evt = None
                    if isinstance(evt, dict):
                        parsed = self._parse_event(evt)
                        if parsed:
                            if parsed.get("event") == "message" and (parsed.get("data") or {}).get("delta"):
                                saw_text = True
                            yield parsed

                if not saw_text:
                    recovered = await self._save_claude_response(session_id)
                    if recovered:
                        saw_text = True
                        yield {"event": "message", "data": {"delta": recovered}}
                else:
                    try:
                        await self._save_claude_response(session_id)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning("jsonl fallback save failed: %s", e)

                stderr_text = await _read_stderr_text(proc, timeout=2)
                if isinstance(proc, subprocess.Popen):
                    try:
                        await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5)
                    except asyncio.TimeoutError:
                        _safe_kill(proc)
                else:
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        _safe_kill(proc)

                if stderr_text and not saw_text and ("Error:" in stderr_text or "error" in stderr_text.lower()):
                    edits = pop_edits()
                    if edits:
                        yield {"event": "files_changed", "data": edits}
                    yield {"event": "error", "data": {"code": "CLI_ERROR", "message": stderr_text[:2000]}}
                    return

                edits = pop_edits()
                if edits:
                    yield {"event": "files_changed", "data": edits}
                yield {"event": "done", "data": {"message": "Claude 回应完成"}}

            except asyncio.CancelledError:
                _safe_kill(proc)
                edits = pop_edits()
                if edits:
                    yield {"event": "files_changed", "data": edits}
                yield {"event": "error", "data": {"code": "STOPPED", "message": "任务取消"}}
            except UnicodeDecodeError:
                _safe_kill(proc)
                edits = pop_edits()
                if edits:
                    yield {"event": "files_changed", "data": edits}
                yield {
                    "event": "error",
                    "data": {
                        "code": "ENGINE_ERROR",
                        "message": "模型已经回复，但读取时编码出错，内容没有显示出来。请再发一次。",
                    },
                }
            except Exception as e:
                _safe_kill(proc)
                edits = pop_edits()
                if edits:
                    yield {"event": "files_changed", "data": edits}
                msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                yield {"event": "error", "data": {"code": "ENGINE_ERROR", "message": msg}}
            finally:
                settle_word()
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
            desc = name
            if isinstance(tool_input, dict):
                raw_path = tool_input.get("file_path") or tool_input.get("path") or ""
                if raw_path:
                    desc = f"{name} {Path(str(raw_path)).name}"
                elif tool_input:
                    desc = f"{name} ({json.dumps(tool_input, ensure_ascii=False)[:120]})"
            return {"event": "phase_start", "data": {"phase": "tool", "description": desc, "skill": ""}}

        if inner_type == "tool_result":
            content = event.get("content", "")
            if isinstance(content, list):
                content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
            text = str(content or "")
            if text and len(text) <= 180:
                return {"event": "message", "data": {"delta": f"\n\n> **工具输出**: {text}\n\n"}}
            return None

        if evt_type == "result" and evt.get("is_error"):
            msg = (evt.get("result") or "").strip() or "模型没有返回内容。若这是接续会话，请再发一次。"
            return {"event": "error", "data": {"code": "CLI_ERROR", "message": msg}}

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

    async def _save_claude_response(self, session_id: str) -> str:
        """从 Claude CLI 会话文件取出最新回复。文件是 UTF-8，不能按系统编码去读。"""
        try:
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
                    return ""
                session_file = found

            lines = session_file.read_text(encoding="utf-8", errors="replace").strip().split("\n")
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

            if last_assistant_content:
                import logging
                logging.getLogger(__name__).info(
                    "jsonl assistant len=%s session=%s",
                    len(last_assistant_content),
                    session_id,
                )
            return last_assistant_content or ""
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("save_claude_response error: %s", e)
            return ""


engine = ClaudeEngine()
