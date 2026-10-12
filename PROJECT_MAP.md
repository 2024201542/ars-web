# ARS Web 项目索引（PROJECT_MAP）

> 给人和 AI 协作者的地图。**改动前先读这一份**，通常不必再整文件通读源码。
> 维护约定：改了文件职责/接口/关键行为，就在对应行补一句。最后更新：2026-10-09。

## 0. 一句话架构

前端 Vue3（`frontend/`，Vite，hash 路由）→ FastAPI（`backend/`，SSE 流式）→ 模型层（Anthropic 原生 / OpenAI 兼容经 `proxy.py` 翻译 / Claude CLI 子进程）→ SQLite（`backend/data/ars.db`，连接池 WAL）。
生产/本地单进程时，后端同时把构建好的前端挂在 `http://127.0.0.1:8000/app/`。

## 1. 后端：入口与配置

| 文件 | 行数 | 职责 | 关键点 |
|---|---|---|---|
| `backend/main.py` | 113 | 应用入口 | 中间件顺序、路由注册、`/api/health`、**`/app` 静态挂载前端 dist** |
| `backend/config.py` | 117 | 路径与密钥 | `DB_PATH`（`ARS_WEB_DB_PATH`）、`WORKSPACE_DIR`、`ARS_EXPORT_DIR`、Fernet key 在 `data/.fernet_key` |
| `backend/providers.py` | — | 厂商/模型注册表 | 5 厂商 9 模型 + base_url；新增模型改这里 |
| `backend/deps.py` | — | slowapi 限流器 | 聊天 30/分、导出 20/时 |
| `backend/logging_config.py` | — | 日志 | 写 `backend/logs/ars-web.log`（**勿整读，用 tail**） |
| `backend/models/message.py` | 44 | 请求模型 | `ChatRequest`（含 `debate_rounds` / `debate_materials` / `summarize_*` / `open_path`）、`DebateSeat`（stance 上限 2000） |

## 2. 后端：路由层

| 文件 | 行数 | 职责 |
|---|---|---|
| `routers/chat.py` | 435 | **核心 SSE**：选引擎、prompt 拼装、`lit/debate/pipeline` 分支、事件透传、落库 |
| `routers/workspace.py` | 660 | 工作区：列表/内容/预览/下载/`pdf`/`pdf-page`/`pdf-info`/**`pdf-ocr`**/上传/新建/改名/删除/文件夹/搜索/`generate-doc`/**`generate-ppt`**/**`pptx-slides`（GET 读、PUT 写回）** |
| `routers/collab.py` | 1446 | 协作：邀请→接受→交回→预览→采纳/撤销 |
| `routers/session.py` | 81 | 会话 CRUD |
| `routers/auth.py` | 31 | 登录/登出/me（token 存 `settings` 表 `auth/auth_token/<token>`） |
| `routers/settings_router.py` | 77 | 用户设置 + `/settings/models`、`/settings/providers` |
| `routers/skills.py` | 30 | 技能列表/模式/配置 |
| `routers/export.py` | 188 | 导出 md/tex/docx（`EXPORT_DIR`） |
| `routers/share.py` | 228 | 只读分享链接 |
| `routers/admin.py` | 52 | 管理员统计/用户管理 |
| `routers/literature.py` | 28 | 文献检索入口 |
| `routers/proxy.py` | 252 | **Anthropic→OpenAI 翻译**（Claude CLI 请求经此转发到 DeepSeek/Kimi/GLM/Qwen） |
| `routers/template_library.py` | 340 | **PPT 模块（独立页面，不走会话）**：`GET/POST/DELETE /api/ppt/templates*`（列表/上传解析/删除/详情）、`GET /api/ppt/themes`、`POST /api/ppt/generate`（选模板→拼接；**不选模板时用所选主题对应的内置模板当版式库**）、`GET /api/ppt/templates/{id}/thumb.png`、`GET /api/ppt/preview.png`、`GET /api/ppt/render/status`、`GET /api/ppt/file` |

