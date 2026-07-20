---
name: interview-transcriber
display_name: 音视频转文档
description: |
  音视频转文档全流程处理技能（支持视频与音频输入，也支持「一段音视频拆成多段文件」合并转录）。默认本地转录（Paraformer-large 魔搭社区中文模型（高精度），离线可用、无需 API Key；⚠️ 首次运行需联网下载本地模型 ~800MB + torch 推理栈，GPU 版约 2.7GB，耗时数分钟）。可选云端转录（Qwen3-ASR-Flash，需 DashScope API Key）。两种方式为并列可选：本地离线可用、无需 Key、首次需下载模型；云端需联网与 Key。默认本地，用户可随时切换。流程：检测输入类型（视频/音频，音频跳过转 MP3 且无需静帧）-> 模型按能力自动决定是否切段 -> 本地/云端转录 -> 说话人分离（本地 Paraformer+CAM++ 在模型内完成、云端 LLM 语义切分，支持多说话人；Paraformer 为真实句级时间码、SenseVoice 为插值估算）-> LLM 生成内容摘要与人物信息 -> 直接生成带时间码的 Word 文档（.docx；分发到在线平台时导出临时 Markdown，上传后即删）-> 自检精简语气词 -> 交付前预览确认 -> 可选分发到在线文档平台。
  若用户把一段音视频拆成多个视频/音频文件，需请用户明确告知哪几个文件属于同一段音视频，技能自动合并转录为一篇文档。
  适用于任何支持 bash 命令执行和文件读写的 AI 编码代理（Agent）。全流程处理完毕后主动询问用户交付位置，并说明还有云端转录这一可选方式（需 DashScope API Key）。
agent_created: true
---

# 音视频转文档（interview-transcriber）

## 概述

将音视频内容（视频或音频，也可是一段音视频被拆成的多个文件）全流程处理为带说话人识别的转录文档。核心流程始终执行：输入预处理 → 默认本地转录（Paraformer-large，高精度、离线可用）→ 模型按能力自动决定是否切段 → 说话人分离（本地 Paraformer+CAM++ 模型内完成，支持多说话人）→ 生成摘要与人物信息 → 直接生成 Word 文档（.docx）→ 自检精简语气词 → 交付前预览确认 → 可选分发。全部完成后主动询问用户交付位置，并说明还有云端转录这一可选方式（需 DashScope API Key）。

**转录方式（默认本地）：** 默认本地转录（Paraformer-large，从魔搭社区下载，无需 API Key，离线可用、中文高精度）；仅当用户明确要求用云端、或提供 DashScope API Key 时才切换 Qwen3-ASR-Flash。详见 references/model_download.md。

**多段音视频（重要）：** 若用户把一段音视频拆成了多个视频/音频文件，必须请用户**明确告知哪几个文件属于同一段音视频**，技能会合并转录为一篇文档。详见文末「多段音视频输入说明」。

## Agent 适配说明

本技能以 Markdown 指令编写，任何支持 bash / 文件读写 / Python 的 AI 编码代理均可使用。

| Agent | 加载方式 |
|-------|---------|
| **WorkBuddy** | 放在 `~/.workbuddy/skills/`，对话中自动触发或 `@skill:interview-transcriber` |
| **Claude Code / Codex / Cursor / 其他** | 作为 `CLAUDE.md` / `AGENTS.md` / `.cursorrules` 注入，核心依赖 ffmpeg + Python + 可选 DashScope |

**LLM 调用方式：** Step 3.6（摘要/人物信息）需要 LLM。本地说话人由 CAM++ 在模型内分离，无需 LLM；仅云端说话人 + 全部摘要仍走 LLM。方式 A（推荐）：Agent 自身即 LLM，直接执行。方式 B：非 LLM Agent 用 Python 调用 qwen-plus，**统一通过 `scripts/call_qwen.py`**（见 references/dashscope_setup.md）。

## 进度反馈（用户体验）

