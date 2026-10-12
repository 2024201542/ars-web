# 开发复盘：PDF 转文字 & PPT 功能是怎么做出来的

> 写于 2026-10-09。给"想搞懂这两块怎么实现的"看的。
> 每个环节按 **目标 → 现象 → 定位 → 改法 → 实测结果** 展开，数字都是当时跑出来的。
> 相关代码都能在 `ars-web/PROJECT_MAP.md` 里找到位置。

---

# 第一部分：PDF 转文字

## 0. 起点：一份"读不出内容"的扫描件

你当时的问题：`6 周其仁，中国农村改革：国家与土地所有权关系的变化.pdf`（50 页扫描件）在聊天里 @ 上去，模型说读不到内容；而另一份 `c048-199807012.pdf`（文字版）却正常。

**关键差别**（用 PyMuPDF 一查就清楚）：

| | 周其仁（读不出） | c048（正常） |
|---|---|---|
| 页数 | 50 | 12 |
| 每页内容 | 一张 1762×2688 的图，**文字层 0 字** | 正文文字 945 字/页 |
| 生成器 | Adobe Acrobat 7.0 Image Conversion Plug-in | Acrobat Distiller（正常排版） |

**结论**：这是"图片型 PDF"（扫描件），页面上根本没有文字对象，只有像素。任何"取文字层"的办法都取不到东西。

## 1. 第一代方案：`pdftotext`（失败，且失败得很隐蔽）

原代码（`services/workspace_manager.py` 的 PDF 分支）：

```python
r = subprocess.run(["pdftotext", str(file), "-"], capture_output=True, text=True, timeout=30)
if r.returncode == 0:
    return r.stdout
```

**现象**：文字版 PDF 也读不出来了，接口返回 406「无法预览此文件类型」。

**定位**：后端日志里反复出现

```
UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 8
Exception in thread Thread-85 (_readerthread)
```

原因两句话：
1. `text=True` 让 Python 用**系统默认编码**解码子进程输出；中文 Windows 上是 **GBK**。
2. `pdftotext` 输出的是 **UTF-8**。UTF-8 的中文按 GBK 解 → 崩。
3. 扫描件之所以"还能返回 50 个字符"，是因为它输出里恰好只有那点字节能被 GBK 解出来——**假成功**，比报错更误导。

**这一段的教训**：跨进程取文本，一定要显式指定编码（`encoding="utf-8", errors="replace"`），不要依赖 `text=True` 的默认行为。

## 2. 第二代方案：直接读文字层（PyMuPDF）

不再走外部命令，改用已经在依赖里的 **PyMuPDF**：

```python
layer = "\n".join(doc.load_page(i).get_text() for i in range(limit)).strip()
if len(layer) >= 120:          # 文字层够用
    return {"text": layer, "source": "text-layer", ...}
```

- 文字版 PDF：**0.1 秒**返回 17,155 字（原来走 pdftotext 要几百毫秒还带编码风险）
- 扫描件：文字层 0 字 → 落到下一步

**为什么留一个 120 字的门槛**：有的扫描件 PDF 会带一点点页码/页眉文字（比如 50 字），如果按"有字就用"，就会把这 50 字当成全文返回。门槛就是用来区分"真有文字层"和"只有零星残留"。

## 3. 第三代方案：OCR（把页面渲染成图片再识别）

### 3.1 选型：为什么不装 Tesseract

先把机器上有的能力全查了一遍（`shutil.which` + `importlib`）：

```
tesseract   -              # 没装
pdftotext   OK  (MiKTeX)
rapidocr_onnxruntime  OK   # 已装
onnxruntime OK  1.29.0
pymupdf     OK  1.28.2
PIL/cv2/numpy OK
```

**RapidOCR** 正好可用：纯 CPU、基于 onnxruntime、自带中文模型、**不需要额外装 Tesseract 和语言包**。这就是选它的全部理由——能用现成的就别装新东西。

### 3.2 参数不是拍脑袋，是量出来的

同一页（第 2 页）试了三种配置：

| 配置 | 耗时 | 结果 |
|---|---|---|
| dpi200 + 默认检测 | 6.11s | 32 行 / 1153 字（干净） |
| dpi150 + 默认检测 | 5.50s | 35 行 / 1227 字，但**识别到页眉噪点**（多了 "HSERIES" 之类） |
| dpi200 关闭检测 | 5.88s | 与第一种相同 |

速度几乎一样（都是 CPU 上的模型推理，瓶颈不在分辨率），所以选 **dpi200 + 默认检测**：清晰度换取质量，代价可忽略。

第一页实测输出：

```
中国农村改革：国家与土地
所有权关系的变化
一个经济制度变迁史的回顾
中国的经济改革正在广泛地改变资源利用的产权形式和效率。这场
弛。本文讨论这场大变革的发源一农村改革的经验。
```