## 3. 后端：服务层（改动最常落在这里）

| 文件 | 行数 | 职责 | 改什么看这里 |
|---|---|---|---|
| `services/idea_debate.py` | 825 | **辩论与辩题** | `_stream_complete`（流式+【思考】/【回答】切分，`marker_mode=False` 用于辩题）、`_speech_prompt`、`stream_debate`（轮数/主持人指令/材料注入）、`stream_topic`、`parse_topic_plan`（容错模板复读、名/id 映射）、`stream_summary`/`summary_material`、hints 与轮间闸门 |
| `services/pdf_ocr.py` | 244 | **扫描件 OCR** | RapidOCR + 逐页缓存（`data/ocr_cache/<指纹>.json`）+ 单次 4 页 + 后台预热 + `progress()` |
| `services/pptx_builder.py` | 267 | **PPT 生成** | `build_pptx(outline, template)`：内置 16:9 主题或套 `.pptx` 模板；中文字体写 `a:ea`；要点/字数上限，溢出转演讲备注；`outline_from_markdown` 兜底 |
| `services/pptx_outline.py` | 206 | **PPT 大纲** | `build_outline_prompt` / `parse_outline`（剥围栏、模板残留过滤、启发式兜底）/ `generate_outline`（**模型无关**：流式调用、优先用 content 而非 reasoning、Kimi 自动关思考） |
| `services/pdf_preview.py` | 52 | PDF 按页出图 | `pdf_page_count`、`render_pdf_page`（PyMuPDF） |
| `services/workspace_manager.py` | 658 | 工作区解析与读写 | `resolve_file`/`get_local_root`（site 与 local 两种根）、**`get_content`（文本/docx→mammoth/pdf→文字层或 OCR）**、上传/新建/改名/删除/搜索 |
| `services/state_tracker.py` | 473 | SQLite 连接池 + 全部表 | sessions/messages/artifacts/settings/users…；`set_setting_ex` 存跨域 token；写操作串行 |
| `services/claude_engine.py` | 650 | Claude CLI 子进程 | Windows 用 `Popen`；stream-json 解析；UTF-8/GBK 兜底 |
| `services/user_manager.py` | 249 | 用户 | 注册/登录/哈希/token |
| `services/skill_loader.py` | 449 | 技能解析 | 读 ARS `SKILL.md`，出技能/模式 |
| `services/literature_search.py` | 485 | 文献检索 | OpenAlex + Crossref 定位；知网预留 |
| `services/pipeline_steps.py` | 242 | 全流程 11 步 | 步骤定义与提示 |
| `services/pptx_edit.py` | 190 | **PPT 读写** | `read_slides(path)` / `write_slides(path, slides)`：只改标题/要点/备注，不动版式主题；**文本框标题也认**（占位符优先，否则页面上部最靠上的大字）；两栏页用 `〔右栏〕` 分栏 |
| `services/ppt_theme.py` | 90 | **PPT 主题库** | 6 套配色/字体（学术红/学院蓝/松墨绿/极简黑白/暖橙/灰紫）；`outline_theme()` 转成大纲的 theme 字段 |
| `services/ppt_template.py` | 300 | **模板解析（M0 核心）** | `analyze_pptx()` 把一份 pptx 拆成"版式样本"并打标签（cover/toc/bullets-N/two-col/big-number/quote/section/end/image+text）、`pick_specimen()` 按标签挑样本、`structure_preview()` 出界面用的结构卡片；`is_text_candidate()` 是全模块共用的"什么算文本框"规则 |
| `services/pptx_splice.py` | 320 | **模板拼接（M1 核心）** | 克隆样本页（`deepcopy` 形状 + 图片关系重映射）→ 删掉模板原页 → 用样本段落当容器填字（保留缩进/间距/项目符号/字体）；两栏/三卡片按栏均分并把「标签：说明」拆行；要点超容量进备注 |
| `services/pptx_render.py` | 150 | **真实缩略图（M3）** | 调 DSH 自带 LibreOffice Kit（node + cli）把 pptx 渲成 PNG，按"文件指纹"缓存到 `data/ppt_render/<指纹>/page-N.png`；找不到渲染器则 `available()=False`，前端自动回退结构预览 |
| `services/ppt_chat.py` | 191 | **对话框生成 PPT** | `wants_ppt()` 意图判断（只看用户原话）、`condense_material()` 保头保尾、`resolve_save_dir()` 推断"附件所在文件夹"、`build_and_save()` 出片（**有模板走拼接、没模板用主题对应的内置版式库**）；REST 接口与对话框共用 |
| `services/ppt_shot.py` | 260 | **② 截图变模板** | RapidOCR 认字 → 按框擦掉原文字（框外中位色填充）得到干净底图 → 铺满整页并**在原位放可编辑文本框** → OpenCV 找出照片区、抹掉并放图片占位矩形 → 产出可被解析入库的 pptx |
| `services/ppt_vision.py` | 265 | **③ 视觉排版** | 模板页渲染成 PNG → qwen-vl 返回 `{title_boxes, body_boxes, photo_boxes}` → 与文本框匹配改写 `title_i/bodies_i/image_i`；按"文件指纹+页"缓存；**自动识别模型返回的是像素还是归一化坐标** |
| `services/ppt_image.py` | 170 | **图像素材** | 元信息与方位分类（横/竖/方/超宽/超长）、`fit_to_slot()` 按图片位比例裁剪（不拉伸）、`extract_from_pdf()` 从 PDF 抽图表（过滤小图/重复图）、`pick_for_slot()` 按位挑图 |
| `services/ppt_library.py` | 130 | **模板库服务层** | 内置/用户模板的枚举、查找、`builtin_for_theme()`、`summary()`；**页面接口与对话框共用**；读取时按 `ANALYSIS_VERSION` **自动重新解析旧分析结果** |
| `services/entry_prompt.py` | 77 | 入口与模式提示 | `MODE_LINES` 各入口一句话；**`CAPABILITY_LINE`：告诉模型界面能出真 pptx**（避免它答"生成不了二进制文档"） |
| `services/docx_text.py` | 183 | Word 读写 | 提取正文 / 写回保留格式 |
| `services/edit_snapshot.py` | 138 | 改动备份 | Agent 改文件的快照与撤销 |
| `services/export_cleaner.py` | 65 | 导出清理 | 24 小时过期清理 |
| `services/agent_runner.py` | 333 | 备用 Agent 执行 | 非 Claude CLI 路径 |
| `services/provider_status.py` | 19 | 厂商 key 状态 | 设置页"已接入"判断 |

