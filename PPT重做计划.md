# PPT 一键生成：重做计划（给 DeepSeek 分阶段执行）

> 写于 2026-10-12。前面的 PPT 模块（拼接引擎、视觉校正、截图建模板、万相配图）保留不删，新引擎做成另一条路，默认走新路。
> 效果样片：`开发日记/截图/ppt-新方案/`（`new-01.png`～`new-09.png`、四张 `对比-*.png`、`样片-人大模板53.pptx`）。
> 参考实现：`backend/scripts/ppt_canvas_demo.py`。第 2、4 阶段的函数可以直接从这里搬，这份脚本已经用人大模板 53 跑通 9 页。

---

## 一、为什么现在的效果比直接发给 AI 差

用 10-10 21:03 生成的讲解稿（19 页）逐页渲染后，看到这些问题：

1. **整句话塞进只放得下四五个字的装饰位。** 拼接引擎把模板里的「五角星图解」页当成普通要点页，十几页反复用它，一句 20 字的要点被截成「能索取过」「要国家，」。
2. **模板里的示例字没清干净。** 每张内容页多一个孤零零的「5」，顶部导航一直写着「绪论背景 / 研究思路 / 关键技术难点」，结尾页写成「04.谢谢」。
3. **先写字、后找版式。** 大纲提示词只告诉模型 5 种版式，也不告诉它每个格子能放几个字；版式是写完以后按要点条数猜的（`suggest_layout`）。直接问 AI 时，AI 是边想内容边排版，所以更顺。
4. **没有计划确认这一步。** 对话里一说「做 PPT」，`wants_ppt` 就直接出片，用户没机会先看页数和每页讲什么。
5. **材料只截头尾。** `condense_material` 保留前 18000 字和后 8000 字，中间章节直接丢掉。
6. **检查用的图是裁过的。** `pptx_render.render_pages` 用的 LibreOffice Kit `render` 命令，对 13.33 英寸宽的模板只画出左上约 75% 的区域（换 dpi 也一样）。模板缩略图和 qwen-vl 视觉校正看到的一直是半张图。改成 `convert` 先转 PDF、再用 PyMuPDF 出图后，整页完整。

结论：问题出在「把文字填进模板原有的设计页」这条路。设计页的格子是给示例字准备的，内容一变就对不上。

## 二、新思路

**模板只提供底板和配色，版式由程序画，AI 按每个格子的字数上限写内容。**

- **底板**：从模板里挑 4 页，即封面、转场（章节页）、内容页、结尾。内容页只留页眉、红条、校徽和页码，中间安全区清空。
- **版式**：程序自带 9 种内容版式（目录、卡片、对比、时间轴、金句、编号结论、要点、大数字、图文）。每种版式都写明字数上限，并按模板的颜色画出来。
- **计划**：模型先读材料，按版式清单出一份逐页计划（JSON），在对话里显示成表格。用户确认或改几句以后再出片。
- **量字**：写进去之前先估算行数，自动选字号。放不下就让模型改短一次，还放不下就截到标点，全文写进讲稿备注。
- **自检**：出片后检查有没有越界、重叠、残留的示例字，再渲染缩略图给用户看。

预期调用次数：计划 1 次（输入约 1 万 token、输出约 3000）+ 改短最多 1 次（约 1000）+ 每次改计划 1 次。不再调用视觉模型和万相，除非用户勾选。

## 三、执行规则（每个阶段开头都要遵守）

1. 一次只做一个阶段，做完跑该阶段的测试，测试全过再进下一阶段。
2. 只改本阶段列出的文件。老模块 `pptx_splice.py`、`ppt_template.py`、`ppt_vision.py`、`ppt_shot.py` 只允许 import，不改。
3. Windows 环境：命令用 `cmd /c "cd /d ... && ..."`；含中文或引号的 Python 写成临时 `.py` 文件再跑，跑完删掉；需要打印中文时先 `set PYTHONIOENCODING=utf-8`。
4. 改了 Python 要重启后端（在 `ars-web\backend` 下：`D:\Miniconda3\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000`，不要加 `--reload`）。
5. 不提交、不推送、不动云服务器。不往代码、日志里写任何 API key。
6. 每个阶段做完，在仓库外层 `工作日志.md` 记一条：你要什么、做了什么、怎么验证的。

