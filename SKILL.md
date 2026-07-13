---
name: interview-transcriber
display_name: 采访秒变 Word
description: |
  采访转录全流程处理技能（支持视频与音频输入，也支持「一个采访拆成多段文件」合并转录）。默认本地转录（SenseVoice/Paraformer 魔搭社区中文模型，离线可用、无需 API Key）；可选云端转录（Qwen3-ASR-Flash，准确率更高，需 DashScope API Key）作为升级方案。流程：检测输入类型（视频/音频，音频跳过转 MP3 且无需静帧）-> 模型按能力自动决定是否切段 -> 本地/云端转录 -> LLM 智能说话人识别（统一语义切分，免 HuggingFace Token，支持多说话人，保留时间码） -> LLM 生成内容摘要与受访人人物信息 -> 直接生成带时间码的 Word 文档（.docx，全程无 Markdown 中间文件）-> 自检精简语气词 -> 交付前预览确认 -> 可选分发到在线文档平台。
  若用户把一个采访拆成多个视频/音频文件，需请用户明确告知哪几个文件属于同一段采访，技能自动合并转录为一篇文档。
  适用于任何支持 bash 命令执行和文件读写的 AI 编码代理（Agent）。全流程处理完毕后主动询问用户交付位置，并提示云端转录作为更高精度的可选方案。
agent_created: true
---

# 采访秒变 Word（interview-transcriber）

## 概述

将采访内容（视频或音频，也可是一段采访被拆成的多个文件）全流程处理为带说话人识别的转录文档。核心流程始终执行：输入预处理 → 默认本地转录（SenseVoice，离线可用）→ 模型按能力自动决定是否切段 → 说话人识别（支持多说话人）→ 生成摘要与人物信息 → 直接生成 Word 文档（.docx，全程无 Markdown 中间文件）→ 自检精简语气词 → 交付前预览确认 → 可选分发。全部完成后主动询问用户交付位置，并提示云端转录作为更高精度可选方案。

**转录方式（默认本地）：** 默认本地转录（SenseVoice，从魔搭社区下载，无需 API Key，离线可用）；仅当用户明确要求更高准确率或提供 DashScope API Key 时才切换云端 Qwen3-ASR-Flash。详见 references/model_download.md。

**多段采访（重要）：** 若用户把一个采访拆成了多个视频/音频文件，必须请用户**明确告知哪几个文件属于同一段采访**，技能会合并转录为一篇文档。详见文末「多段采访输入说明」。

## Agent 适配说明

本技能以 Markdown 指令编写，任何支持 bash / 文件读写 / Python 的 AI 编码代理均可使用。

| Agent | 加载方式 |
|-------|---------|
| **WorkBuddy** | 放在 `~/.workbuddy/skills/`，对话中自动触发或 `@skill:interview-transcriber` |
| **Claude Code / Codex / Cursor / 其他** | 作为 `CLAUDE.md` / `AGENTS.md` / `.cursorrules` 注入，核心依赖 ffmpeg + Python + 可选 DashScope |

**LLM 调用方式：** Step 3.5/3.6 需要 LLM。方式 A（推荐）：Agent 自身即 LLM，直接执行语义分析。方式 B：非 LLM Agent 用 Python 调用 qwen-plus，**统一通过 `scripts/call_qwen.py`**（见 references/dashscope_setup.md）。

## 进度反馈（用户体验）

长耗时环节（模型下载 0.5–1GB、逐段转录、LLM 说话人识别/摘要、docx 生成）用户会干等。请在每阶段向用户给出**简短进度提示**，例如：
- 「① 正在预处理视频 / 转码音频…」
- 「② 首次转录需联网下载本地模型（SenseVoice ~500MB / Paraformer ~800MB），耗时约 1–5 分钟，请耐心等待；下载后自动缓存，后续转录秒级启动」
- 「③ 正在转录第 2/5 段…」
- 「④ 正在做说话人识别 / 生成摘要…」
- 「⑤ 正在生成 Word 文档…」