## 4. 前端

| 文件 | 行数 | 职责 |
|---|---|---|
| `components/ChatPanel.vue` | **1421** | **最重**：输入栏、辩论设置（模型/立场/轮数/选文章）、生成辩题、消息渲染（辩论卡片、实时流卡片、法官/总结）。改交互基本都在这 |
| `components/FilePreview.vue` | 620 | 中间预览：md/csv/html、PDF 逐页画布+文字层、图片、docx 排版、**pptx 逐页文字（可就地改并写回）**；状态栏显示"文字可选中 / 扫描图片 / OCR x/y / N 页幻灯片" |
| `components/FileTree.vue` | 529 | 左侧文件树：本机文件夹、上传、拖拽、新建/改名/删除 |
| `components/AppSidebar.vue` | 349 | 左侧栏：新建、历史、技能入口 |
| `components/CollabButton.vue` | 649 | 协作入口与状态（占用/待审） |
| `views/WorkSessionView.vue` | 470 | 三栏布局（文件 / 预览 / 对话），装配各组件 |
| `composables/useChatStream.ts` | 168 | SSE 解析：`message/progress/phase_start/files_changed/pipeline/literature/debate_topic/debate_pause/debate_voice/debate_stream/debate_delta/done/error`；`liveStream` 逐字状态 |
| `api/index.ts` | 335 | 全部 HTTP 封装（`request`、`withAuthToken`、`chatSSE`、workspace/settings/collab） |
| `types/index.ts` | 154 | 类型：`DebatePayload`（含 rounds/materials）、`DebateVoice`、`Message` |
| `components/FileMentionPopup.vue` | 87 | `@` 选文件 |
| `utils/pdfTextSelection.ts` | 127 | PDF 文字层选中/复制对齐 |
| `utils/mermaidBlocks.ts` | 42 | 预览里的 mermaid 渲染 |
| `utils/composerModes.ts` / `utils/constants.ts` / `utils/startOptions.ts` | 133/36/188 | 入口菜单（`DIRECT_ENTRIES` 会话入口 / **`MODULE_ENTRIES` 独立模块入口**）、技能路由与标签、起始选项 |
| `views/PptView.vue` | 330 | **模板库管理页**（路由 `/ppt`，入口菜单里的「模板库」）：模板卡片（真封面图 + 结构预览兜底）、上传/删除、按模板或按主题生成 |
| `components/PptTemplatePicker.vue` | 250 | **模板选择面板**（对话框里「模板：xxx」按钮打开）：左边列表（真封面）、右边整页预览（翻页）、上传/删除、「用这套模板」、页数选择 |
| `stores/{session,settings,workspace,auth,pendingStart}.ts` | 37–85 | Pinia 状态 |
| 其余 components/views | — | ToastContainer、ErrorBoundary、ShareButton、ExportButton、GenerateDocButton、ModeSelector、SkillGuide、ConversationHistory、ChatInput、ChatMessage、ResultViewer；Home/Settings/Login/Admin/Share/CollabInvite 视图 |

