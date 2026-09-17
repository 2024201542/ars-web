# ARS Web — 学术研究助手前端包装 技术设计文档

> **版本**: v1.0  
> **日期**: 2026-06-11  
> **上游依赖**: [academic-research-skills v3.9.4.2](../academic-research-skills/)  
> **文档状态**: 正式发布

---

## 目录

- [1. 项目概述](#1-项目概述)
  - [1.1 背景](#11-背景)
  - [1.2 目标用户](#12-目标用户)
  - [1.3 核心原则](#13-核心原则)
- [2. 系统架构](#2-系统架构)
  - [2.1 总体架构](#21-总体架构)
  - [2.2 项目目录结构](#22-项目目录结构)
- [3. 技术栈选型](#3-技术栈选型)
  - [3.1 后端技术栈](#31-后端技术栈)
  - [3.2 前端技术栈](#32-前端技术栈)
  - [3.3 未选用的技术](#33-未选用的技术)
- [4. 后端详细设计](#4-后端详细设计)
- [5. 前端详细设计](#5-前端详细设计)
- [6. 数据流与安全性](#6-数据流与安全性)
- [7. 分阶段实施计划](#7-分阶段实施计划)
- [8. 与上游 ARS 的关系](#8-与上游-ars-的关系)
- [9. 风险与应对](#9-风险与应对)
- [10. 附录](#10-附录)

---

## 1. 项目概述

### 1.1 背景

[academic-research-skills](../academic-research-skills/) (ARS) 是一个 Claude Code 技能套件，提供完整的学术研究辅助能力：

- **4 大核心技能**: 深度研究 / 论文撰写 / 同行评审 / 全流程调度
- **38 个智能 Agent**: 各司其职的专业助手
- **25+ 种工作模式**: 灵活适配不同研究场景
- **完整学术管线**: 从研究构思到论文定稿的全流程覆盖

**现状与挑战**：ARS 目前只能在 **Claude Code CLI** 终端环境下使用，对普通用户门槛较高。

**项目目标**：ARS Web 项目旨在为 ARS 包装一个独立可用的 **Web 前端 + 后端服务**，让用户通过浏览器即可使用学术研究辅助功能。

### 1.2 目标用户

| 用户群体 | 核心需求 | 典型场景 |
|---------|---------|---------|
| **高校研究生、青年教师** | 文献综述、论文撰写辅助 | 毕业论文、期刊投稿、课题研究 |
| **科研工作者** | 深度研究、引用验证 | 学术论文、项目报告、文献调研 |
| **学术期刊审稿人** | 同行评审辅助 | 稿件评审、质量评估、修改建议 |

### 1.3 核心原则

| 原则 | 说明 | 实施策略 |
|------|------|----------|
| **辅助性而非替代性** | 与 ARS 一致，定位为研究助手，不做全自动论文生成器 | 保留用户决策权，关键节点需人工确认 |
| **用户自行提供 API Key** | Anthropic API Key 由用户在前端配置，后端不存储 | 降低运营成本，保障用户数据主权 |
| **渐进式实现** | 首期支持深度研究 + 论文撰写，后续逐步覆盖评审和全流程 | 降低开发风险，快速验证核心价值 |
| **ARS 兼容性** | 核心 Agent 指令不修改，保持与上游 ARS 的兼容性 | 直接读取上游 SKILL.md，减少维护成本 |

---

## 2. 系统架构

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  Vue 3 前端 (ars-web-frontend)             │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  功能模块                                            │  │  │
│  │  │  • 技能选择 / 模式配置                               │  │  │
│  │  │  • 会话管理 / 实时流式输出                           │  │  │
│  │  │  • 结果展示 / 文件下载 (MD/DOCX/PDF)                 │  │  │
│  │  │  • API Key 配置面板                                 │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP/SSE
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                Python FastAPI 后端 (ars-web-backend)             │
│                                                                  │
│  ┌──────────────┐  ┌────────────────┐  ┌───────────────────┐   │
│  │  API 路由层   │  │  Agent 编排引擎 │  │  外部 API 客户端   │   │
│  │              │  │                │  │                   │   │
│  │ /api/session │  │ SkillLoader    │  │ AnthropicClient   │   │
│  │ /api/chat    │  │ AgentRunner    │  │ SemanticScholar   │   │
│  │ /api/result  │  │ WorkflowMgr    │  │ OpenAlexClient    │   │
│  │ /api/export  │  │ StateTracker   │  │ CrossrefClient    │   │
│  └──────────────┘  └────────────────┘  └───────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              ARS Skill 文件读取层                          │   │
│  │  • 读取 ../academic-research-skills/ 下 SKILL.md          │   │
│  │  • 解析 Agent 定义、模式配置、Template                     │   │
│  │  • 复用 scripts/ 下 Python 客户端脚本                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**架构特点**：
- **前后端分离**: Vue 3 + FastAPI，通过 HTTP/SSE 通信
- **流式响应**: SSE (Server-Sent Events) 实现实时输出
- **插件式技能加载**: 运行时读取 ARS SKILL.md，无需硬编码

### 2.2 项目目录结构

```
/root/project/ars-web/
├── TECHNICAL_DESIGN.md          # 本文件
├── backend/                     # Python FastAPI 后端
│   ├── requirements.txt         # Python 依赖
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 配置管理
│   ├── routers/                 # API 路由模块
│   │   ├── session.py           # 会话管理 API
│   │   ├── chat.py              # 对话/流式输出 API
│   │   ├── export.py            # 文件导出 API
│   │   └── skills.py            # 技能查询 API
│   ├── services/                # 核心业务逻辑
│   │   ├── skill_loader.py      # ARS SKILL.md 解析器
│   │   ├── agent_runner.py      # Agent 执行引擎
│   │   ├── workflow_manager.py  # 工作流编排
│   │   └── state_tracker.py     # 会话状态管理
│   ├── clients/                 # 外部服务客户端
│   │   ├── anthropic_client.py  # Anthropic API 封装
│   │   ├── semantic_scholar.py  # Semantic Scholar API
│   │   ├── openalex_client.py   # OpenAlex API
│   │   └── crossref_client.py   # Crossref API
│   ├── models/                  # 数据模型
│   │   ├── session.py           # 会话数据模型
│   │   ├── message.py           # 消息数据模型
│   │   └── skill.py             # 技能数据模型
│   └── utils/                   # 工具函数
│       ├── markdown_parser.py   # Markdown 解析工具
│       └── exporter.py          # 文件导出工具 (MD/DOCX/PDF)
├── frontend/                    # Vue 3 前端
│   ├── package.json             # Node.js 依赖
│   ├── vite.config.ts           # Vite 构建配置
│   ├── index.html               # HTML 入口
│   ├── src/
│   │   ├── main.ts              # 应用入口
│   │   ├── App.vue              # 根组件
│   │   ├── router/              # 路由配置
│   │   │   └── index.ts
│   │   ├── stores/              # Pinia 状态管理
│   │   │   ├── session.ts       # 会话状态 Store
│   │   │   └── settings.ts      # 用户设置 Store
│   │   ├── views/               # 页面组件
│   │   │   ├── HomeView.vue     # 首页 / 技能选择
│   │   │   ├── ResearchView.vue # 深度研究页面
│   │   │   ├── PaperView.vue    # 论文撰写页面
│   │   │   ├── ReviewView.vue   # 同行评审页面
│   │   │   └── SettingsView.vue # 设置页面 (API Key)
│   │   ├── components/          # 可复用组件
│   │   │   ├── ChatPanel.vue    # 对话面板 (流式输出)
│   │   │   ├── ModeSelector.vue # 模式选择器
│   │   │   ├── ResultViewer.vue # 结果展示器
│   │   │   ├── ProgressBar.vue  # 进度指示器
│   │   │   ├── ExportButton.vue # 导出按钮
│   │   │   └── SetupWizard.vue  # 初始设置向导
│   │   ├── api/                 # API 调用封装
│   │   │   └── index.ts
│   │   └── types/               # TypeScript 类型定义
│   │       └── index.ts
│   └── public/
│       └── favicon.svg
└── docker-compose.yml           # 容器化部署 (可选)
```

---

## 3. 技术栈选型

### 3.1 后端技术栈

| 组件 | 选型 | 选型理由 |
|------|------|----------|
| **Web 框架** | FastAPI (Python 3.11+) | 原生支持 SSE 流式输出、自动生成 OpenAPI 文档、异步高性能 |
| **LLM 调用** | `anthropic` Python SDK | Anthropic 官方 SDK，完美支持 Messages API + streaming |
| **数据存储** | SQLite + aiosqlite | 轻量级数据库，单机部署足够；异步访问提升性能 |
| **文件导出** | Pandoc (系统调用) | 复用 ARS 现有方案，支持 MD → DOCX/PDF/LaTeX 转换 |
| **任务队列** | asyncio + 内存队列 | 首期无需 Redis，单进程 asyncio 足够应对并发 |
| **YAML 解析** | ruamel.yaml | 与 ARS 现有依赖保持一致，支持 YAML 注释保留 |

### 3.2 前端技术栈

| 组件 | 选型 | 选型理由 |
|------|------|----------|
| **框架** | Vue 3 + Composition API | 学习曲线平缓，适合快速开发，响应式系统强大 |
| **构建工具** | Vite 5 | 极速 HMR、TypeScript 原生支持、生产构建优化 |
| **状态管理** | Pinia | Vue 3 官方推荐，轻量级，TypeScript 友好 |
| **UI 框架** | Tailwind CSS 3 | 快速构建界面，无需引入重型组件库，高度可定制 |
| **Markdown 渲染** | markdown-it + highlight.js | 高性能渲染研究结果、论文预览，支持代码高亮 |
| **HTTP 客户端** | fetch + EventSource | 原生支持 SSE 流式读取，无需额外依赖 |
| **路由** | Vue Router 4 | SPA 路由管理，支持动态路由和导航守卫 |

### 3.3 未选用的技术

| 技术 | 未选用理由 | 备注 |
|------|------------|------|
| Redis / Celery | 首期用户量小，asyncio 内存队列足够 | 后续高并发场景可引入 |
| PostgreSQL | 单机 SQLite 满足需求，降低部署复杂度 | 后续数据量增长可迁移 |
| WebSocket | SSE 更简单，单向流式输出已满足需求 | 无需全双工通信 |
| LangChain / LlamaIndex | ARS 有自己的 Agent 编排逻辑，不引入额外抽象层 | 保持架构简洁 |
| Docker (首期) | 可选提供 docker-compose，但不强制 | 本地开发优先，容器化可选 |

---

## 4. 后端详细设计

### 4.1 API 设计

#### 4.1.1 会话管理 API

| 方法 | 路径 | 说明 | 请求体/响应 |
|------|------|------|-------------|
| `POST` | `/api/sessions` | 创建新会话 | 返回 `session_id` |
| `GET` | `/api/sessions` | 获取历史会话列表 | 返回会话摘要数组 |
| `GET` | `/api/sessions/{id}` | 获取会话详情 | 返回完整会话信息（含消息历史） |
| `DELETE` | `/api/sessions/{id}` | 删除会话 | 返回删除确认 |

#### 4.1.2 对话交互 API (核心)

| 方法 | 路径 | 说明 | 备注 |
|------|------|------|------|
| `POST` | `/api/sessions/{id}/chat` | 发送消息 | 返回 SSE 流式响应 |
| `POST` | `/api/sessions/{id}/chat/stop` | 中断当前生成 | 立即停止流式输出 |

**SSE 事件类型定义**:

```
event: message       # 文本增量 (delta)
event: agent_switch  # Agent 切换通知 {"agent": "bibliography_agent", "phase": 2}
event: phase_start   # 阶段开始 {"phase": "literature_search", "description": "..."}
event: phase_done    # 阶段完成 {"phase": "literature_search"}
event: result        # 阶段产出的结构化结果
event: error         # 错误信息 {"code": "...", "message": "..."}
event: done          # 全部完成
```

#### 4.1.3 技能与模式 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skills` | 获取所有可用技能列表 |
| `GET` | `/api/skills/{name}/modes` | 获取某技能的所有模式 |
| `GET` | `/api/skills/{name}/config` | 获取技能配置项（论文类型、引用格式等） |

#### 4.1.4 文件导出 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/sessions/{id}/export` | 导出会话结果为指定格式 |
| `GET` | `/api/sessions/{id}/exports/{file_id}` | 下载导出文件 |

**支持的导出格式**: `markdown` / `docx` / `pdf` / `latex`

#### 4.1.5 设置 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `PUT` | `/api/settings` | 更新用户设置（API Key 等） |
| `GET` | `/api/settings` | 获取当前设置（脱敏显示） |

### 4.2 核心模块设计

#### 4.2.1 Skill Loader (`services/skill_loader.py`)

**职责**: 读取上游 ARS 项目中的 SKILL.md 文件，解析出结构化的技能定义。

```python
class SkillDefinition:
    name: str                    # 技能标识，如 "deep-research"
    version: str                 # 版本号，如 "2.9.4"
    description: str             # 技能描述
    modes: list[ModeDefinition]  # 可用模式列表
    agents: list[AgentDefinition] # Agent 定义列表
    triggers: list[str]          # 触发关键词
    system_prompt: str           # 完整 SKILL.md 的 Markdown 内容
```

**解析策略**:
1. 读取 `{skill}/SKILL.md` 的 YAML frontmatter + Markdown body
2. 读取 `{skill}/agents/*.md` 的所有 Agent 定义
3. 读取 `{skill}/references/*.md` 的相关引用
4. 将完整的 Agent 指令拼接为 LLM 可用的 system prompt

#### 4.2.2 Agent Runner (`services/agent_runner.py`)

**职责**: 核心执行引擎，负责 Agent 的调度和执行。

```python
class AgentRunner:
    async def run_phase(
        self,
        session_id: str,
        skill: str,
        mode: str,
        agent: str,
        context: dict,
    ) -> AsyncGenerator[SSEEvent, None]:
        """执行一个 Agent 阶段，流式返回事件"""
        ...
```

**核心功能**:
1. 构建多 Agent 的 system prompt（根据当前阶段选择对应 Agent）
2. 调用 Anthropic Messages API（streaming 模式）
3. 解析 Agent 输出，识别阶段切换信号
4. 触发下一阶段 Agent 或等待用户确认

**Agent 调度流程** (以 deep-research 为例):

```
用户输入研究主题
  ↓
┌─────────────────────────────────────────────────────┐
│ 阶段 1: research_question_agent (研究问题构思)       │
│ [用户确认]                                           │
├─────────────────────────────────────────────────────┤
│ 阶段 2: research_architect_agent (方法论设计)       │
│ [用户确认]                                           │
├─────────────────────────────────────────────────────┤
│ 阶段 3: bibliography_agent (文献检索)               │
├─────────────────────────────────────────────────────┤
│ 阶段 4: source_verification_agent (来源验证)        │
├─────────────────────────────────────────────────────┤
│ 阶段 5: synthesis_agent (综合分析)                  │
│ [用户确认]                                           │
├─────────────────────────────────────────────────────┤
│ 阶段 6: report_compiler_agent (报告编写)            │
├─────────────────────────────────────────────────────┤
│ 阶段 7: editor_in_chief_agent (编辑审查)            │
├─────────────────────────────────────────────────────┤
│ 阶段 8: ethics_review_agent (伦理审查)              │
│ [最终输出]                                           │
└─────────────────────────────────────────────────────┘
```

#### 4.2.3 Workflow Manager (`services/workflow_manager.py`)

**职责**: 管理技能的工作流状态机。

- 定义每个技能的阶段序列
- 管理阶段间的依赖关系
- 处理用户确认检查点 (checkpoint)
- 支持中断恢复

#### 4.2.4 State Tracker (`services/state_tracker.py`)

**职责**: 管理会话状态，持久化到 SQLite。

**状态数据**:
- 当前技能、模式、阶段
- 中间产出物（研究问题、方法论蓝图、文献列表等）
- 消息历史
- Material Passport (YAML)

### 4.3 数据模型 (SQLite)

```sql
-- 会话表
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    mode_name TEXT NOT NULL,
    title TEXT,
    status TEXT DEFAULT 'active',  -- active / paused / completed / error
    passport TEXT,                  -- Material Passport YAML
    created_at TEXT,
    updated_at TEXT
);

-- 消息表
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,             -- user / assistant / system
    content TEXT,
    agent_name TEXT,                -- 当前消息关联的 Agent
    phase_name TEXT,                -- 当前消息关联的阶段
    metadata TEXT,                  -- JSON: tokens, cost 等
    created_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- 中间产出表
CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    artifact_type TEXT,             -- research_question / bibliography / outline / draft / review
    content TEXT,                   -- Markdown 内容
    format TEXT DEFAULT 'markdown',
    created_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- 用户设置表
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT,                     -- 敏感信息使用 Fernet 加密
    updated_at TEXT
);
```

### 4.4 Anthropic API 封装

```python
# clients/anthropic_client.py
class AnthropicClient:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def stream_message(
        self,
        system_prompt: str,    # 完整的 Agent 指令 (从 SKILL.md 构建)
        messages: list[dict],  # 对话历史
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        """流式调用 Anthropic Messages API"""
        ...
```

**模型选择策略**:

| 场景 | 推荐模型 | 说明 |
|------|----------|------|
| 默认场景 | `claude-sonnet-4-20250514` | 性价比最优，适合大部分任务 |
| 复杂推理 | `claude-opus-4-20250514` | Editorial Review 等高要求场景 |
| 用户自定义 | 用户在前端 Settings 中选择 | 支持用户自行选择模型 |

---

## 5. 前端详细设计

### 5.1 路由设计

| 路径 | 组件 | 说明 |
|------|------|------|
| `/` | `HomeView` | 首页，技能卡片选择，新建会话 |
| `/settings` | `SettingsView` | API Key、模型偏好设置 |
| `/session/:id/research` | `ResearchView` | 深度研究交互页 |
| `/session/:id/paper` | `PaperView` | 论文撰写交互页 |
| `/session/:id/review` | `ReviewView` | 同行评审交互页 |

### 5.2 页面布局

```
┌──────────────────────────────────────────────────────────────┐
│  Header (Logo | 会话标题 | 设置入口)                           │
├──────────┬───────────────────────────────────────────────────┤
│          │                                                   │
│  左侧     │              主对话区域                            │
│  阶段     │        (ChatPanel + ResultViewer)                 │
│  导航     │                                                   │
│          │        • 流式输出 Agent 思考                       │
│  ● 研究   │        • Markdown 渲染结果                        │
│    问题   │        • 内嵌代码 / 表格 / 引用                    │
│  ○ 方法   │                                                   │
│  ○ 文献   │                                                   │
│  ○ 分析   │                                                   │
│  ○ 报告   │                                                   │
│          │                                                   │
├──────────┴───────────────────────────────────────────────────┤
│  Footer (输入框 | 模式切换 | 导出按钮 | 确认/继续)              │
└──────────────────────────────────────────────────────────────┘
```

### 5.3 核心组件

#### 5.3.1 ChatPanel — 对话面板

**功能特性**:
- 使用 SSE EventSource 读取后端流式输出
- Markdown 实时渲染（支持 LaTeX 数学公式）
- 消息类型区分：普通消息 / 阶段通知 / 结构化结果
- 自动滚动到底部

#### 5.3.2 ModeSelector — 模式选择器

**功能特性**:
- 新建会话时展示
- 列出当前技能的所有可用模式
- 每个模式附带简短描述、预计时间、适用场景
- 支持技能内的 Paper Type / Citation Format 等次级配置

#### 5.3.3 ResultViewer — 结果展示器

**功能特性**:
- 多 Tab 切换：文献列表 / 论文大纲 / 完整草稿 / 审查报告
- 支持 Markdown 预览 + 原始代码切换
- 内嵌引用跳转和外部链接

#### 5.3.4 ExportButton — 导出按钮

**功能特性**:
- 下拉菜单：Markdown / DOCX / PDF / LaTeX
- 点击后调用后端导出 API，触发浏览器下载

### 5.4 状态管理 (Pinia)

```typescript
// stores/session.ts
interface SessionState {
  currentSession: Session | null;
  messages: Message[];
  phases: PhaseInfo[];
  currentPhase: string;
  isStreaming: boolean;
}

// stores/settings.ts
interface SettingsState {
  anthropicApiKey: string;    // 仅存内存，不持久化到 localStorage
  selectedModel: string;
  moonShotApiKey: string;     // 可选
  s2ApiKey: string;           // 可选
}
```

---

## 6. 数据流与安全性

### 6.1 完整交互流程

```
用户                    前端                     后端                    LLM API
 │                      │                       │                        │
 │  1. 选择技能 + 模式    │                       │                        │
 │─────────────────────>│                       │                        │
 │                      │  2. POST /sessions     │                        │
 │                      │─────────────────────>│                        │
 │                      │  3. session_id         │                        │
 │                      │<─────────────────────│                        │
 │                      │                       │                        │
 │  4. 输入研究主题       │                       │                        │
 │─────────────────────>│                       │                        │
 │                      │  5. POST /chat (SSE)   │                        │
 │                      │─────────────────────>│                        │
 │                      │                       │  6. 加载 Skill         │
 │                      │                       │     构建 System Prompt │
 │                      │                       │                        │
 │                      │                       │  7. Messages API       │
 │                      │                       │─────────────────────>│
 │                      │                       │  8. SSE token stream   │
 │                      │                       │<─────────────────────│
 │                      │  9. SSE 事件转发       │                        │
 │                      │<─────────────────────│                        │
 │  10. 实时看到输出      │                       │                        │
 │<─────────────────────│                       │                        │
 │                      │                       │                        │
 │  11. [检查点] 确认     │                       │                        │
 │─────────────────────>│                       │                        │
 │                      │  12. POST /chat (继续)  │                        │
 │                      │─────────────────────>│                        │
 │                      │     ... 重复 7-10 ...  │                        │
 │                      │                       │                        │
 │  13. 导出结果          │                       │                        │
 │─────────────────────>│                       │                        │
 │                      │  14. POST /export      │                        │
 │                      │─────────────────────>│                        │
 │                      │                       │  15. Pandoc 转换       │
 │                      │  16. 文件下载          │                        │
 │                      │<─────────────────────│                        │
 │                      │                       │                        │
```

### 6.2 安全性设计

#### 6.2.1 API Key 安全

| 安全措施 | 实施方式 |
|----------|----------|
| **传输安全** | 用户在前端输入的 API Key 通过 HTTPS 传输到后端 |
| **内存存储** | 后端仅在内存中持有当前会话的 API Key，不写入数据库 |
| **会话隔离** | 会话结束后清除内存中的 Key |
| **加密存储** | 如果用户勾选"记住"，后端使用 `cryptography.fernet` 加密后存入 SQLite |

#### 6.2.2 输入校验

- 所有用户输入必须做长度限制和内容过滤
- Session ID 必须归属校验，防止跨用户访问

#### 6.2.3 速率限制

- 对 `/api/chat` 接口做 per-session 的速率限制
- 防止滥用导致用户 API 费用过高

---

## 7. 分阶段实施计划

### Phase 1: MVP — 深度研究 (deep-research)

**目标**: 跑通 "用户输入主题 → 后端编排 Agent → 前端流式展示 → 下载报告" 的完整链路

**任务列表**:

| 序号 | 任务 | 预计工时 |
|------|------|----------|
| 1 | 搭建 FastAPI 后端骨架（main.py + 路由） | 1 天 |
| 2 | 实现 Skill Loader（解析 deep-research SKILL.md + 7 个 Agent） | 2 天 |
| 3 | 实现 AnthropicClient（流式调用） | 1 天 |
| 4 | 实现简化版 AgentRunner（串联 3 个核心 Agent） | 3 天 |
| 5 | 实现 SQLite 存储（sessions / messages / artifacts） | 1 天 |
| 6 | 搭建 Vue 3 + Vite 前端骨架 | 1 天 |
| 7 | 实现 SettingsView（API Key 配置） | 0.5 天 |
| 8 | 实现 HomeView（技能选择） | 1 天 |
| 9 | 实现 ResearchView（ChatPanel + ResultViewer） | 3 天 |
| 10 | 实现 Markdown 导出 | 0.5 天 |

**预计总工时**: 14 天

### Phase 2: 论文撰写 (academic-paper)

**目标**: 支持论文撰写全流程

**任务列表**:

| 序号 | 任务 | 预计工时 |
|------|------|----------|
| 1 | 解析 academic-paper SKILL.md + 12 个 Agent | 2 天 |
| 2 | 实现 Structure Architect + Draft Writer + Citation Compliance Agent 编排 | 4 天 |
| 3 | 前端 PaperView 页面（含大纲配置、引用格式选择） | 3 天 |
| 4 | 实现 DOCX/PDF 导出（集成 Pandoc） | 2 天 |
| 5 | 双语摘要生成 | 1 天 |

**预计总工时**: 12 天

### Phase 3: 同行评审 (academic-paper-reviewer)

**目标**: 支持多视角论文评审

**任务列表**:

| 序号 | 任务 | 预计工时 |
|------|------|----------|
| 1 | 解析 academic-paper-reviewer SKILL.md + 7 个 Agent | 2 天 |
| 2 | 实现并行 Reviewer 编排（EIC + 3 Reviewers + Devil's Advocate） | 4 天 |
| 3 | 前端 ReviewView 页面（多 Review 报告 Tab 展示） | 3 天 |
| 4 | Editorial Decision Letter 生成 | 1 天 |

**预计总工时**: 10 天

### Phase 4: 全流程 + 增强

**目标**: 完整管线 + 增强体验

**任务列表**:

| 序号 | 任务 | 预计工时 |
|------|------|----------|
| 1 | 实现 academic-pipeline 全流程串行调度 | 4 天 |
| 2 | 会话恢复 / Material Passport 管理 | 3 天 |
| 3 | 外部 API 集成（Semantic Scholar / OpenAlex / Crossref / Kimi） | 4 天 |
| 4 | LaTeX 模板支持（APA 7.0 / Chicago / IEEE） | 2 天 |
| 5 | Docker 部署方案 | 1 天 |

**预计总工时**: 14 天

---

## 8. 与上游 ARS 的关系

### 8.1 依赖关系图

```
┌──────────────────────────────────────┐
│  academic-research-skills (上游)     │
│  • SKILL.md / agents/*.md            │──── 读取解析 ────┐
│  • scripts/*.py (API 客户端)         │──── 直接复用 ────┤
│  • templates/ (格式模板)             │──── 复制引用 ────┤
└──────────────────────────────────────┘                  │
                                                          ▼
┌──────────────────────────────────────┐    ┌─────────────────────────┐
│  ars-web (本工程)                     │    │  Anthropic / Kimi /     │
│  • backend/services/                 │───▶│  Semantic Scholar API   │
│  • frontend/                         │    └─────────────────────────┘
└──────────────────────────────────────┘
```

### 8.2 兼容性原则

| 原则 | 说明 |
|------|------|
| **不修改上游文件** | ARS Web 只读取和解析，不修改 ARS 的任何文件 |
| **Python 脚本复用** | `ars-web/backend/clients/` 将 ARS 的 `scripts/` 中 API 客户端代码适配后搬入 |
| **版本追踪** | ARS Web 的技术文档和发布说明中应标注兼容的 ARS 版本 |

---

## 9. 风险与应对

| 风险 | 影响等级 | 应对策略 |
|------|----------|----------|
| **LLM 输出不可控** | 高 | Agent 阶段切换信号不稳定时，使用 XML 结构化标记包裹输出，便于解析 |
| **System Prompt 过长** | 中 | Token 成本高、响应慢，按阶段动态裁剪，仅加载当前阶段相关 Agent 指令 |
| **复杂 Agent 编排 bug** | 高 | 工作流中断时，每个阶段后自动保存 checkpoint，支持人工干预和恢复 |
| **Anthropic API 不稳定** | 中 | 服务中断时，实现重试机制 + 用户可见的错误提示 |
| **中文文献搜索质量** | 低 | Kimi 搜索结果不可靠时，保持与 ARS 相同的多源验证策略 |

---

## 10. 附录

### A. 环境变量

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | 是* | Anthropic API Key (*用户在前端提供，非服务端必需) |
| `MOONSHOT_API_KEY` | 否 | Kimi API Key (CNKI 中文搜索) |
| `S2_API_KEY` | 否 | Semantic Scholar API Key |
| `ARS_WEB_DB_PATH` | 否 | SQLite 数据库路径，默认 `./data/ars.db` |
| `ARS_WEB_SECRET_KEY` | 否 | Fernet 加密密钥，用于加密存储 API Key |
| `ARS_SKILLS_PATH` | 否 | ARS 技能目录路径，默认 `../academic-research-skills/` |

### B. 参考链接

- **ARS 上游项目**: [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills)
- **Anthropic Messages API**: https://docs.anthropic.com/en/api/messages
- **FastAPI SSE**: https://fastapi.tiangolo.com/advanced/events/
- **Pandoc**: https://pandoc.org/

### C. 文档修订历史

| 版本 | 日期 | 修订内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-06-11 | 初始版本 | ARS Web Team |

---

**文档结束** | 如有问题或建议，请提交 Issue 或 Pull Request