---

## 阶段 0：修渲染（先做，后面都靠它看效果）

**文件**：`backend/services/pptx_render.py`，新增测试 `backend/tests/test_pptx_render.py`

**改法**：

- 新增 `_render_via_pdf(source, pages, dpi) -> dict[int, Path]`：
  1. `node cli.js convert --input <pptx> --output <tmp>.pdf`（同样串行加锁，超时 300 秒）；
  2. `import pymupdf`，逐页 `page.get_pixmap(dpi=dpi).save(...)`，写进原来的缓存目录 `page-<n>.png`；
  3. 删临时 PDF。
- `render_pages` 先走 `_render_via_pdf`；失败再退回原来的 `render` 命令。
- PDF 也缓存成 `deck.pdf`，同一文件请求不同页时不重复转换。
- `clear_cache()` 不变。改完调用一次，清掉旧的裁切缩略图。

**验收**：

- 渲染 `开发日记/截图/ppt-新方案/样片-人大模板53.pptx` 第 4 页：图片宽高比约 16:9，右侧 15% 区域里有非白像素（校徽）。
- 模板库里人大模板 53 的缩略图能看到右上角校徽和右侧水印。
- 测试在没有 kit 的机器上自动 `skip`。

---

## 阶段 1：模板底板档案（profile）

**新文件**：`backend/services/ppt_base.py`；测试 `backend/tests/test_ppt_base.py`

每个模板旁边存一份 `<id>.base.json`：

```json
{
  "version": 1,
  "slide_size": [13.33, 7.5],
  "pages": {"cover": 1, "section": 3, "content": 29, "end": 31},
  "safe_area": [0.74, 1.45, 12.6, 6.75],
  "colors": {"accent": "#9B1B30", "accent_soft": "#F6ECEE", "dark": "#262626", "gray": "#595959", "muted": "#8C8C8C"},
  "slots": {
    "cover":   {"title": "中国人民大学模板", "subtitle": "Thesis defense template for graduation project",
                "info": ["答辩学生", "指导老师"]},
    "section": {"index": "01", "title": "研究现状", "subs": ["摘要", "引言"]},
    "content": {"title": "请输入你的标题", "title_right_limit": 10.1},
    "end":     {"info": ["答辩学生", "指导老师"]}
  },
  "confirmed": false
}
```

`slots` 里记的是**模板原文**，用来在复制出来的页里找到那个文本框（按文字匹配，找不到再按字号最大、位置最上兜底）。

**函数**：

```python
def guess_base(pptx_path) -> dict          # 自动猜，confirmed=False
def load_base(tid) -> dict | None
def save_base(tid, base: dict) -> None      # 用户确认后 confirmed=True
def content_canvas(prs, src_slide, base, title, page_no)   # 复制内容页并清空安全区
def is_junk_text(text: str) -> bool         # 识别残留示例字
```

**自动猜的规则**（只需猜个大概，最后由用户在界面上确认）：

- 封面 = 第 1 页；结尾 = 最后一页。
- 转场页 = 有一个 ≥40pt 的「01/02/…」数字框、文本框不超过 6 个的页，取第一张。
- 内容页 = 顶部 1.5 英寸内有标题框和一条横线、安全区里的形状最少的页。
- 安全区 = 顶部元素最低处 + 0.3 英寸，到底部页脚最高处 − 0.2 英寸；左右各留 0.7 英寸。
- 颜色：统计所有形状的纯色填充，去掉白、灰、黑，出现最多的当 `accent`；`accent_soft` 是 accent 和白色按 1:9 混合。
- `content_canvas` 清空规则：形状中心在安全区内且高度大于 0.6 英寸的删掉；页脚里的日期清空，页码改成实际页号。