长耗时环节（模型下载 0.5–1GB、逐段转录、说话人命名/摘要、docx 生成）用户会干等。请在每阶段向用户给出**简短进度提示**，例如：
- 「① 正在预处理视频 / 转码音频…」
- 「② 首次转录需联网下载本地模型（Paraformer-large ~800MB，默认），耗时约 1–5 分钟，请耐心等待；下载后自动缓存，后续转录秒级启动」
- 「③ 正在转录第 2/5 段…」
- 「④ 正在做说话人命名 / 生成摘要…」（本地说话人已由 CAM++ 分离，此步仅轻量命名）
- 「⑤ 正在生成 Word 文档…」

脚本本身也会打印阶段与逐段进度（`[转录进度 i/N]`、`段 i/N`、`⏳ 首次下载` 等），可直接转述给用户。

## 长耗时步骤执行要点（避免 Agent 卡死 / 用户看到「没声了」）
本技能多个步骤耗时数分钟（模型下载、逐段 ASR、说话人命名/摘要）。若 Agent 在前台**阻塞等待**这些命令，一旦超时或脚本挂起，整轮对话会卡死、再也不回消息。必须遵守：

- **长命令一律放后台跑 + 轮询**，不要在前台同步等：转录（`transcribe_local.py` / `transcribe_qwen.py`）、LLM 调用（`call_qwen.py`）都用后台任务启动，再周期性读取进度 / 部分结果文件确认存活。
- **超时策略（已取消强制终止）**：任何长耗时调用都**不再 `os._exit` 强制杀进程**——超时改为**抛异常友好退出**，由上层决定如何恢复。
  - **模型加载（首次下载）不设硬超时**：网速慢也允许模型慢慢下载完。每累计满 600s 脚本会打印一条 `⚠️ 已超 600s` 状态横幅（仍在后台继续下载、不中断），提示 Agent 向用户报告并询问「继续等待 / 中止」。
  - **Agent 必做**：`transcribe_local.py` 务必**后台启动并轮询日志**；一旦看到上述横幅，立即向用户报告现状并**用提问让用户选择「继续 / 中止」**（不要自作主张杀进程，也不要干等）。用户选「继续」就保持运行；选「中止」才停任务（已落盘的 `_transcript.partial.json` 可作部分交付）。
  - **单段 ASR 900s / LLM 调用 180s** 仍保留软超时（超时抛异常、脚本打印原因后退出，不卡死）。
  - 所有进度 print 已 `flush`，后台日志能实时看到。
- **部分结果已落盘**：`transcribe_local.py` 每处理完一段就写 `<标题>_transcript.partial.json`，即使中途中断也有部分内容可交付 / 续跑。
- 用户感知：启动长步骤前一句「正在转录，约需 X 分钟，我后台跑着、好了告诉你」比「稍等片刻」更不容易让用户以为卡死。

## ⚠️ 踩坑与硬性规则（必读）

本技能在真实环境（Windows + 托管 Python 3.13 无 C++ 编译器 + RTX 4070 GPU + 钉钉 dws）跑通过，以下坑都是实测踩出来的。完整清单与对策见 **references/gotchas.md**（强烈建议改动技能或首次跑长任务前通读）。几条最高频、最致命的硬性规则：

- **本地说话人分离必须走 punc_segment 句子级模式（血泪坑）**：普通 `speech_paraformer-large_asr_nat` **不产生词级时间码**，加了 spk_model 也只会退回 **vad_segment 模式**——每个 VAD 语音段只能贴一个说话人标签，开头几十秒连续问答会被并成同一个人（这就是"说话人分离有很大问题"的根因）。**正确做法**：用 nat 版模型 `iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch`（词级时间码）+ **显式传 `vad_model`（fsmn_vad）**+ **同载 `punc_model`（ct-transformer）**+ `spk_model`（campplus_sv），并传 `preset_spk_num=2`（双人对话强制聚 2 类，显著稳）。四件套缺一不可：缺 vad_model → 长音频不分段、`sentence_info` 为空（"生成 0 片段"）；缺 punc_model → 无 `punc_array`、punc_segment 不触发、`sentence_info` 为空。跑通后每句自带 `spk/sentence/start/end`，句子级正确交替。`build_document.py --auto` 按「首次出现顺序」中性命名为 说话人1/2/3……（**不做采访者/受访人角色判定**，corrections 的 `speaker_roles` 留空即保持中性）；改真名/角色才用 `--apply`。仅**云端** Qwen3-ASR-Flash 无原生分离，仍需 LLM 语义切分。
- **本地时间码分两路**：Paraformer-VAD 返回**真实句级时间码**（sentence_info，精确到句）；仅 SenseVoice 的 `sentence_timestamp` 不生效、每段整块，逐句时间码才由「标点切句 + 各段偏移/时长线性插值」估算——**段内为估算值、段落边界才精确，勿标「精确到秒」**。
- **钉钉在线文档无法渲染本地图片路径**：`H:/...jpg` 不显示，必须用 `dws doc media insert` 把图真正上传插入。
- **钉钉 `dws auth status` 会卡 2 分钟**：别依赖它，直接试业务命令（doc search/create/send 正常即已登录）。
- **同主题二改三改用 overwrite，不要新建**：修订同一采访复用同一文档（`dws doc update --mode overwrite`），勿重复新建造成冗余；新采访才 `doc create`。
- **未经明确授权不发钉钉消息**：覆盖文档（overwrite）无需每次问，但 `chat message send` 必须用户明确同意。

