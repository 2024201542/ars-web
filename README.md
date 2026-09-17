# ARS Web

为 [academic-research-skills](https://github.com/aramis/ars) (ARS) 学术研究技能套装提供的 Web 前端界面，让科研工作者通过浏览器即可使用 AI 辅助的深度研究、论文撰写、同行评审等功能。

## 架构概览

```
┌──────────────────────────────────────────────────────────┐
│                      Frontend (Vue 3)                     │
│   HomeView  →  WorkSessionView  →  ChatPanel (SSE)       │
│   SettingsView  │  ExportButton  │  ModeSelector          │
├──────────────────────────────────────────────────────────┤
│                    FastAPI Backend (:8000)                │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌────────────┐  │
│  │ session │ │   chat   │ │  skills   │ │  settings   │  │
│  │  CRUD   │ │  (SSE)   │ │   list    │ │   CRUD     │  │
│  └─────────┘ └────┬─────┘ └───────────┘ └────────────┘  │
│                   │                                       │
│         ┌─────────▼──────────┐                           │
│         │   ClaudeEngine     │  ← 子进程管理              │
│         │ (claude_engine.py) │    stdout 逐行解析          │
│         └─────────┬──────────┘    stream-json → SSE       │
│                   │                                       │
│         ┌─────────▼──────────┐                           │
│         │   Claude CLI v2.1  │  ← Node.js 子进程          │
│         │  (--print --verbose │    ~/.claude/settings.json │
│         │   --session-id ...) │    --add-dir ARS skills    │
│         └─────────┬──────────┘                           │
│                   │                                       │
│     ┌─────────────▼──────────────┐                       │
│     │     /v1/proxy (proxy.py)   │ ← Anthropic → OpenAI   │
│     │   格式翻译 + SSE 转发       │   协议转换层            │
│     └─────────────┬──────────────┘                       │
│                   │                                       │
│  ┌────────────────▼─────────────────────────────┐       │
│  │      StateTracker (SQLite, WAL mode)          │       │
│  │  sessions │ messages │ artifacts │ settings   │       │
│  └──────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                  ▼
    Anthropic API     DeepSeek API      Kimi / GLM / Qwen
    (原生协议)        (OpenAI 兼容)       (OpenAI 兼容)
```

**核心架构决策**：所有模型统一通过 **Claude CLI** 子进程驱动，而非直接调用各厂商 SDK。Claude CLI 提供多 Agent 协作、工具调用、Skill 系统和会话持久化能力。非 Anthropic 模型通过本地 `proxy.py` 路由做协议转换（Anthropic Messages → OpenAI Chat Completions）。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端框架 | Vue 3 + TypeScript | Composition API + `<script setup>` |
| 构建工具 | Vite 5 | HMR 开发体验 |
| UI | Tailwind CSS 3 | 原子化 CSS |
| 状态管理 | Pinia | sessions / settings 两个 store |
| 路由 | Vue Router 4 | 三页面 SPA |
| 流式渲染 | markdown-it + highlight.js | Markdown + 代码高亮 |
| 后端框架 | FastAPI | 异步 Web 框架 |
| 服务器 | Uvicorn | ASGI 服务器 |
| AI 驱动 | **Claude CLI** (Node.js) | 子进程模式，统一所有模型 |
| 协议转换 | Anthropic ↔ OpenAI | proxy.py 翻译层 |
| 数据库 | SQLite + aiosqlite | WAL 模式，单例连接复用 |
| 加密 | Fernet (cryptography) | API Key 静态加密存储 |
| 限流 | slowapi | 聊天 30次/分钟，导出 20次/小时 |
| 部署 | Docker Compose | 前端 nginx + 后端 uvicorn |

## 目录结构

```
ars-web/
├── backend/                     # FastAPI 后端
│   ├── main.py                  # 应用入口，注册路由和中间件
│   ├── config.py                # 配置管理（DB路径、加密、限流等）
│   ├── providers.py             # 模型/Provider 注册表（5厂商9模型）
│   ├── deps.py                  # 共享依赖（速率限制器）
│   ├── routers/
│   │   ├── session.py           # 会话 CRUD API
│   │   ├── chat.py              # 对话 SSE API（核心）
│   │   ├── skills.py            # 技能查询 API
│   │   ├── settings_router.py   # 用户设置 API
│   │   ├── export.py            # 文件导出 API
│   │   └── proxy.py             # Anthropic→OpenAI 协议翻译代理
│   ├── services/
│   │   ├── claude_engine.py     # Claude CLI 子进程引擎
│   │   ├── state_tracker.py     # SQLite 会话状态持久化
│   │   ├── skill_loader.py      # ARS SKILL.md 解析器
│   │   ├── agent_runner.py      # Agent 执行引擎（备用方案）
│   │   └── export_cleaner.py    # 导出文件定时清理
│   ├── models/
│   │   ├── message.py           # ChatRequest / Message 数据模型
│   │   ├── session.py           # 会话数据模型
│   │   └── skill.py             # 技能数据模型
│   └── clients/
│       ├── anthropic_client.py  # Anthropic SDK 封装（备用）
│       └── openai_client.py     # OpenAI SDK 封装（备用）
│
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── views/
│   │   │   ├── HomeView.vue         # 首页 / 技能选择
│   │   │   ├── WorkSessionView.vue  # 工作会话页（聊天 + 结果）
│   │   │   └── SettingsView.vue     # 设置页（API Key 配置）
│   │   ├── components/
│   │   │   ├── ChatPanel.vue        # 对话面板（SSE 流式）
│   │   │   ├── ResultViewer.vue     # 结果展示器
│   │   │   ├── ExportButton.vue     # 导出按钮
│   │   │   └── ModeSelector.vue     # 模式选择器
│   │   ├── api/index.ts             # 后端 API 调用封装
│   │   ├── stores/                  # Pinia 状态管理
│   │   ├── types/index.ts           # TypeScript 类型定义
│   │   └── router/index.ts          # 路由配置
│   └── nginx.conf                   # 生产环境 nginx 配置
│
├── docker-compose.yml           # 容器化部署编排
├── Dockerfile.backend           # 后端镜像
└── TECHNICAL_DESIGN.md          # 详细技术设计文档
```

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 22+（Claude CLI 需要）
- Claude CLI 已全局安装：`npm install -g @anthropic-ai/claude-code`

### 1. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 启动后端

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 启动前端

```bash
cd frontend
npm run dev
```

前端默认运行在 `http://localhost:5173`，后端在 `http://localhost:8000`。

### 5. 配置 API Key

打开浏览器访问 `http://localhost:5173`，进入**设置页面**，填入对应厂商的 API Key。Key 会以 Fernet 加密存储在 SQLite 中。

## API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/sessions` | 创建会话 |
| `GET` | `/api/sessions` | 列出会话 |
| `GET` | `/api/sessions/{id}` | 获取会话详情（含消息） |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `POST` | `/api/sessions/{id}/chat` | **发送消息（SSE 流式）** |
| `POST` | `/api/sessions/{id}/chat/stop` | 停止生成 |
| `GET` | `/api/skills` | 列出可用技能 |
| `GET` | `/api/models` | 列出可用模型 |
| `POST` | `/api/settings` | 保存设置 |
| `GET` | `/api/settings` | 读取设置 |
| `POST` | `/api/sessions/{id}/export` | 导出为文件 |
| `POST` | `/v1/proxy/v1/messages` | 协议翻译代理（内部使用） |
| `GET` | `/v1/proxy/v1/models` | 模型列表代理（内部使用） |

## 支持的模型

| 模型 ID | 名称 | 厂商 | 协议 |
|---------|------|------|------|
| `claude-sonnet-4-6` | Claude Sonnet 4.6 | Anthropic | Anthropic 原生 |
| `claude-opus-4-8` | Claude Opus 4.8 | Anthropic | Anthropic 原生 |
| `claude-haiku-4-5` | Claude Haiku 4.5 | Anthropic | Anthropic 原生 |
| `kimi-k2-0905-preview` | Kimi K2 | 月之暗面 | OpenAI 兼容 → 代理翻译 |
| `glm-4.6` | GLM-4.6 | 智谱 | OpenAI 兼容 → 代理翻译 |
| `deepseek-chat` | DeepSeek Chat | DeepSeek | OpenAI 兼容 → 代理翻译 |
| `deepseek-reasoner` | DeepSeek Reasoner | DeepSeek | OpenAI 兼容 → 代理翻译 |
| `qwen-max` | 通义千问 Max | 阿里云 | OpenAI 兼容 → 代理翻译 |
| `qwen-plus` | 通义千问 Plus | 阿里云 | OpenAI 兼容 → 代理翻译 |

## 架构原理

### 为什么用 Claude CLI 而不是直接调 SDK？

Claude CLI 原生提供了：

- **多 Agent 协作**：Research Agent、Writer Agent、Reviewer Agent 等自动编排
- **工具调用 (Tool Use)**：文件读写、Shell 命令、API 调用等
- **Skill 系统**：通过 `--add-dir` 加载 ARS 技能套装，原生 `/skill` 调用
- **会话持久化**：`--session-id` 管理多轮对话历史
- **统一接口**：所有模型（无论 Anthropic 还是其他）都通过同一套命令驱动

### 非 Anthropic 模型如何工作？

```
Claude CLI ──(Anthropic 格式)──→ proxy.py ──(OpenAI 格式)──→ DeepSeek/Kimi/GLM/Qwen
              stream-json ←──────── SSE 翻译 ←────────── OpenAI SSE chunk
```

`proxy.py` 将 Anthropic Messages API 的 `system` / `messages` / `stream` 字段翻译为 OpenAI Chat Completions 格式，并将 SSE chunk 反向翻译为 Anthropic stream-json 格式返回给 Claude CLI。

### 配置注入机制

每次发起对话时，`chat.py` 会：

1. 从 SQLite 读取当前模型和 API Key
2. 写入 `~/.claude/settings.json`（Claude CLI 的原生配置文件）
3. Claude CLI 子进程启动时自动读取该配置

对于非 Anthropic 模型，`ANTHROPIC_BASE_URL` 被设为 `http://localhost:8000/v1/proxy`，Claude CLI 发出的所有 API 请求都会经过本地的格式翻译代理。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ARS_SKILLS_PATH` | `../academic-research-skills` | ARS 技能套装路径 |
| `ARS_WEB_DB_PATH` | `backend/data/ars.db` | SQLite 数据库路径 |
| `ARS_WEB_SECRET_KEY` | 自动生成 | Fernet 加密密钥 |
| `ARS_WEB_PROXY_URL` | `http://localhost:8000/v1/proxy` | 代理端点地址 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## Docker 部署

```bash
docker compose up -d
```

前端运行在 80 端口（nginx），后端运行在 8000 端口。

## 相关文档

- [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) — 详细技术设计文档
- [.trae/documents/PRD.md](./.trae/documents/PRD.md) — 产品需求文档
- [.trae/documents/TECHNICAL_ARCHITECTURE.md](./.trae/documents/TECHNICAL_ARCHITECTURE.md) — 技术架构文档