## 5. 四条关键数据流（改前先对号入座）

1. **聊天**：`ChatPanel.doSend`（附件读内容拼进 prompt）→ `useChatStream.sendMessage` → `POST /api/sessions/{id}/chat`(SSE) → `chat.py` 选引擎 → 事件流 → 前端累积渲染。
2. **辩论**：辩论设置（模型+立场+轮数）→ `debateRequest()` 打包 `seats/rounds/materials` → `chat.py` 的 debate 分支 → `stream_debate`（逐轮发言；每轮前消费主持人指令并出 `kind=host` 卡片；材料按篇 3000 字/合计 9000 字注入）→ 前端渲染 voices + `liveStream`。
3. **辩题**：`draftTopic()`（面板选的文章 + 输入框 @ 的附件，单篇 8000/合计 16000 字）→ `action=topic` → `stream_topic`（`marker_mode=False` 纯正文流）→ `debate_topic` + `applyPlan` 填立场。
4. **PDF 预览与 OCR**：`FilePreview` → `/files/pdf` 取原件 → pdfjs 渲染（wasm 在 `/app/pdfjs/wasm/`）；状态栏轮询 `/files/pdf-ocr`；若被当作文本读取（聊天附件/辩题/辩论材料）则走 `pdf_ocr`。

## 6. 常见改动的落点

| 要改什么 | 落点 |
|---|---|
| PPT 生成规则（版式/字体/上限） | `services/pptx_builder.py`（MAX_BULLETS / MAX_BULLET_CHARS / DEFAULT_FONT / DEFAULT_ACCENT） |
| PPT 大纲规则与提示词 | `services/pptx_outline.py`（`OUTLINE_SYSTEM` / `_SCHEMA_HINT` / `build_outline_prompt`） |
| 新增模型/厂商（如更多 Kimi） | `backend/providers.py` 的 `MODELS` 加一行（`provider` 用 `moonshot`） |
| 辩题规则/格式 | `idea_debate.stream_topic` + `parse_topic_plan`（前端不用动） |
| 轮数/主持人/材料 | `stream_debate`（后端）+ `ChatPanel` 辩论设置区 |
| 辩论卡片外观 | `ChatPanel.vue` 的 `debateVoices/debatePlanOf/liveStream` 渲染段 |
| PDF 预览行为 | `FilePreview.vue` + `pdf_preview.py` / `pdf_ocr.py` |
| 文件读取能力（新格式） | `workspace_manager.get_content` |
| 新增接口 | `routers/*.py` + `frontend/src/api/index.ts` + `types/index.ts` |
| 新模型/厂商 | `backend/providers.py`（+ 设置页自动出现） |
| 前端打包路径 | `frontend/vite.config.ts` 的 `base`（`VITE_APP_BASE=/app/`） |