## 工作流程

### Step 0: 环境准备与首次安装 review（必须，避免组件漏装）

本技能依赖：5 个 Python 包（funasr / modelscope / python-docx / pillow / dashscope）+ ffmpeg/ffprobe。**这些必须在转录前全部就绪**，否则跑到一半才报错、白费数分钟。

**执行顺序（硬性要求）：**
1. **先 review（不安装）**：运行 `python <skill_dir>/scripts/setup_env.py --verify`
   - 全 ✅ → 直接跳到 Step 1，无需安装。
   - 有 ❌ → 进入第 2 步安装。
2. **安装**：`python <skill_dir>/scripts/setup_env.py`（**已装组件自动跳过、不重复下载**，逐包安装，单个失败不影响其他包，会自动记录漏装项并给出精准重试命令；ffmpeg 在 Windows 缺失时自动从国内镜像下载静态构建；`--force` 可强制重装所有组件）。
3. **安装后必须再 review**：脚本装完会**自动跑一遍自检**并打印 PASS/FAIL 报告（也可单独 `python <skill_dir>/scripts/setup_env.py --verify` 复查）。**只有全部 ✅ 才进入 Step 1 转录；仍有 ❌ 则按报告里的精准命令补装对应组件，复查通过再继续。**
   - 切勿「装完就走」——这正是过去组件漏装、转录中途失败的根因。

> 说明：`setup_env.py` 的自检是**真实 import 每个包 + 校验 ffmpeg 二进制是否存在**，不是看 pip 记录，漏装一定能暴露。Agent 在 Step 0 结束后应向用户一句话通报「组件自检全部通过 / 还差 X」，再继续。

### Step 1: 输入预处理（ffmpeg）

**1a. 检测输入类型**：视频（`.mp4 .mov .avi .mkv .flv .wmv .webm`）/ 音频（`.mp3 .wav .m4a .aac .flac .ogg .wma`）。

**1b. 视频输入 → 提取静帧 + 转 MP3**
- 静帧：用 `scripts/extract_frame.py` 抽取**最清晰的一帧**（视频【五等分】各抽 1 帧、按清晰度比选，输入定位不软解整段视频），输出 800px 宽：
  ```
  python <skill_dir>/scripts/extract_frame.py "输入.mp4" "人物静帧.jpg"
  ```
- 转 MP3（16k 单声道 192kbps）：`ffmpeg -i "输入.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y`
- `frame_path="人物静帧.jpg"`，`audio_file="输出.mp3"`

**1c. 音频输入 → 跳过 MP3 转换，无静帧**
```
ffmpeg -i "输入.m4a" -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y
```
- `frame_path=null`，`audio_file="输出.mp3"`（或原文件）

**1d. 多段输入合并**：见文末「多段音视频输入说明」（合并命令见 references/segment_commands.md）。

> 切段不在 Step 1 进行：由 Step 2.6 按模型能力自动决策（不询问用户）。

### Step 2: 确定文档标题

`拍摄时间+人物简介（≤10字）`。拍摄时间用 fallback 链：① 文件夹名 `YY-MMDD` → ② 文件名 `YY-MMDD` → ③ 文件元数据时间 → ④ 标记「未知日期」。人物简介由 Agent 提炼（学校/专业/年级/家乡等，≤10字）。示例：`26-0509 车辆学院直博生`。