**残留示例字**（`is_junk_text` 命中就删框或清空）：`请输入|请在此|点击(输入|添加|此处)|Add your text|Type Your|Click here|此部分内容|您的内容打在这里|苗猫|HSVmode|XXX|xxx|Thesis defense|2025/5/23`，以及只有一个数字的框（例如「5」），但页码占位符除外。

**验收**：

- `guess_base` 对人大模板 53 给出封面 1、结尾 31；转场页和内容页落在 3/9/14/19/24 和内容页之中，并且对这页执行 `content_canvas` 以后，安全区里没有形状。
- 对 5 套人大模板和 6 套内置主题都能跑完，不报错。
- 内置主题的 `.base.json` 手工确认好以后放在 `assets/ppt_templates/builtin/`。

---

## 阶段 2：版式库

**新文件**：`backend/services/ppt_layouts.py`；测试 `backend/tests/test_ppt_layouts.py`

从 `scripts/ppt_canvas_demo.py` 搬这些函数：`_em`、`fit_pt`、`text_box`、`rect`、`badge`，以及 `layout_toc / layout_cards / layout_compare / layout_timeline / layout_quote / layout_numbered`。新增 `layout_bullets / layout_bignum / layout_image_text`。所有颜色从 `base["colors"]` 读，安全区从 `base["safe_area"]` 读，不写死。

**版式清单与字数上限**（按 13.33 英寸宽；10 英寸宽的模板按宽度比例缩，向下取整）：

| 版式 `layout` | 用在什么内容 | 字段与上限 |
|---|---|---|
| `toc` | 目录 | `items` 3–6 项；`label` ≤6 字，`desc` ≤12 字 |
| `cards` | 2–4 个并列要点 | `cards[].key` ≤6 字，`cards[].desc` ≤28 字；`takeaway` ≤34 字，可空 |
| `compare` | 前后、正反、两派对比 | `left/right.head` ≤8 字；每栏 `points` 2–4 条，每条 ≤18 字 |
| `timeline` | 年份、阶段、步骤 | `nodes` 3–6 个；`year` ≤6 字，`head` ≤6 字，`desc` ≤10 字 |
| `quote` | 原文金句、核心判断 | `quote` ≤40 字，`source` ≤20 字，`note` ≤40 字 |
| `numbered` | 结论、建议、步骤 | `rows` 2–4 行；`head` ≤9 字，`desc` ≤30 字 |
| `bullets` | 实在归不了类的要点 | `points` 3–5 条，每条 ≤30 字 |
| `bignum` | 有关键数字 | `stats` 1–3 个；`value` ≤6 字符，`label` ≤10 字，`desc` ≤24 字 |
| `image_text` | 有配图 | `image` 图片序号；`points` 2–4 条，每条 ≤24 字 |
| `cover` | 封面 | `title` ≤14 字，`subtitle` ≤22 字，`info` ≤2 行，每行 ≤16 字 |
| `section` | 章节页 | `index` 如 "01"，`title` ≤6 字，`subs` ≤3 个，每个 ≤10 字 |
| `end` | 结尾 | `info` ≤2 行 |

内容页标题统一 ≤20 字，最好写成一句结论，例如「所有权悖论：产权离不开国家，也容易被国家侵蚀」。

**代码要求**：

- 上限写成一张表 `LAYOUT_SPECS`，供第 3 阶段生成提示词、做校验，也供前端显示字数，三处共用。
- 每个 `layout_*` 只往安全区里画；放不下时抛 `Overflow(field, text, limit)`，不要偷偷缩到看不清。
- 字号下限：正文 13pt，标题 18pt。
- 换行时避免最后一行只剩 1–2 个字：`fit_pt` 估算出孤字时，把字号降 1pt 再试，降不动就报 `Overflow`，交给改短那一步。

**验收**：

- 每种版式用上限内的假数据画一页，所有文本框都在安全区内，两两不重叠。
- 超出上限 1.5 倍的字抛 `Overflow`。
- 拿 `ppt_canvas_demo.py` 里的数据重画，和样片 `new-02.png`～`new-08.png` 基本一致。