## 7. 协作约定（省 token / 省时间，给 AI 协作者）

1. **先读本文件**，再决定要不要读源码；定位用 `grep`，不要整文件通读（`ChatPanel.vue` 1421 行、`collab.py` 1446 行）。
2. 读大文件用 `offset/limit` 取片段；一次改动只读相邻 30–60 行。
3. **工具输出限流**：命令一律加 `2>$null`；列表加 `| Select-Object -First N`；`git` 加 `-c core.safecrlf=false` 或忽略 CRLF 警告。
4. **日志**：`backend/logs/ars-web.log` 已 2MB，只看 `Get-Content -Tail 30`；不要把 uvicorn 的异常堆栈整段贴回上下文。
5. **不要在本会话里起后端**：它会把大段 traceback 打进上下文；用 `ars-web-start.bat`（仓库根）在会话外启动，或用临时端口起一次、测完立刻关。
6. 构建前端用安静模式：`npx vite build --logLevel warn`，只要结果不要资产清单。
7. 一次脚本做多件事（探测/校验合并），减少往返。
8. **临时脚本必须自己退出**：结尾写 `os._exit(0)`（并先 `sys.stdout.flush()`）；不要为了拿 user_id 去 `tracker._ensure_initialized()`——aiosqlite 的连接线程不是守护线程，进程会挂住不退出。优先用 `httpx.ASGITransport(app)` 直连接口，或直接用 `sqlite3` 只读打开 `data/ars.db`。
9. **后台任务必须当场收尾**（血的教训：有脚本被挂起后跑了一个多小时）：
   - 启动时立刻记下 job_id；**同一轮结束前 `job_list` 检查一遍**，只允许留下"就是要在会话外继续跑"的服务（推荐用仓库根 `ars-web-start.bat` 由用户自行启动）。
   - 用完马上 `job_kill`，别指望它自己退出——被挂起的进程会一直占着工具槽位和机器。
   - 收尾清单：`job_list` 里全部是 killed/completed → `Get-Process python` 无残留 → 临时脚本与日志已删。
10. **慢模型只验一次**：逻辑正确性用假模型服务或快速模型（DeepSeek）验证，慢速思考型模型（Kimi K3 等）只在"确认兼容性"时跑一次。
11. **长会话及时换新会话**：每轮都会重发全部历史，会话越长越贵；而且界面在会话过大时（实测 10 MB / 4780 条记录）**只能显示最近一段**，早期消息在文件里但看不到。收尾时把结论写进本节或 `工作日志.md`，再开新会话继续。

## 8. 已知坑（踩过的，别再踩）