### Step 2.5: 确定转录方式（默认本地）

默认本地（`mode: "local"`，Paraformer-large），**不打断询问**。仅当用户明确要求云端/提供 Key，或要求其他本地模型（如更轻量的 SenseVoice）时才切换。

> ⚠️ **开始前一句话交代取舍**（避免用户误以为卡死）：本地离线可用、无需 Key，但首次需联网下载模型（Paraformer-large ~800MB + torch 推理栈，GPU 版约 2.7GB，耗时数分钟）；云端需联网与 DashScope API Key。两种方式都能满足常规转录需求，默认本地，用户可随时切换。

配置 `transcribe_config.json`（也可先用 `python <skill_dir>/scripts/prepare.py <输入>` 一键生成：自动识别类型、抽静帧、转 MP3、按模型能力切段、写入 config）：

**首次转录提醒（必须执行）：** 在真正运行转录脚本（Step 3）之前，必须先用一句话告知用户——「本次为首次转录，将联网下载本地模型（Paraformer-large 约 800MB + torch 推理栈，GPU 版约 2.7GB），耗时数分钟，请耐心等待；下载完成后会自动缓存，之后转录秒级启动」。脚本 `transcribe_local.py` 启动时也会打印同样提示。这样做是为避免用户面对数分钟静默误以为卡死。
- 云端（`mode: "cloud"`）：需 `api_key`；本地（`mode: "local"`）：`model` 默认 paraformer（可选 sensevoice）。**本地说话人由 CAM++ 在模型内分离（免 HF Token、无需 LLM）**；仅云端说话人 + 全部摘要才走 LLM 语义切分，群访等多个说话人同样支持。
- 配置模板（cloud/local）见 references/dashscope_setup.md；模型下载/镜像/HF Token 说明见 references/model_download.md。

### Step 2.6: 切段决策（模型自动，不询问）

用 ffprobe 获取音频时长，按所选模型能力自动决策（详见 references/segment_commands.md）：
- **云端 Qwen3-ASR-Flash**：>5 分钟必切（4 分钟/段，留余量）；≤5 分钟整段。
- **本地 SenseVoice/Paraformer**：>20 分钟建议切（4 分钟/段）；短音频整段。
- 切段命令见 references/segment_commands.md。结果写入 config 的 `segments`（切段：offset 递增；不切：`[{"file":"输出.mp3","offset":0}]`）。

### Step 3: 运行转录

> `<skill_dir>` 为本技能目录。

**3A. 云端（可选方式）**：`python <skill_dir>/scripts/transcribe_qwen.py --config transcribe_config.json` — 逐段调用 qwen3-asr-flash，生成 `<标题>_transcript.json`（含 metadata + `raw_text`，无 Markdown）。

**3B. 本地（默认）**：`python <skill_dir>/scripts/transcribe_local.py --config transcribe_config.json [--model paraformer]`（默认 Paraformer-large，高精度） — 逐段 ASR，**说话人由 CAM++ 在模型内分离**（生成 `<标题>_transcript.json` 已带 `SPEAKER_XX`），角色命名见 Step 3.65。依赖安装见 references/model_download.md。

### Step 3.5: 说话人识别（本地已模型内完成，云端需 LLM）

- **本地（默认）**：说话人已由 Paraformer+CAM++ 在模型内分离，`_transcript.json` 每段已带真实 `SPEAKER_XX`。**无需 LLM**；统一命名（说话人1/2/3……）在 Step 3.65 由 `build_document.py --auto` 完成（按首次出现顺序中性编号），如需真名/角色用 `--apply` 覆盖。
- **云端**：Qwen3-ASR-Flash 无原生说话人分离，仍需 LLM 语义切分。方法 A（Agent 自身 LLM）直接按 references/prompts.md 的 prompt 输出；方法 B（外部 API）用 `python <skill_dir>/scripts/call_qwen.py --prompt-file speaker_prompt.txt`。

> 说明：本地说话人走 CAM++ 是按声纹聚类（模型内、可靠），与旧版「逐句启发式」或「LLM 语义切分」都不同——它直接给出「谁在何时说」，不再需要 Agent 做繁重的切分。

### Step 3.6: 生成摘要与人物信息（必须执行！）