脚本本身也会打印阶段与逐段进度（`[转录进度 i/N]`、`段 i/N`、`⏳ 首次下载` 等），可直接转述给用户。

## 长耗时步骤执行要点（避免 Agent 卡死 / 用户看到「没声了」）
本技能多个步骤耗时数分钟（模型下载、逐段 ASR、LLM 说话人/摘要）。若 Agent 在前台**阻塞等待**这些命令，一旦超时或脚本挂起，整轮对话会卡死、再也不回消息。必须遵守：

- **长命令一律放后台跑 + 轮询**，不要在前台同步等：转录（`transcribe_local.py` / `transcribe_qwen.py`）、LLM 调用（`call_qwen.py`）都用后台任务启动，再周期性读取进度 / 部分结果文件确认存活。
- **脚本已加硬超时与 flush**：模型加载 600s、单段 ASR 900s、LLM 调用 180s 超时后会**快速失败并退出**（不再无限挂起）；所有进度 print 已 `flush`，后台日志能实时看到。超时即按「错误处理」章节恢复，不要干等。
- **部分结果已落盘**：`transcribe_local.py` 每处理完一段就写 `<标题>_transcript.partial.json`，即使中途中断也有部分内容可交付 / 续跑。
- 用户感知：启动长步骤前一句「正在转录，约需 X 分钟，我后台跑着、好了告诉你」比「稍等片刻」更不容易让用户以为卡死。

## 工作流程

### Step 0: 环境准备与首次安装 review（必须，避免组件漏装）

本技能依赖：5 个 Python 包（funasr / modelscope / python-docx / pillow / dashscope）+ ffmpeg/ffprobe。**这些必须在转录前全部就绪**，否则跑到一半才报错、白费数分钟。

**执行顺序（硬性要求）：**
1. **先 review（不安装）**：运行 `python <skill_dir>/scripts/setup_env.py --verify`
   - 全 ✅ → 直接跳到 Step 1，无需安装。
   - 有 ❌ → 进入第 2 步安装。
2. **安装**：`python <skill_dir>/scripts/setup_env.py`（逐包安装，单个失败不影响其他包，会自动记录漏装项并给出精准重试命令；ffmpeg 在 Windows 缺失时自动从国内镜像下载静态构建）。
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

**1d. 多段输入合并**：见文末「多段采访输入说明」（合并命令见 references/segment_commands.md）。

> 切段不在 Step 1 进行：由 Step 2.6 按模型能力自动决策（不询问用户）。

### Step 2: 确定文档标题

`拍摄时间+人物简介（≤10字）`。拍摄时间用 fallback 链：① 文件夹名 `YY-MMDD` → ② 文件名 `YY-MMDD` → ③ 文件元数据时间 → ④ 标记「未知日期」。人物简介由 Agent 提炼（学校/专业/年级/家乡等，≤10字）。示例：`26-0509 车辆学院直博生`。

### Step 2.5: 确定转录方式（默认本地）

默认本地（`mode: "local"`，SenseVoice），**不打断询问**。仅当用户明确要求云端/提供 Key，或要求其他本地模型时才切换。配置 `transcribe_config.json`：

**首次转录提醒（必须执行）：** 在真正运行转录脚本（Step 3）之前，必须先用一句话告知用户——「本次为首次转录，将联网下载本地模型（SenseVoice 约 500MB），耗时约 1–5 分钟，请耐心等待；下载完成后会自动缓存，之后转录秒级启动」。脚本 `transcribe_local.py` 启动时也会打印同样提示。这样做是为避免用户面对数分钟静默误以为卡死。
- 云端（`mode: "cloud"`）：需 `api_key`；本地（`mode: "local"`）：`model` 默认 sensevoice（可选 paraformer）。说话人统一由 Step 3.5 LLM 语义切分（免 HF Token），群访等多个说话人同样支持。
- 配置模板（cloud/local）见 references/dashscope_setup.md；模型下载/镜像/HF Token 说明见 references/model_download.md。

