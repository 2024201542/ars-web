"""Agent 执行引擎 — 直接调用 LLM API（已弃用）

⚠️ 此模块已弃用，当前活跃路径是 claude_engine.py（Claude CLI 子进程）。
保留此文件作为以下场景的回退：
- 环境未安装 Claude CLI
- 需要直接控制 API 调用参数（max_tokens、temperature 等）
- 未来可能重新激活作为轻量模式

迁移指南: 若需在此模块基础上继续开发，请使用 providers.py 的 make_client()
而非直接实例化 AnthropicClient，以支持多 Provider 协议路由。
"""

from typing import AsyncGenerator, Optional

from clients import make_client
from services.skill_loader import SkillLoader
from services.state_tracker import StateTracker


async def _build_messages(session_id: str, current_message: str, state_tracker: StateTracker) -> list[dict]:
    """构建带历史的多轮对话消息列表。"""
    # 获取历史消息
    history = await state_tracker.get_messages(session_id)
    messages = []
    for m in history:
        role = "assistant" if m["role"] == "assistant" else "user"
        if m.get("content"):
            messages.append({"role": role, "content": m["content"]})

    # 追加当前用户消息
    messages.append({"role": "user", "content": current_message})
    return messages


class AgentRunner:
    """执行 Agent 阶段，流式返回 SSE 事件。"""

    def __init__(self, skill_loader: SkillLoader, state_tracker: StateTracker):
        self.skill_loader = skill_loader
        self.state_tracker = state_tracker

    async def run_research(
        self,
        session_id: str,
        message: str,
        api_key: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        protocol: str = "anthropic",
    ) -> AsyncGenerator[dict, None]:
        """执行深度研究完整流程。"""
        client = make_client(protocol, api_key=api_key, model=model, base_url=base_url)
        skill_name = "deep-research"

        # 获取会话信息
        session = await self.state_tracker.get_session(session_id)
        if not session:
            yield {"event": "error", "data": {"code": "SESSION_NOT_FOUND", "message": "会话不存在"}}
            return

        # 保存用户消息
        await self.state_tracker.add_message(session_id, "user", message)

        # 加载技能提示词
        system_prompt = self.skill_loader.get_agent_system_prompt(skill_name)

        # 构建研究指令（作为 system 提示，引导第一轮；后续轮次跟随历史）
        research_prompt = f"""请根据以下用户的研究需求，执行学术深度研究流程。

## 用户需求
{message}

## 执行要求
请按以下阶段依次执行，每完成一个阶段用 XML 标签标记：

<phase name="research_question">
1. 分析用户需求，提出具体、可行的研究问题
2. 明确研究范围和边界
</phase>

<phase name="methodology">
1. 推荐合适的研究方法
2. 设计研究框架
</phase>

<phase name="literature_search">
1. 搜索相关学术文献（请给出具体的文献标题、作者、年份和期刊）
2. 至少列出 10-15 篇相关文献
</phase>

<phase name="source_verification">
1. 验证每篇文献的可信度
2. 标注文献来源类型（期刊论文/会议论文/预印本等）
</phase>

<phase name="synthesis">
1. 综合分析文献，找出共识、分歧和研究空白
2. 构建理论框架
</phase>

<phase name="report">
1. 编写完整研究报告（采用学术风格，结构化呈现）
2. 包含：摘要、引言、文献综述、方法、分析、结论、参考文献
</phase>

请用学术中文撰写，格式规范，引用清晰。"""

        # 构建带历史的消息列表（第一轮：系统指令 + 用户消息；后续轮次：完整历史）
        history = await state_tracker.get_messages(session_id)
        if len(history) <= 1:
            # 第一轮：使用完整研究指令
            messages = [{"role": "user", "content": research_prompt}]
        else:
            # 后续轮次：使用历史 + 当前消息
            messages = await _build_messages(session_id, message, self.state_tracker)

        full_response = ""
        current_phase = "research_question"

        # 发送阶段开始事件
        yield {
            "event": "phase_start",
            "data": {
                "phase": current_phase,
                "description": "正在分析研究问题...",
            },
        }

        try:
            async for chunk in client.stream_message(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=8192,
            ):
                full_response += chunk
                yield {"event": "message", "data": {"delta": chunk}}

        except RuntimeError as e:
            yield {"event": "error", "data": {"code": "API_ERROR", "message": str(e)}}
            return

        # 保存 Assistant 消息
        await self.state_tracker.add_message(
            session_id, "assistant", full_response,
            agent_name="research_agent",
            phase_name=current_phase,
        )

        # 保存研究报告产出物
        await self.state_tracker.add_artifact(
            session_id, "research_report", full_response
        )

        await self.state_tracker.update_session_status(session_id, "completed")

        yield {"event": "done", "data": {"message": "深度研究完成"}}

    async def run_paper(
        self,
        session_id: str,
        message: str,
        api_key: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        protocol: str = "anthropic",
    ) -> AsyncGenerator[dict, None]:
        """执行论文撰写流程。"""
        client = make_client(protocol, api_key=api_key, model=model, base_url=base_url)
        skill_name = "academic-paper"

        session = await self.state_tracker.get_session(session_id)
        if not session:
            yield {"event": "error", "data": {"code": "SESSION_NOT_FOUND", "message": "会话不存在"}}
            return

        await self.state_tracker.add_message(session_id, "user", message)

        system_prompt = self.skill_loader.get_agent_system_prompt(skill_name)

        paper_prompt = f"""请根据以下需求撰写学术论文。

## 论文需求
{message}

## 执行要求
请按以下阶段依次执行：

<phase name="outline">
1. 设计论文大纲（IMRaD 结构：引言、方法、结果、讨论、结论）
2. 分配各章节字数
</phase>

<phase name="draft">
1. 撰写完整论文草稿
2. 学术规范写作，引用清晰
</phase>

<phase name="citation">
1. 检查引用格式（APA 7th 格式）
2. 生成参考文献列表
</phase>

<phase name="abstract">
1. 撰写中英文双语摘要
2. 提取 3-5 个关键词
</phase>

请用学术中文撰写（英文摘要除外）。"""

        # 构建带历史的消息列表
        history = await state_tracker.get_messages(session_id)
        if len(history) <= 1:
            messages = [{"role": "user", "content": paper_prompt}]
        else:
            messages = await _build_messages(session_id, message, self.state_tracker)

        yield {
            "event": "phase_start",
            "data": {"phase": "outline", "description": "正在设计论文大纲..."},
        }

        full_response = ""
        try:
            async for chunk in client.stream_message(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=16384,
            ):
                full_response += chunk
                yield {"event": "message", "data": {"delta": chunk}}

        except RuntimeError as e:
            yield {"event": "error", "data": {"code": "API_ERROR", "message": str(e)}}
            return

        await self.state_tracker.add_message(
            session_id, "assistant", full_response,
            agent_name="paper_writer",
            phase_name="draft",
        )

        await self.state_tracker.add_artifact(session_id, "draft", full_response)
        await self.state_tracker.update_session_status(session_id, "completed")

        yield {
            "event": "result",
            "data": {"type": "draft", "content": full_response, "format": "markdown"},
        }

        yield {"event": "done", "data": {"message": "论文撰写完成"}}

    async def run_generic(
        self,
        session_id: str,
        skill_name: str,
        message: str,
        api_key: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        protocol: str = "anthropic",
    ) -> AsyncGenerator[dict, None]:
        """通用技能执行器 —— 加载 SKILL.md + Agents 作为 system prompt，执行用户指令。"""
        client = make_client(protocol, api_key=api_key, model=model, base_url=base_url)

        session = await self.state_tracker.get_session(session_id)
        if not session:
            yield {"event": "error", "data": {"code": "SESSION_NOT_FOUND", "message": "会话不存在"}}
            return

        await self.state_tracker.add_message(session_id, "user", message)

        system_prompt = self.skill_loader.get_agent_system_prompt(skill_name)
        display_name = self.skill_loader.DISPLAY_NAMES.get(skill_name, skill_name)

        # 按模式动态构建提示词
        mode_name = session.get("mode_name", "full")
        skill_prompt = self._build_mode_prompt(skill_name, mode_name, message)

        yield {
            "event": "phase_start",
            "data": {"phase": mode_name, "description": f"正在执行 {display_name} ({mode_name})...", "skill": skill_name},
        }

        # 构建带历史的消息列表
        history = await state_tracker.get_messages(session_id)
        if len(history) <= 1:
            messages = [{"role": "user", "content": skill_prompt}]
        else:
            messages = await _build_messages(session_id, message, self.state_tracker)
        full_response = ""

        try:
            async for chunk in client.stream_message(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=16384 if skill_name == "academic-pipeline" else 8192,
            ):
                full_response += chunk
                yield {"event": "message", "data": {"delta": chunk}}

        except RuntimeError as e:
            yield {"event": "error", "data": {"code": "API_ERROR", "message": str(e)}}
            return

        await self.state_tracker.add_message(
            session_id, "assistant", full_response,
            agent_name=f"{skill_name}_agent",
            phase_name=mode_name,
        )

        await self.state_tracker.add_artifact(
            session_id, f"{skill_name}_result", full_response
        )
        await self.state_tracker.update_session_status(session_id, "completed")

        yield {"event": "done", "data": {"message": f"{display_name} 完成"}}

    def _build_mode_prompt(self, skill_name: str, mode_name: str, message: str) -> str:
        """根据技能和模式构建用户指令。"""
        prompts = {
            "academic-paper-reviewer": f"""请对以下论文进行学术同行评审。

## 需要评审的论文
{message}

## 评审要求
- 从多角度评估论文质量：创新性、方法论严谨性、论证逻辑性、文献覆盖度
- 指出优点和不足
- 给出修改建议和总体评价（Accept / Minor Revision / Major Revision / Reject）
- 使用学术评分标准

请用学术中文撰写评审报告。""",

            "academic-pipeline": f"""请执行全流程学术管线，从研究到论文撰写完成全流程。

## 研究主题
{message}

## 流程要求
请按以下阶段依次执行：

1. **Stage 1 研究阶段**: 研究问题构思、文献检索、综合分析
2. **Stage 2 撰写阶段**: 基于研究结果撰写完整学术论文（IMRaD 格式）
3. **Stage 2.5 完整性验证**: 自检论文完整性、逻辑一致性
4. **Stage 3 审稿阶段**: 对论文进行自我同行评审
5. **Stage 4 修订阶段**: 根据审稿意见修订论文
6. **Stage 5 最终定稿**: 生成最终版本

请用学术中文撰写，在每个阶段完成后明确标注当前阶段和产出。""",

            "kimi-cnki-search": f"""请使用 Kimi AI 检索中文学术文献。

## 检索需求
{message}

## 要求
- 优先检索 CNKI 和 CSSCI 来源期刊的中文学术文献
- 对检索结果进行分类整理
- 提供每篇文献的标题、作者、期刊、年份和简要摘要
- 以结构化格式输出

请用中文输出检索结果。""",
        }

        if skill_name in prompts:
            return prompts[skill_name]

        # 默认通用提示词
        return f"""请执行 {self.skill_loader.DISPLAY_NAMES.get(skill_name, skill_name)} 任务。

## 用户需求
{message}

## 要求
请用学术规范和严谨的方式进行，用学术中文撰写输出结果。"""