调用 LLM 生成**三部分**：① `summary`（3-5 句总结性摘要）+ ② `summary_sections`（按主题拆分的分板块摘要，每个板块 = `{"title", "content"}`，**至少 2 个板块**）+ ③ `person_info`（人物字段表，字段：学校/单位、专业/学院、年级/身份、家乡、关键经历、核心观点）。方法 A/B 同上，prompt 见 references/prompts.md。

**写入 `<标题>_document.json`**（字段定义见 references/output_schema.md）。该 JSON 由 Step 3.8 直接生成 .docx，**全程不生成 Markdown**。

### Step 3.65: 用 build_document.py 组装 document.json（标准实现，修切分 bug）

把 Step 3.5/3.6 的结果落盘为标准化 `<标题>_document.json`，**统一走脚本**而非临时正则切分（2026-07-13 复盘：手写切分曾把 SenseVoice 的 `<|withitn|>` 当段间分隔，导致段 1 整段丢失、段 3 丢失、时间码错乱；本脚本直接消费 `transcript.json` 的结构化 `segments`，根除该问题）。

```bash
# 1) 先看逐句解析 + 说话人分布，供 Agent 复核命名
python <skill_dir>/scripts/build_document.py "<output_dir>/<标题>_transcript.json" --review

# 2) 自动按首次出现顺序统一命名 说话人1/2/3…… + 写出 document.json（summary/person_info 由 Agent 填）
python <skill_dir>/scripts/build_document.py "<output_dir>/<标题>_transcript.json" "<output_dir>/<标题>_document.json" --auto

# 3) Agent 复核后用 corrections.json 落盘最终 document.json（推荐，避免手改 JSON）
#    corrections.json = {"speaker_roles": {"说话人1":"张三","说话人2":"李四", ...},
#                        "summary":"…", "summary_sections":[{"title":"…","content":"…"}, ...],
#                        "person_info":[…]}
python <skill_dir>/scripts/build_document.py "<output_dir>/<标题>_transcript.json" "<output_dir>/<标题>_document.json" --apply corrections.json
```

- 脚本消费 `transcript.json` 的 `segments`：Paraformer-VAD 已带**真实句级** start/end（精确到句）；SenseVoice 则整段一块、start/end 为 0，由本脚本「按标点切句 + 各段偏移/时长线性插值」得到——**段内为估算值，段落边界才精确，勿标「精确到秒」**。无需再解析 `raw_text`。
- 说话人角色：本地已用 CAM++ 在模型内分离好（每段带真实 `SPEAKER_XX`），`--auto` 统一按首次出现顺序中性命名为 说话人1/2/3……，**无需 LLM**。命名有误时再用 `--apply` 覆盖 `speaker_roles` 即可。⚠️ **轻量闭环（命名不准才用）**：① `python build_document.py transcript.json --review` 打印逐句 + 说话人分布；② 若自动命名不准，把角色映射写成 `corrections.json`：`{"speaker_roles": {"说话人1":"张三","说话人2":"李四"}, "summary":"…", "summary_sections":[{"title":"…","content":"…"}, ...], "person_info":[…]}`；③ `python build_document.py transcript.json document.json --apply corrections.json` 自动按 speaker id 映射角色、合并连续同角色为 turn，写出最终 `document.json`（无需手改嵌套 JSON，避免出错）。
- 随后 Agent 把 Step 3.6 的 `summary` / `summary_sections` / `person_info` 写入同一 `document.json`（无信息则 `person_info: []` 整段省略；多人多表）。
- 也可 `import` 本脚本的 `parse_sentences / assign_speaker_labels / assemble_document` 在 Agent 代码里直接调用。
- **长轮次自动分段**：`group_turns` 会把长独白（如某说话人一口气讲 1000+ 字）按 ~160 字或 4 句切成多段，每段带首句时间码；`build_docx.py` 的 `.docx` 与 Markdown 均逐段输出，避免一大块难读。

### Step 3.7: 自检与语气词精简（生成文档后执行）

通读对话记录，适度删除明显冗余的语气词/填充词（嗯、啊、那个、就是、然后堆叠等）。原则：**只删明显冗余、不改原意、不动摘要/人物信息/时间码/说话人标签**。详见 references/prompts.md 文末说明。