术语、脚注、标点都基本正确。

### 3.3 最硬的约束：5 秒/页 × 50 页 = 5 分钟

**这是整个设计的分水岭**。不能做成"点一下，等五分钟"——HTTP 会超时、用户会以为死机。所以做了三件事：

**(a) 逐页缓存**（`data/ocr_cache/<指纹>.json`）

```python
def _fingerprint(path):          # 路径 + 大小 + 修改时间
    raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]
```

文件一改，指纹变，缓存自动失效——不用手动清。同一份文件永不重复识别。

**(b) 单次只识别 4 个新页**（约 20 秒，能接受的等待）

```python
SYNC_MAX_NEW_PAGES = 4     # 一个请求里最多新识别几页
```

读一次，先给你前几页能用的内容；再读一次，从**还没识别的那页**继续往后补。

**(c) 后台预热**

```python
threading.Thread(target=run, name="ocr-warm", daemon=True).start()
```

确认是扫描件后，趁你在看/在问别的，后台把后面的页慢慢识别完。

实测：

```
扫描件 首次 3 页  16.2s
再读一次         0.04s   （缓存命中）
请求 8 页         已识别 8 页（只补了 5 个新页）
```

### 3.4 三个"用着才发现"的问题

| 现象 | 原因 | 改法 |
|---|---|---|
| 读不出时界面只说"读不出"，模型拿不到任何信息 | 原来 OCR 无结果就 `return None` | 明确返回一句说明：「这份 PDF 没有文字层，OCR 也没识别出可用文字——可能是纯图片页或扫描质量太差」 |
| 每次都要等 OCR 才开始 | 只有"读正文"才触发预热 | **预览扫描件时就启动预热**（`/files/pdf-ocr` 进度接口顺手调 `warm_pages`） |
| 整份永远只识别前 12 页 | `warm_pages` 每次都从第 0 页开始扫 | 改成"从第一篇**未识别**的页继续"，多次调用可把整份读完（实测从 12 → 32 → 44 → **50/50**） |

## 4. 成功带来的新问题（这段最值得记住）

OCR 能读全之后，你反馈"**还是读取不了**"。我一探，真相很讽刺：

```
运行中后端读那份扫描件：56395 字，OCR 已识别 50/50 页   ← 识别完全成功
但 middleware/validation.py：message 上限 = 50000 字符
→ 56395 > 50000 → 整条消息被拒：HTTP 400「输入长度超过限制」
```

**我上一步的改进（读全文档）顶破了下一步的限制（输入上限）**，对外表现却是同一句话："读不出来"。

改法（两层配合，不能只改一层）：

| 层 | 改动 | 为什么 |
|---|---|---|
| 后端 | `message` 上限 50000 → **200000**（中间件 + 请求模型同步改） | 一份 50 页扫描件 OCR 后 5–6 万字，上限必须留出余量；两处不同步会变成 422 |
| 前端 | 注入附件时**单篇截 30000 字、合计 45000 字**，并提示「已转成文字 56395 字，本次注入前 30000 字」 | 上限放开不等于该把 6 万字全塞给模型（费 token、挤上下文）；截断要**可见**，不能静默 |

**通用教训**：端到端链路上任何一层的"上限/超时/编码"，都要用**真实最坏样本**（这里就是 50 页扫描件的全文）去撞一遍。只测"能不能解析"是不够的，得测"解析完能不能送出去"。

## 5. 最终形态（一句话流程）

```
取文字层（PyMuPDF）
   ├─ ≥120 字 → 直接用（文字版，0.1s）
   └─ 不足    → OCR（RapidOCR，dpi200）
                 ├─ 命中逐页缓存 → 立即返回
                 ├─ 新识别 4 页  → 返回「已识别前 X/Y 页」
                 └─ 后台继续补页 → 下次读更多
       结果带标注：[这份 PDF 是扫描件，正文由 OCR 识别，已识别前 X/Y 页]
```

实测终态：

| 文件 | 结果 |
|---|---|
| c048（文字版） | 17,155 字 / 0.1 秒，走文字层 |
| 周其仁（50 页扫描件） | **56,395 字 / 50 页全识别**，走 OCR + 缓存 |

> 附：PDF 的**预览**是另一条路（浏览器里 pdf.js 渲染），踩的是另一个坑——扫描件用 JBIG2 压缩，pdf.js 缺 wasm 解码器导致整页空白，修法是把 `pdfjs-dist/wasm/` 拷进产物并传 `wasmUrl`。与"转文字"是两套独立机制，别混。

---

# 第二部分：PPT 功能是怎么加进去的

## 0. 先写方案，再写代码

第一步不是动手，而是产出 `开发日记/2026-10-09 PPT创作功能实现方案.md`：调研开源方案、定技术路线、把实现拆成 10 步、写清 JSON 结构和提示词草案、列风险。