### Step 2.6: 切段决策（模型自动，不询问）

用 ffprobe 获取音频时长，按所选模型能力自动决策（详见 references/segment_commands.md）：
- **云端 Qwen3-ASR-Flash**：>5 分钟必切（4 分钟/段，留余量）；≤5 分钟整段。
- **本地 SenseVoice/Paraformer**：>20 分钟建议切（4 分钟/段）；短音频整段。
- 切段命令见 references/segment_commands.md。结果写入 config 的 `segments`（切段：offset 递增；不切：`[{"file":"输出.mp3","offset":0}]`）。

### Step 3: 运行转录

> `<skill_dir>` 为本技能目录。

**3A. 云端（可选升级）**：`python <skill_dir>/scripts/transcribe_qwen.py --config transcribe_config.json` — 逐段调用 qwen3-asr-flash，生成 `<标题>_transcript.json`（含 metadata + `raw_text`，无 Markdown）。

**3B. 本地（默认）**：`python <skill_dir>/scripts/transcribe_local.py --config transcribe_config.json [--model sensevoice]` — 逐段 ASR，生成 `<标题>_transcript.json`（统一标 `SPEAKER_00`，说话人由 Step 3.5 LLM 语义切分）。依赖安装见 references/model_download.md。

### Step 3.5: LLM 说话人识别（必须执行！）

无论云端/本地都需 LLM：
- **云端**：连续文本 → LLM 语义切分，识别所有说话人（采访者/受访人/其他如记者乙、旁白）。
- **本地**：脚本统一标 `SPEAKER_00` → LLM 语义切分为角色名（**支持多说话人：采访者/受访人/记者乙/旁白等，免 HF Token**）。

方法 A（Agent 自身 LLM）直接按 prompt 输出；方法 B（外部 API）用 `python <skill_dir>/scripts/call_qwen.py --prompt-file speaker_prompt.txt`。完整 prompt 模板见 references/prompts.md。

### Step 3.6: 生成摘要与人物信息（必须执行！）

调用 LLM 生成 3-5 句摘要 + 受访人信息表（字段：学校/单位、专业/学院、年级/身份、家乡、关键经历、核心观点）。方法 A/B 同上，prompt 见 references/prompts.md。

**写入 `<标题>_document.json`**（字段定义见 references/output_schema.md）。该 JSON 由 Step 3.8 直接生成 .docx，**全程不生成 Markdown**。

### Step 3.7: 自检与语气词精简（生成文档后执行）

通读采访记录，适度删除明显冗余的语气词/填充词（嗯、啊、那个、就是、然后堆叠等）。原则：**只删明显冗余、不改原意、不动摘要/人物信息/时间码/说话人标签**。详见 references/prompts.md 文末说明。

### Step 3.8: 构建 Word 文档（直接生成，无中间 Markdown）

```
python <skill_dir>/scripts/build_docx.py "<output_dir>/<标题>_document.json" "<output_dir>/<标题>.docx"
```
直接渲染：标题、居中静帧（仅视频、`frame_path` 非 null）、内容摘要、人物信息（无则省略／多人多表）、文档信息（含**时间码精度**标注）、采访记录（加粗说话人+时间码）。音频输入跳过静帧。依赖：`pip install python-docx pillow`。

### Step 3.9: 交付前预览与轻量确认（清理前）

`.docx` 生成后、Step 5 清理前，向用户展示标题 / 说话人概览 / 摘要要点，确认说话人分得对不对。确认后继续；有误回对应步骤修正（说话人颠倒→Step 3.5，标题错→Step 2，摘要偏差→Step 3.6）后重新生成并再确认。用户说"直接定稿"可跳过。

### Step 4: 输出与分发

本地 `.docx` 始终生成。可选分发：钉钉/飞书/腾讯文档（用 `build_docx.py --export-md` 生成临时 `_upload.md` 上传后即删）/ 本地文件 / 直接粘贴。上传失败保留本地 `.docx` 兜底。