### Step 3.8: 构建 Word 文档（直接生成，无中间 Markdown）

```
python <skill_dir>/scripts/build_docx.py "<output_dir>/<标题>_document.json" "<output_dir>/<标题>.docx"
```
直接渲染：标题、居中静帧（仅视频、`frame_path` 非 null）、**内容摘要**（含总结性摘要 + 分板块 H2 子标题）、人物信息（无则省略／多人多表）、文档信息（精简为 5 行：源文件 / 输入类型 / 转录工具 / 说话人识别 / 转录日期，**不再写时间码精度、摘要与人物信息**）、对话记录（每轮首句用一个**色相差异大的彩色圆点** emoji 标识不同说话人：🔴红 → 🔵蓝 → 🟢绿 → 🟡黄 → 🟣紫 → ⚫黑 → 🟤棕 → ⚪白 → 🟠橙 → 🔘灰 循环；说话人1=🔴红、说话人2=🔵蓝，默认色相差距大）。音频输入跳过静帧。依赖：`pip install python-docx pillow`。

### Step 3.9: 交付前预览与轻量确认（清理前）

`.docx` 生成后、Step 5 清理前，向用户展示标题 / 说话人概览 / 摘要要点，确认说话人分得对不对。确认后继续；有误回对应步骤修正（说话人颠倒→Step 3.5，标题错→Step 2，摘要偏差→Step 3.6）后重新生成并再确认。用户说"直接定稿"可跳过。

### Step 4: 输出与分发

本地 `.docx` 始终生成。可选分发：钉钉/飞书/腾讯文档（用 `build_docx.py --export-md --no-frame` 生成临时 `_upload.md`——`--no-frame` 避免写入打不开的本地图路径，上传后即删）/ 本地文件 / 直接粘贴。上传失败保留本地 `.docx` 兜底。

**钉钉分发硬性规则（详见 references/gotchas.md §3）：**
- **图片必须用 `dws doc media insert` 上传**：在线文档 Markdown **不渲染本地路径**（如 `H:/.../人物静帧.jpg`），直接写进去不显示。正确做法：① 导出上传用 `_upload.md` 时加 `--no-frame` 参数（脚本不再写入本地图片行）；② 用 `dws doc media insert --node <nodeId> --file <本地图> --index 0` 把图真正上传插入（三步：取上传凭证→传 OSS→插块）。原 `.docx` 才保留本地图。
- **同主题 reuse 用 overwrite，勿新建**：修订同一采访复用同一文档（`dws doc update --mode overwrite` 配合 `--content-file`）覆盖，避免冗余；新采访才 `dws doc create`。
- **`dws auth status` 会卡 ~2 分钟**：别用它判断登录态，直接试探 `doc search/create/send` 等**业务命令**，正常即已登录。
- **未经明确授权不发消息**：`dws doc update/overwrite` 无需每次问；但 `dws chat message send` **必须用户明确同意**才执行。用户明确说不要发给某人时，本次及后续都不再发。

### Step 5: 清理临时文件

```bash
# 保留 <标题>_document.json（可编辑的事实源，修订/overwrite 时复用，无需重跑转录）
rm -f _seg*.mp3 _upload.md *_raw.txt *_transcript.json *_transcript.partial.json *segments.json transcribe_config.json 输出.mp3
```
保留：`<标题>.docx`、`<标题>_document.json`、人物静帧.jpg（仅视频）。

### Step 6: 询问交付位置（收尾）

全部完成后主动询问用户发哪里，再分发；未经确认不上传外部平台。如用户问起，也可说明：本次使用本地转录；若想改用云端 Qwen3-ASR-Flash（需 DashScope API Key）也可随时切换。

## 多段音视频输入说明（重要）

**用户须知**：当一个采访被拆成多个视频/音频文件时，用户必须**明确告知技能哪几个文件属于同一段采访**。技能不会自行假设多个文件是同一采访；未说明则每个文件各成一篇文档。