**调研结论**（决定后面所有事）：

| 方案 | 取舍 |
|---|---|
| **python-pptx** ✅ | 纯 Python 服务端生成真 `.pptx`，可开模板保留主题；和项目已有的"生成 Word（python-docx）"是同一条路线 |
| PptxGenJS | Node 库，后端是 Python，混栈不值 |
| [Presenton](https://github.com/presenton/presenton) | 独立应用，只借它的大纲提示词思路 |
| [PPTAgent](https://github.com/icip-cas/PPTAgent) | "参考模板→保真填充"最好但重，列为三期方向 |
| Marp / Slidev / reveal.js | 出的是 HTML 幻灯片，不是 WPS 能改的 pptx |

**核心设计**：模型只负责"出结构化大纲（JSON）"，**文件由代码生成**。这样可控、可复现、可编辑，不指望模型直接吐二进制。

## 1. 三代交互，一路被你的真实用法推着走

| 代 | 形态 | 你的反馈 | 结果 |
|---|---|---|---|
| 一代 | 只有"生成文档"按钮 | "这个好像不是真的能生成 ppt" | 模型当时确实说"我生成不了 .pptx"——**是它不知道界面已有能力**，于是加了 `CAPABILITY_LINE` 告诉它 |
| 二代 | 回复操作条里加「生成 PPT」（页数/模板可选） | "放在这里感觉不好，最好一句话就能生成" | 做了三代 |
| 三代 | **对话框说一句**「根据这个写个 ppt」→ 自动生成 → 落到附件所在文件夹 | — | 实测：13 页，写进 `土地改革论文写作/` |

## 2. 服务端三件套

**(a) `services/pptx_builder.py`：大纲 → .pptx**

关键处理（每条都对应一个真实的坑）：

| 做什么 | 为什么 |
|---|---|
| 中文字体写 `a:ea`（不只 `font.name`） | python-pptx 的 `font.name` 只管西文；不写 `a:ea`，中文在 WPS 里会回退成宋体 |
| 要点 ≤7 条、每条 ≤40 字，**超出的挪进演讲备注** | 溢出会挤出版面；挪到备注既不丢内容也不破坏页面 |
| 版式没有标题占位符时**补一个文本框** | 首次测试末页"谢谢"凭空消失，就是空白版式没有 title placeholder |
| 模板模式沿用模板字体/主题，内置模式才设自己的 | 套学校模板时不能把人家配色改掉 |

**(b) `services/pptx_outline.py`：模型 → JSON（模型无关）**

- **模型无关**的关键：不给每家写一套调用，而是复用已有的统一调用层（`providers.py` 路由 + `idea_debate._stream_complete`，它已覆盖 OpenAI 兼容与 Anthropic 两种协议）。默认用你当前选中的模型。
- **解析容错**：剥 ```json 围栏 → 截取首尾大括号 → 失败则用标题/短横线启发式兜底（并标 `fallback`）。
- 四个模型实测都出大纲：DeepSeek 13 页/13.3s、千问 11 页/17.7s、Kimi K3 12 页/45.8s、Kimi K2.6 11 页/44.6s。

**(c) 接口 `POST /api/workspace/generate-ppt`**

照抄已有 `generate-doc` 的骨架（选消息 → 拼材料 → 生成 → 落工作区），这样交互和错误处理天然一致。

## 3. PPT 线踩的坑（按发现顺序）

| # | 现象 | 定位 | 改法 |
|---|---|---|---|
| 1 | 生成时报「不支持的文件类型: .pptx」 | `.pptx` 不在 `ALLOWED_FILE_EXTS` | 加进去（顺带解锁了"上传 .pptx 模板"） |
| 2 | Kimi 流式报 `DecodingError` | Moonshot 对 SSE 回 `content-encoding: br`（Brotli），httpx 流式+br 会炸 | 请求头加 `accept-encoding: identity` |
| 3 | Kimi 只出 2 页 | 思考型模型把正文放进 `reasoning_content`，解析到的是**思考中的半截 JSON 草稿** | 给 Moonshot 传 `thinking: {"type":"disabled"}`；解析**优先用 content**，失败再退回全文 |
| 4 | 慢模型报读超时 | 非流式调用要等整段返回 | 大纲生成改成**流式**（持续有分片，不会假超时） |
| 5 | 点「生成 PPT」报「所选消息没有可用的正文」 | 前端流式新消息用本地时间戳当 id，与库里 id 对不上 | 请求带 `text` 兜底，解析不到 id 就用它 |
| 6 | 说"写个 ppt"没反应 | 意图判断被我自己的"超 400 字不判"挡住了——附件正文几万字和用户原话在同一条 message 里 | 前端单独传 `user_text`，**意图只看用户原话** |
| 7 | 生成的文件跑到 `generated/` | 需求是"放到附件所在文件夹" | `save_generated_file(..., target_dir)`：按附件解析出目录，返回的 `path/source` 跟着对应根走 |

## 4. 让它可改：预览区闭环

生成完不能改，等于半成品。所以补了 `services/pptx_edit.py`：

```python
read_slides(path)   → 逐页 {title, bullets[{text, children}], notes}
write_slides(path, slides) → 只改文字，版式与主题不动
```

- 前端 `FilePreview.vue` 增加 pptx 分支：每页一个标题输入框 + 要点文本域（行首两空格=下一级）+ 备注框，顶部「写回 PPT」
- 接口：`GET /api/workspace/files/pptx-slides`（读）、`PUT`（写回）
- 实测：读 9 页 → 改标题/要点/备注 → 写回 → 重读确认生效

**设计取舍**：只改文字，不碰版式。这样套了学校模板的 PPT 改几个字不会把主题、字号、logo 弄乱。

## 5. 一句话生成的实现链路

```
你在对话框说："根据这个写一个 ppt 报告吧"（附件已 @）
   ↓ 前端把附件内容注入 message（单篇 ≤30000 字）+ 另传 user_text / attach_paths
后端 chat.py：
   ppt_chat.wants_ppt(user_text) → True
   ↓ 不走模型闲谈，直接：
   ppt_chat.condense_material(message)      # 保头保尾，论文摘要/引言在头、结论在尾
   ppt_chat.resolve_save_dir(attach_paths)  # 附件所在目录
   ppt_chat.build_and_save(...)             # 大纲 → pptx → 落盘（+ outline.json）
   ↓ 事件：phase_start → ppt_created → message（含页数与页面顺序）
前端：刷新左侧文件栏 + toast + 回复下方显示"已生成 PPT"卡片
```

实测：`根据这个写一个 ppt 报告吧` + 周其仁 PDF → **13 页 pptx**，落在 `土地改革论文写作/`，`source=local`，文件确认存在。

---

# 第三部分：这两条线共通的套路（可迁移）

1. **先探测，再动手**：先用小脚本把环境（有哪些库/命令）、文件（页数、文字层、编码）、接口（返回什么）量清楚，再改代码。这两条线里每一次"猜着改"都翻过车。
2. **分层兜底，每层都给得出解释**：文字层 → OCR → 明确说明"读不出"。永远不要让最底层返回一个沉默的 `None`。
3. **缓存要按"文件指纹"而不是文件名**：路径+大小+修改时间，文件一改自动失效。
4. **慢操作要切成"够用就好 + 后台补齐"**：单次 4 页 + 后台预热，而不是死等 5 分钟。
5. **成功可能顶破下一层的限制**（56k 字 vs 50k 上限）：端到端必须用**真实最坏样本**跑一遍。
6. **模型无关靠"统一调用层"**，不是给每家写一套：一次接线，DeepSeek/千问/Kimi 都能用。
7. **意图识别只看用户原话**：一个 prompt 里混着几万字附件时，任何"看整条消息"的判断都会被淹没。
8. **只改文字、不动版式**：涉及用户模板/主题时，这是最稳的编辑策略。
9. **先写方案文档再写代码**：PPT 这条线之所以顺，是因为先花了时间把选型、JSON 结构、10 个步骤写下来，后面基本是执行。

---

## 附：这两条线涉及的文件

| 文件 | 作用 |
|---|---|
| `backend/services/pdf_ocr.py` | PDF 文字提取：文字层 + OCR + 逐页缓存 + 后台预热 |
| `backend/services/pdf_preview.py` | PDF 按页出图（预览用） |
| `backend/services/pptx_builder.py` | 大纲 → .pptx（版式/字体/溢出/模板） |
| `backend/services/pptx_outline.py` | 模型 → 结构化大纲（提示词 + 容错解析 + 流式） |
| `backend/services/pptx_edit.py` | 读/写 pptx 文字（预览区可改） |
| `backend/services/ppt_chat.py` | 对话框一句生成：意图判断 / 材料浓缩 / 目录推断 / 生成落盘 |
| `backend/routers/workspace.py` | `generate-ppt`、`pptx-slides`(GET/PUT)、`pdf-ocr` 等接口 |
| `backend/routers/chat.py` | 意图分支 `ppt_job` + `ppt_created` 事件 |
| `backend/services/workspace_manager.py` | `get_content`（PDF 转文字入口）、`save_generated_file(target_dir)` |
| `frontend/src/components/FilePreview.vue` | PDF 预览（含 OCR 进度）、PPT 逐页编辑 |
| `frontend/src/components/ChatPanel.vue` | 附件注入与截断、生成 PPT 面板、对话生成结果卡片 |