### Step 5: 清理临时文件

```bash
rm -f _seg*.mp3 _upload.md *_raw.txt *_transcript.json *_document.json *segments.json transcribe_config.json 输出.mp3
```
保留：`<标题>.docx`、人物静帧.jpg（仅视频）。

### Step 6: 询问交付位置（收尾）

全部完成后主动询问用户发哪里，再分发；未经确认不上传外部平台。话术附云端提示：「本次本地转录；如需更高准确率可改用云端 Qwen3-ASR-Flash（需 DashScope API Key，随时告诉我即可切换）。」

## 多段采访输入说明（重要）

**用户须知**：当一个采访被拆成多个视频/音频文件时，用户必须**明确告知技能哪几个文件属于同一段采访**。技能不会自行假设多个文件是同一采访；未说明则每个文件各成一篇文档。

**触发与处理（Step 1d）**：用户说明后，Agent 将这批文件合并转录为一篇文档：
- **视频**：每个文件分别用 `extract_frame.py` 抽静帧（支持多视频参数，自动跨片段比选最清晰帧）+ 各自转 MP3，再合并所有 MP3 为 `输出.mp3`（ffmpeg concat，统一 16k 单声道）。
- **音频**：每个文件重采样（如需）后 concat 合并。
- 合并后，Step 2.6 切段决策作用在合并 `输出.mp3` 总时长上；标题取第一个文件的命名/时间信息。
- 合并命令见 references/segment_commands.md（concat 部分）。

## 说话人识别说明

- ❌ 启发式方法（关键词+段落长度）：已废弃，完全不可靠。
- ✅ 云端模式：Qwen3-ASR-Flash 转录 + LLM 语义切分（准确率 95%+，支持多说话人）。
- ✅ 本地模式：LLM 语义切分（免 HF Token，支持多说话人：采访者/受访人/记者乙/旁白等）。
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

- **多段采访需用户明确说明归属**，才合并为一篇文档；未说明则各成一篇
- **说话人识别必须用 LLM**（启发式已废弃）；prompt 必须强调「每轮问答独立成段，不要合并同一说话人多轮」
- **DashScope 调用统一**：音频转录用 `MultiModalConversation.call(model="qwen3-asr-flash")`；文本任务（说话人/摘要）用 `scripts/call_qwen.py`（`Generation.call`, qwen-plus）。务必 `pip install -U dashscope`，勿用已变更的 `Transcription.call`（版本兼容见 references/dashscope_setup.md）
- **默认本地转录**，不强制询问；仅用户要求更高准确率或提供 Key 时切云端
- **输入类型自动识别**：视频才提取静帧+转 MP3；音频跳过且 `frame_path=null` 不输出静帧
- **切段决策在选方式之后、模型自动**：云端 >5 分钟必切，本地 >20 分钟建议切，均不询问
- **说话人统一 LLM 语义切分（本地/云端同此）**：支持多说话人（群访无需额外配置）；无需 HF Token、无需 pyannote
- **全程无需 HuggingFace**：说话人走 LLM 语义切分，模型仅 SenseVoice/Paraformer（魔搭直连）；已移出 faster-whisper / pyannote
- Windows 路径用正斜杠（`C:/...` 或相对路径，勿用 Git Bash 的 `/c/...` 写法，脚本已自动兼容转换）；`bc` 不可用（用 Python 算）；bash heredoc 不吃 `\s`（正则写 .py 文件）
- **长文本 LLM 分段**：单次输入 ≤ 8000 字符，超长分段后合并
- **时间码精度**：本地精确到秒；云端段内为估算值（4 分钟粒度），文档已标注，勿当精确时间
- **收尾必须主动询问交付位置**（Step 6），未经确认不上传外部平台
- **最终交付 .docx，全程无 Markdown 中间文件**：转录脚本输出 `_transcript.json`，Agent 写 `_document.json`，`build_docx.py` 直接生成 .docx