**触发与处理（Step 1d）**：用户说明后，Agent 将这批文件合并转录为一篇文档：
- **视频**：每个文件分别用 `extract_frame.py` 抽静帧（支持多视频参数，自动跨片段比选最清晰帧）+ 各自转 MP3，再合并所有 MP3 为 `输出.mp3`（ffmpeg concat，统一 16k 单声道）。
- **音频**：每个文件重采样（如需）后 concat 合并。
- 合并后，Step 2.6 切段决策作用在合并 `输出.mp3` 总时长上；标题取第一个文件的命名/时间信息。
- 合并命令见 references/segment_commands.md（concat 部分）。

## 说话人识别说明

- ❌ 启发式方法（关键词+段落长度）：已废弃，完全不可靠。
- ✅ 云端模式：Qwen3-ASR-Flash 转录 + LLM 语义切分（支持多说话人）。
- ✅ 本地模式：Paraformer-large + CAM++ 在模型内说话人分离（按声纹自动聚类，免 HF Token、无需 LLM；统一中性命名为 说话人1/2/3）。
- Qwen3-ASR-Flash 不直接支持说话人分离；云端最优方案为「转录 + LLM 语义分段」。

## 错误处理与失败恢复

全流程任一环节失败都应**可见、可恢复、有兜底**。关键原则：
- 预处理/时长失败 → 提示检查源文件；时长未知保守切段
- 模型下载失败 → 打印手动命令，建议改用 Paraformer/云端
- 云端 API 失败 → 偶发重试，持续失败自动降级本地
- 说话人识别异常 → 告警，Step 3.9 由用户纠正
- .docx 依赖缺失 → 提示 `pip install python-docx pillow`，保留 `_document.json`
- 上传失败 → 保留本地 `.docx` 兜底

详细回退动作见 references/error_handling.md。

## 注意事项

- **多段音视频需用户明确说明归属**，才合并为一篇文档；未说明则各成一篇
- **本地说话人由 CAM++ 模型内分离（无需 LLM）**；仅云端 Qwen3-ASR-Flash 无原生分离、仍走 LLM 语义切分（启发式已废弃）。
- **DashScope 调用统一**：音频转录用 `MultiModalConversation.call(model="qwen3-asr-flash")`；文本任务（说话人/摘要）用 `scripts/call_qwen.py`（`Generation.call`, qwen-plus）。务必 `pip install -U dashscope`，勿用已变更的 `Transcription.call`（版本兼容见 references/dashscope_setup.md）
- **默认本地 Paraformer-large 转录**，不强制询问；仅用户明确要求用云端、SenseVoice 或提供 Key 时切
- **GPU 加速（本地仍默认）**：`setup_env.py` 检测到 NVIDIA GPU 会自动装 CUDA 版 torch，本地 Paraformer-large/SenseVoice 推理走 GPU（RTX 40 系约数倍提速）；无 GPU 则装 CPU 版。无论哪种，**默认仍是本地模型推理**，不切换云端
- **输入类型自动识别**：视频才提取静帧+转 MP3；音频跳过且 `frame_path=null` 不输出静帧
- **切段决策在选方式之后、模型自动**：云端 >5 分钟必切，本地 >20 分钟建议切，均不询问
- **本地说话人由 CAM++ 模型内分离（无需 LLM）**；仅云端 Qwen3-ASR-Flash 无原生分离、仍走 LLM 语义切分；支持多说话人（群访无需额外配置）；无需 HF Token、无需 pyannote
- **全程无需 HuggingFace**：本地说话人走 CAM++（模型内、魔搭直连），模型仅 Paraformer-large/SenseVoice；已移出 faster-whisper / pyannote
- Windows 路径用正斜杠（`C:/...` 或相对路径，勿用 Git Bash 的 `/c/...` 写法，脚本已自动兼容转换）；`bc` 不可用（用 Python 算）；bash heredoc 不吃 `\s`（正则写 .py 文件）
- **长文本 LLM 分段**：单次输入 ≤ 8000 字符，超长分段后合并
- **时间码精度**：本地 Paraformer-VAD 为真实句级时间码；SenseVoice 段内为插值估算（段落边界精确）；云端段内为估算值（4 分钟粒度）；文档已如实标注，勿当精确时间
- **收尾必须主动询问交付位置**（Step 6），未经确认不上传外部平台
- **最终交付 .docx**：转录脚本输出 `_transcript.json`，Agent 写 `_document.json`，`build_docx.py` 直接生成 .docx（分发到在线平台时导出临时 Markdown，上传后即删）