| 现象 | 原因 | 处理 |
|---|---|---|
| `attempt to write a readonly database` | 进程被外部沙箱限制写入工作区，或目录缺写权限 | 用仓库根 `ars-web-start.bat` 在会话外启动；它会先清 8000 端口并做写入自检 |
| PDF 文本读出乱码/为空 | 旧代码 `pdftotext` 用系统 GBK 解码 UTF-8 | 已改为 pymupdf 读文字层 + OCR 兜底（`pdf_ocr`） |
| 扫描件预览全白 | pdfjs 缺 JBIG2/JPEG2000 的 wasm | 构建插件把 `pdfjs-dist/wasm/` 拷到 `dist/pdfjs/wasm/`，代码传 `wasmUrl` |
| 连续删除文件报 `destroy is not a function` | `PDFDocumentProxy` 没有 `destroy` | 清理统一走 `loadingTask.destroy()` |
| 辩题显示"一句话" | 模型照抄提示词里的格式示例 | 提示词去占位词 + `parse_topic_plan` 过滤模板残留 |
| 开始辩论报 `[object Object]` | 立场超 200 字触发 422，detail 是数组 | 上限提到 2000 + 前端截断 + 错误格式化 |
| 前端改了没生效 | 后端托管的是 `dist` 构建产物 | 在 `frontend/` 执行 `VITE_APP_BASE=/app/ npx vite build` 后硬刷新 |
| 端口 8000 被旧进程占着 | 上次的后端没退干净 | `ars-web-start.bat` 会自动清端口 |
| Kimi 流式报 `DecodingError` | Moonshot 对 SSE 回 `content-encoding: br`，httpx 流式+Brotli 会炸 | 请求头加 `accept-encoding: identity`（`_stream_complete`/`_complete` 已加） |
| Kimi 出大纲只 2 页 | 思考型模型把正文放进 `reasoning_content`，解析到的是思考中的 JSON 草稿 | 给 Moonshot 传 `thinking: {type: disabled}`；解析时优先 content，失败再退回全文 |
| 生成 pptx 报「不支持的文件类型」 | `.pptx` 原本不在 `ALLOWED_FILE_EXTS` | 已加入（同时解锁上传 `.pptx` 模板） |
| 模板解析把装饰矩形当成"空文本框" | 矩形也有 `has_text_frame`，解析出的"第 0 个文本框"是空框，结果版式全判成 section | `ppt_template.is_text_candidate()`：装饰形状（非占位符且无字）跳过；**解析与拼接必须共用这一条规则**，索引才对得上 |
| 用 `is` 比较 python-pptx 的 shape | 每次遍历 `slide.shapes` 都新建包装对象，`a is not b` 永远为真（导致标题被当正文重复读） | 比底层 XML：`a._element is not b._element` |
| 用 PowerShell `Set-Content` 改 Python 文件 | PowerShell 5 的 `-Encoding utf8` 会加 BOM → `SyntaxError: invalid non-printable character U+FEFF` | 改 Python 源码一律用编辑工具或 Python 自己写（`Path.write_text`） |
| LibreOffice Kit 渲染返回 0 张图 | 输出目录已存在（要求输出是新目录） | 渲染前换新目录（或先删旧目录） |
| 找不到"文本框标题"的 PPT | 很多模板不用占位符，标题就是普通文本框 | 标题启发式：页面上部（≤30% 高）最靠上的 ≥16pt 文本框；整页只有一两个大字时放宽（分节/结尾页） |
| 同一素材两次生成，一次 11 页一次只有 2 页 | 模型偶发退化大纲（页数极少、标题雷同） | `pptx_outline.is_degenerate()` 判定 + 自动重试一次（带"至少 N 页"的强要求）；`normalize_layouts()` 兜底第一页封面/最后一页结尾/无版式按要点数推断 |
| 模型把所有页都写成 content，整份一个样 | 模型不爱用版式字段 | `pptx_outline.suggest_layout()`：按要点形状自动升级（2 条→two-col、3 条独立→cards-3、≥3 条带年份→timeline、1 条长句→quote、1 条短数字→big-number），**只在模型没明确指定时替换** |
| LibreOffice Kit 渲染失败：`EEXIST: mkdir` | kit 要求输出目录**尚不存在**（它自己创建），而 `mkdtemp()` 会先建好 | 传一个"唯一但不存在"的路径，`finally` 里删掉 |
| 缩略图每次都要等 1–2 秒 | 渲染慢 | `data/ppt_render/<文件指纹>/page-N.png` 磁盘缓存；文件一改指纹变，自动失效 |
| 设计模板里要点写不进去 | "形状顺序第一个正文框"常是装饰小字/导航条 | 正文框改为优先取**面积最大**的文本框；竖排一串框按列表处理（一条要点一个框） |
| 模板预览一直显示"渲染失败" | **`<img>` 标签不会带 Authorization 头**，图片请求全被 401 挡掉；而项目里其他图片/下载 URL 都用了 `withAuthToken()`，新加的 PPT 三个 URL 忘了包 | 所有给 `<img>`/`<a>` 直接用的 URL 必须 `withAuthToken()`（后端 `get_user_id` 支持 `?token=` 回退）。踩过一次，别再踩 |
| 模板里的图片一个都找不到 | 设计模板的照片**包在组合里 / 做成形状的图片填充 / 当页面底图**，`shape_type == PICTURE` 全都漏掉（人大模板 35 页 = 0 个图片位） | 解析图片位一律**扫 XML 的 `a:blip`**；替换时按同一个序号设 `r:embed` |
| 配图功能上线后老模板不生效 | 模板库里的 `analysis.json` 是加字段之前生成的，缺 `image_i` | `ppt_template.ANALYSIS_VERSION` + `ppt_library._fresh()`：版本旧就**自动重新解析并写回**。以后加字段务必 +1 |
| 把校徽当配图位换掉 | 小长条装饰图（2.2×0.43in，比例 5.1）也被当成图片位 | `_usable_slot()`：排除满幅底图（>78%）与装饰小图/长条（<6% 或极端比例） |
| 截图模板被判成"结尾页" | `index == total-1` 规则对**单页**模板必然命中 | 改成 `index == total-1 and total > 1` |
| qwen-vl 返回的坐标对不上 | 提示里要求 0~1 归一化，**模型仍返回像素坐标**（x=1472 = 图宽） | `ppt_vision.normalize_boxes()`：任何值 >1.5 就按像素处理并除以渲染图尺寸 |
| 视觉区域匹配不到文本框 | 用 IoU 太严格：文本框通常只占模型画的内容区一小块 | 正文匹配改用**包含度**（intersection / 框面积），阈值 0.35 |
| 成品里留着"添加标题内容 / ADD A TITLE" | **有两类原因**：① 模板占位文字没被清（填字之外的框）② **那页是"整页导出成图片"的模板页，文字烘焙在图里，改不了**（人大模板-50 有 6 页是这种） | ① 通用占位文字清洗（`_scrub_placeholders`，只清"没写过"的框）② 解析时标 `image_only`（满幅图 ≥90% 且文本框 ≤4），挑版式与角色映射都跳过这种页；彻底解法是用 `ppt_shot` 的截图流水线把它重建为可编辑页 |
| 页面上文字与图重叠、看着乱 | 给没图位的页硬塞图片 | `_add_picture()` 只在"正文框 ≤2 且整套最多 3 页"时加，竖图走右侧竖条、横图走底部通栏 |
| 拼接后出现空白页 | 该页标题框选偏，一个字都没写进去 | `_ensure_not_empty()`：逐页检查，空页补一个文本框（标题 + 要点），并在 warnings 里说明 |
| 模板面板显示"没有可用的渲染器" | 面板一次请求 11 套封面 → 11 个 LibreOffice 并发互相拖超时；而接口把任何失败都写成"没有渲染器" | `pptx_render` 加**全局串行锁** + 记录真实失败原因；接口返回 503 + 原因；前端**只给选中项**拉真封面，失败给"重试" |
| 生成的 PPT 不出现在左侧文件树 | 没带附件时存进工作区 `generated/`，而文件树显示的是本机文件夹 | 没附件时**默认存进当前打开的本机文件夹**（`get_local_root`）；消息写明位置；前端收到 `ppt_created` 先把文件树切到 `local` 再刷新 |
| 对话里 @ 了扫描件却"读不出来" | 扫描件 OCR 后 5–6 万字，撞破 `MAX_INPUT_LENGTHS['message']=50000`，整条消息被 400 拒 | 上限提到 200000，前端单篇截 30000 字并提示；PDF 一律先转文字再用 |
| 点「生成 PPT」报「所选消息没有可用的正文」 | 前端流式新消息用本地时间戳 id，与库里 id 对不上 | 请求带 `text` 兜底，解析不到 id 就用它 |