---

## 阶段 3：读材料 → 出计划

**新文件**：`backend/services/ppt_plan.py`；测试 `backend/tests/test_ppt_plan.py`

### 3.1 整理材料 `digest_material(text, limit=14000) -> str`

替代只截头尾的做法：

1. 按标题切节，识别 `#`、`一、`、`（一）`、`第X章`、`1.`、`1.1` 这类开头。
2. 每节保留：标题、开头 600 字，以及节内含年份、百分比、数字、引号和「因此 / 总之 / 本文认为」的句子。
3. 按节数平均分配字数，总长不超过 `limit`。摘要、引言和结论各多给 1.5 倍。
4. 材料本身短于 `limit` 就原样返回。

### 3.2 计划 JSON

```json
{
  "title": "国家与土地产权关系的变化",
  "subtitle": "中国农村改革的经济制度变迁史回顾",
  "minutes": 10,
  "slides": [
    {"layout": "cover", "title": "国家与土地产权关系的变化", "subtitle": "中国农村改革的经济制度变迁史回顾", "info": ["汇报人：", "课程："]},
    {"layout": "toc", "title": "汇报框架", "items": [{"label": "理论框架", "desc": "国家与产权的悖论"}]},
    {"layout": "section", "index": "01", "title": "理论框架", "subs": ["所有权悖论", "诺斯难题与新假设"]},
    {"layout": "cards", "title": "所有权悖论：产权离不开国家，也容易被国家侵蚀",
     "cards": [{"key": "国家必要", "desc": "产权的界定与执行，离不开国家的强制力和法律保护。"}],
     "takeaway": "悖论：没有国家，产权无从保护；国家一旦介入，又容易造成所有权残缺。",
     "notes": "三张卡片依次讲必要性、自利性、残缺的概念，最后落到悖论。",
     "from": "第一节"},
    {"layout": "end", "info": ["汇报人：", "欢迎批评指正"]}
  ]
}
```

每张内容页都要有 `notes`（讲稿，60–120 字）和 `from`（来自原文哪一节，便于用户核对）。

### 3.3 提示词（`PLAN_PROMPT`，系统提示 + 用户内容）

系统提示要点（原样写进代码）：

```
你是学术汇报的 PPT 策划。读完材料，按下面的版式清单做一份逐页计划，只输出 JSON。
规则：
1. 默认 10–16 页；用户给了页数就按页数。第一页 cover，第二页 toc，最后一页 end。
2. 每一章前放一张 section；toc 的项和 section 一一对应。
3. 每张内容页只讲一件事，标题写成一句结论，不超过 20 字。
4. 按内容挑版式：有年份或阶段用 timeline；有前后、正反用 compare；2–4 个并列点用 cards；
   结论和建议用 numbered；原文里有分量的一句话用 quote；有关键数字用 bignum；其余用 bullets。
5. 同一种版式不要连续超过 2 页。
6. 每个字段都不能超过版式清单里的字数上限。宁可少写，也不要写满再挤。
7. 只用材料里有的事实和数字，不要编造；材料没给数字就不要用 bignum。
8. 每张内容页写 notes（60–120 字讲稿）和 from（来自原文哪一节）。
版式清单：
{由 LAYOUT_SPECS 自动生成：版式名、用途、每个字段的上限}
```

用户内容：`页数要求（可空）+ 用户补充要求（可空）+ 整理后的材料`。

调用方式与 `pptx_outline.generate_outline` 相同（复用 `idea_debate._stream_complete`），`max_tokens=6000`。JSON 解析失败时重试 1 次，再失败就返回错误，不要退回本地规则大纲。

### 3.4 校验与改短

```python
def validate_plan(plan) -> list[dict]       # [{"slide": 4, "field": "cards[1].desc", "text": "...", "limit": 28}]
async def shorten(plan, issues, model_id)  # 只把超限字段和上限发给模型，要求意思不变、改到上限内
def hard_trim(plan, issues)                # 兜底：截到上限内最后一个标点，原文追加到该页 notes
def normalize(plan)                        # 首页 cover、末页 end、未知版式改 bullets、数组条数夹到范围内
```

顺序：`normalize`、`validate`，超限就 `shorten`（最多 1 次），再 `validate`，还超限就 `hard_trim`。

### 3.5 改计划 `revise_plan(plan, instruction, model_id)`

用户在对话里说「第 5 页改成对比」「加一页讲乡镇企业」「整体压到 10 页」时调用。发送当前计划 JSON 和这句话，要求返回完整的新计划，之后同样走 3.4。

**验收**：

- 用 `C:\Users\28473\Desktop\学术写作工具测试\` 里那篇土地产权文章跑一次：页数 10–16，版式至少用到 5 种，`validate_plan` 返回空列表。
- 构造一个超限字段，`hard_trim` 后不超限，并且 notes 里能找到原文。
- `digest_material` 对 5 万字材料输出不超过 14000 字，并且每一节的标题都还在。

---

## 阶段 4：按计划出片

**新文件**：`backend/services/ppt_compose.py`；测试 `backend/tests/test_ppt_compose.py`

```python
def compose(base: dict, plan: dict, template_path, out_path, images: list[str] | None = None) -> dict:
    """返回 {"pages": n, "overflow": [...], "warnings": [...]}。"""
```

步骤（参考 `ppt_canvas_demo.build`）：

1. 打开模板，记下原有页数 N。
2. 按计划逐页处理：
   - `cover / section / end`：用 `pptx_splice._clone_slide` 复制底板页，按 `slots` 找框换字（`_set_text` 保留原样式），需要时把框拉宽到 `title_right_limit`，并把对齐方式设为左对齐。
   - 内容页：先 `content_canvas` 复制并清空，再调用对应的 `layout_*`。
   - 写 `notes` 到演讲备注。
3. 删掉模板原有的 N 页（`pptx_splice._delete_slides`）。
4. 整份过一遍 `is_junk_text`；装饰细线压到我们的文字框上就删掉（参考 demo 里的 `_drop_lines_over`）。
5. `Overflow` 不中断：这一页按上限截字重画，记进返回值的 `overflow`。

**验收**：

- 用 `ppt_canvas_demo.py` 里的数据组成一份计划，`compose` 产出的 9 页和样片一致。
- 生成后全文搜索不到任何残留示例字。
- 页脚页码和实际页号一致；封面和结尾不显示页码。

---

## 阶段 5：出片后自检

**新文件**：`backend/services/ppt_check.py`

```python
def check_deck(pptx_path, base) -> list[dict]   # [{"page": 5, "kind": "overflow|overlap|junk|offslide", "detail": "..."}]
```

- 几何检查：我们画的文本框不出安全区，两两不重叠；任何文本框不出页面。
- 文字检查：`is_junk_text` 命中、空标题、同一标题连续出现。
- 渲染：调用阶段 0 的 `render_pages` 出全部缩略图（dpi 72），供前端展示。
- 视觉模型复核默认关闭，保留开关 `ARS_PPT_VLM_CHECK=1`，打开时最多抽查 3 页。

---

## 阶段 6：对话里的流程和界面

### 6.1 后端

- `routers/chat.py`：`wants_ppt` 命中后不再直接 `build_and_save`，改成
  1. 发 `phase_start`「正在读材料、列 PPT 计划」；
  2. `digest_material` 加 `make_plan`；
  3. 计划存成 `<文件夹>/<标题>.ppt计划.json`；
  4. 发一个新事件 `ppt_plan`，内容为 `{"plan_path", "plan", "template_id"}`。
- `routers/template_library.py` 新增：
  - `POST /api/ppt/plan`：`{material_text | session_id+message_ids, pages, guidance, model}`，返回计划；
  - `POST /api/ppt/plan/revise`：`{plan_path, instruction, model}`，返回新计划；
  - `POST /api/ppt/compose`：`{plan_path, template_id, filename, save_to_local}`，出片，再跑 `check_deck`，返回 `{path, pages, overflow, issues, thumbs}`；
  - `GET/PUT /api/ppt/templates/{id}/base`：读写底板档案。
- `ppt_chat.build_and_save` 保留，加参数 `engine="splice"`。环境变量 `ARS_PPT_ENGINE` 默认为 `canvas`，设成 `splice` 时走老路。

### 6.2 前端

- `ChatPanel.vue`：收到 `ppt_plan` 时显示一张「PPT 计划卡」：
  - 顶部一行：模板选择（复用 `PptTemplatePicker`）、页数、预计时长；
  - 下面逐页列出页号、版式名（中文）、标题、要点摘要（每页一行，可展开）；
  - 按钮：「生成 PPT」调 `/compose`，「再改改」会在输入框里预填「把第 _ 页……」，发出去走 `/plan/revise`。
- 生成后在卡片下方显示缩略图条（`thumbs`），点开进 `PptView`。
- `PptView.vue`：左边是计划编辑（每页的字段可直接改，旁边显示「12/20」这类字数，超限变红），右边是缩略图，支持「只重画这一页」。
- `PptTemplatePicker.vue`：新增「设置底板」，展示模板全部页缩略图，用户给封面、转场、内容页、结尾各点一页，下方即时显示清空后的内容页预览，保存时调用 `PUT /base`。

**验收**（在浏览器 http://127.0.0.1:5173 里用 stu01 走一遍）：

1. @ 上土地产权那篇文章，说「做个 PPT，12 页左右」，对话里出现计划卡，不直接出片。
2. 说「第 6 页改成时间轴」，计划卡刷新，只有第 6 页变化。
3. 选人大模板 53，点「生成 PPT」，30 秒内出片，缩略图里看不到截字、重叠和示例字。
4. 换一套人大模板（例如 55），先「设置底板」再生成，配色跟着变。

---

## 阶段 7：加模板的流程（给你自己找来的模板用）

1. 上传 `.pptx`（沿用现有上传接口）。
2. 后台跑 `guess_base`，前端弹出「设置底板」，让用户确认 4 页。大多数模板 1 分钟内能确认完。
3. 只有图片、字改不了的模板页不能当底板；截图建模板的功能保留，但不进入一键生成的默认流程。
4. 模板大于 20MB 时提示「文件较大，生成会慢一些」，不阻止上传。

---

## 八、建议的执行顺序和每段的大小

| 顺序 | 阶段 | 预计改动 | 做完能看到什么 |
|---|---|---|---|
| 1 | 0 修渲染 | 1 个文件约 60 行 | 模板缩略图变完整 |
| 2 | 2 版式库 | 新文件约 400 行（大半从 demo 搬） | 9 种版式的单页样张 |
| 3 | 1 底板档案 | 新文件约 250 行 | 人大模板 53 自动认出底板 |
| 4 | 4 出片 | 新文件约 200 行 | 手写计划能出整份 PPT |
| 5 | 3 出计划 | 新文件约 300 行 | 文章能变成计划 JSON |
| 6 | 5 自检 | 新文件约 120 行 | 出片后列出问题页 |
| 7 | 6 界面 | 后端约 150 行，前端约 400 行 | 对话里先看计划再出片 |
| 8 | 7 加模板 | 前端约 200 行 | 自己的模板也能用 |

先做 0、2、1、4，这四段不调用模型，DeepSeek 每段一次对话就能做完，用 `scripts/ppt_canvas_demo.py` 对照效果。第 5 步开始才接模型。

## 九、交给 DeepSeek 时的开场白（可直接复制）

```
请读 ars-web/PPT重做计划.md，只执行「阶段 X」。
参考实现在 ars-web/backend/scripts/ppt_canvas_demo.py，效果图在 开发日记/截图/ppt-新方案/。
遵守计划里的「执行规则」。做完跑本阶段测试，把结果和改了哪些文件告诉我，再在 工作日志.md 记一条。
不要读和本阶段无关的老 PPT 模块。
```
