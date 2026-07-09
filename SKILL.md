---
name: interview-transcriber
description: |
  采访视频全流程处理技能。覆盖：从视频文件提取人物静帧 -> 视频转 MP3 音频 -> 询问用户选择转录方式（云端/本地，告知质量差异）-> 云端转录（Qwen3-ASR-Flash，推荐）或本地转录（faster-whisper + pyannote.audio 声纹分离，质量较差）-> LLM 智能说话人识别（区分采访者/受访人，保留时间码） -> LLM 生成内容摘要与受访人人物信息（置于文档正文最前面） -> 生成带时间码的 Markdown 文档（第一行嵌入静帧） -> 可选输出到在线文档平台/本地文件等。
  适用于任何支持 bash 命令执行和文件读写的 AI 编码代理（Agent）。
agent_created: true
---

# 采访视频转录

## 概述

将采访视频全流程处理为带说话人识别的转录文档：提取静帧 -> 音频转换 -> 转录（云端/本地可选）-> 说话人识别 -> 生成摘要与人物信息 -> 生成 Markdown -> 可选分发到在线文档平台。

**核心流程（Step 1-3.6）** 与输出目标无关，始终执行。**输出分发（Step 4）** 根据用户需求选择目标平台。

**转录方式选择：** Step 2.5 会在转录前询问用户选择转录方式，并告知质量差异：
- **云端转录（Qwen3-ASR-Flash）** — 推荐，中文识别准确率高，LLM 语义分析区分说话人，需 DashScope API Key
- **本地转录（faster-whisper + pyannote.audio）** — 无云端 API 依赖，pyannote 声纹分离区分说话人，但中文识别质量明显较差，需 HuggingFace Token

## Agent 适配说明

本技能以 Markdown 指令文件形式编写，任何支持 bash 命令执行、文件读写、Python 脚本运行的 AI 编码代理均可使用。以下是各主流 Agent 的使用方式：

| Agent | 加载方式 |
|-------|---------|
| **WorkBuddy** | 放置在 `~/.workbuddy/skills/` 目录下，对话中自动触发或手动 `@skill:interview-transcriber` |
| **Claude Code** | 将本文件内容追加到 `CLAUDE.md`，或通过 `--skill` 参数加载；Agent 本身即为 LLM，可直接执行 Step 3.5/3.6 的语义分析 |
| **Codex (OpenAI)** | 将本文件作为 `AGENTS.md` 或通过系统提示注入；Agent 本身即为 LLM，可直接执行 Step 3.5/3.6 |
| **Cursor** | 将本文件内容放入 `.cursorrules` 或项目上下文中 |
| **其他 Agent** | 将本文件作为系统提示或上下文注入即可，核心流程依赖 ffmpeg + Python + 可选的 DashScope API |

**LLM 调用方式说明：**

Step 3.5（说话人识别）和 Step 3.6（摘要与人物信息）需要 LLM 能力。有两种执行方式：
- **方式 A（推荐）：Agent 自身即是 LLM** — 大多数编码代理（Claude Code、Codex、WorkBuddy 等）本身具备 LLM 能力，可直接阅读转录文本并按 prompt 要求输出结果，无需额外 API 调用
- **方式 B：调用外部 LLM API** — 如 Agent 本身不便直接处理，可使用 Python 调用 `dashscope.Generation.call(model='qwen-plus')`，示例代码见各 Step

## 工作流程

### Step 1: 视频预处理（ffmpeg）

从用户指定的视频目录中读取视频文件（MP4/MOV/AVI 等），执行两项操作：

**1a. 提取人物静帧（视频第 5 秒，800px 宽）**
```
ffmpeg -i "视频文件.mp4" -ss 5 -vframes 1 -q:v 2 -vf "scale=800:-1" "人物静帧.jpg" -y
```

**1b. 视频转 MP3（16kHz 单声道 192kbps）**
```
ffmpeg -i "视频文件.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y
```

**1c. 多段视频合并（如用户指定多个视频需合并转录）**
```
# 先将每个视频转为 MP3，再用 ffmpeg concat filter 合并
ffmpeg -i "合并.mp3" -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0 -t 240 _seg1.mp3 -y
```

**1d. 将 MP3 切分为 4 分钟段（云端和本地转录均需要）**

> 云端：Qwen3-ASR-Flash 单次调用时长限制。本地：控制内存占用 + pyannote 声纹分离在短段上更稳定。

```
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0 -t 240 _seg1.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 240 -t 240 _seg2.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 480 -t 240 _seg3.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 720 -t 260 _seg4.mp3 -y
```

### Step 2: 确定文档标题

**文档命名规范：**

文档标题采用 `拍摄时间+人物简介` 格式：
- **拍摄时间**：从视频所在文件夹名中提取，格式为 `YY-MMDD`（如 `26-0509`、`26-0611`）
- **人物简介**：≤10个中文字符，概括受访人核心特征（学校/专业/年级/家乡等关键信息）
- 两者之间用空格连接

**命名示例：**
| 文件夹名 | 文档标题 | 人物简介字数 |
|---------|---------|------------|
| 清华26-0509 | `26-0509 车辆学院直博生` | 7字 |
| 清华26-0611 | `26-0611 经济学大三女生` | 7字 |
| 清华26-0703 | `26-0703 药学院研二男生` | 7字 |
| 清华26-0528 | `26-0528 北大创业女生` | 6字 |

**人物简介提炼要点：**
1. 优先用：学校（清华/北大等）+ 专业/学院 + 年级/身份
2. 如有特色可替换：如"云南高考第七"、"休学创业中戏生"
3. 严格控制在10个中文字符以内，简洁有力

### Step 2.5: 询问转录方式 & 创建转录配置

**转录前必须询问用户选择哪种转录方式，并明确告知质量差异。**

向用户提出以下问题（可直接展示或通过 Agent 的交互机制提问）：

---

> 请选择转录方式：
>
> **A. 云端转录（Qwen3-ASR-Flash）** — ✅ 推荐
> - 中文识别准确率高，标点断句自然，专有名词识别好
> - 需要 DashScope API Key（阿里云百炼，有免费额度）
> - 网络环境要求：需要联网
>
> **B. 本地转录（faster-whisper + pyannote.audio）** — ⚠️ 质量较差
> - 无需云端 API，离线可用
> - **中文识别质量明显较差**：人名/专有名词错误率高，标点不准确
> - 可能影响后续说话人识别和摘要生成的效果
> - 需要 HuggingFace Token + 安装额外依赖
> - 仅建议在无网络环境或 API 不可用时使用
>
> 请回复 A 或 B：

---

**等待用户回复后，根据选择创建配置：**

- 用户选 A（云端）→ 创建 `mode: "cloud"` 配置，需确认 DashScope API Key
- 用户选 B（本地）→ 创建 `mode: "local"` 配置，需确认 HuggingFace Token
- 如用户未明确选择，默认使用云端转录（A），并告知用户

根据用户选择，在工作目录创建 transcribe_config.json：

**云端转录配置（mode: cloud）：**
```
{
  "mode": "cloud",
  "api_key": "<用户的DashScope API Key>",
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "video_file": "<原始视频文件名>",
  "frame_path": "人物静帧.jpg",
  "output_dir": "<输出目录>",
  "segments": [
    {"file": "<路径>/_seg1.mp3", "offset": 0},
    {"file": "<路径>/_seg2.mp3", "offset": 240},
    {"file": "<路径>/_seg3.mp3", "offset": 480},
    {"file": "<路径>/_seg4.mp3", "offset": 720}
  ]
}
```

**本地转录配置（mode: local）：**
```
{
  "mode": "local",
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "video_file": "<原始视频文件名>",
  "frame_path": "人物静帧.jpg",
  "output_dir": "<输出目录>",
  "hf_token": "<HuggingFace Access Token，用于 pyannote.audio 声纹分离>",
  "model_size": "medium",
  "segments": [
    {"file": "<路径>/_seg1.mp3", "offset": 0},
    {"file": "<路径>/_seg2.mp3", "offset": 240},
    {"file": "<路径>/_seg3.mp3", "offset": 480},
    {"file": "<路径>/_seg4.mp3", "offset": 720}
  ]
}
```

如果用户还没有 DashScope API Key（仅云端转录需要），引导用户去 https://bailian.console.aliyun.com/?tab=model#/api-key 注册获取。详细说明见 references/dashscope_setup.md。

如果用户还没有 HuggingFace Token（仅本地转录需要），引导用户：
1. 注册 HuggingFace 账号：https://huggingface.co/join
2. 生成 Access Token：https://huggingface.co/settings/tokens
3. 接受 pyannote 模型条款：https://huggingface.co/pyannote/speaker-diarization-3.1

### Step 3: 运行转录

根据 Step 2.5 中用户选择的转录方式（配置中的 `mode` 字段）执行对应脚本。

> `<skill_dir>` 指本技能文件所在目录。

#### 3A. 云端转录 — Qwen3-ASR-Flash（推荐 ✅）

使用 scripts/transcribe_qwen.py 脚本：

```
python <skill_dir>/scripts/transcribe_qwen.py --config transcribe_config.json
```

脚本执行：
1. 逐段调用 Qwen3-ASR-Flash API 转录（使用 `dashscope.MultiModalConversation.call(model="qwen3-asr-flash")`）
2. 合并所有段的文本为带时间码的原始转录文本（每段以 `[MM:SS]` 开头，基于段偏移）
3. 生成 <标题>.md（带时间码，先不区分说话人，第一行嵌入静帧引用）

**优势：** 中文识别准确率高，标点/断句自然，专有名词识别好。

#### 3B. 本地转录 — faster-whisper + pyannote.audio（备选 ⚠️）

> **⚠️ 质量警告：本地转录效果明显差于云端方案。**
> - 中文识别错误率显著更高，尤其人名、专有名词、口语化表达
> - 标点不准确，可能影响后续 LLM 角色映射效果
> - 仅建议在无网络环境、API 不可用、或用户明确要求本地处理时使用
> - 如对转录质量有要求，请优先使用 3A 云端方案

使用 scripts/transcribe_local.py 脚本：

```
python <skill_dir>/scripts/transcribe_local.py --config transcribe_config.json
```

**前置条件：** 需要安装依赖：
```
pip install faster-whisper pyannote.audio
```

脚本执行（逐段处理）：
1. 加载 pyannote.audio 声纹分离模型（`pyannote/speaker-diarization-3.1`，首次使用自动下载）
2. 加载 faster-whisper medium 模型（首次使用自动下载，约 1.5GB）
3. 对每个 4 分钟段执行：
   - **a. pyannote.audio 声纹分离**：识别段内不同说话人，输出带时间戳的说话人轮次（SPEAKER_00, SPEAKER_01, ...）
   - **b. faster-whisper 转录**：生成带时间戳的文本片段
   - **c. 时间戳对齐**：将每个 whisper 文本片段与 pyannote 说话人标签对齐（取片段中点对应的说话人）
4. 合并所有段，输出带时间码和 `**SPEAKER_00**` / `**SPEAKER_01**` 标签的文本（时间码精确到秒）
5. 生成 <标题>.md（带时间码 + SPEAKER 标签，第一行嵌入静帧引用）

**模型选择建议（faster-whisper）：**
| 模型 | 大小 | 速度 | 中文质量 | 说明 |
|------|------|------|---------|------|
| tiny | 75MB | 最快 | 很差 | 不推荐中文 |
| base | 145MB | 快 | 差 | 仅快速预览用 |
| small | 466MB | 中 | 一般 | 最低可接受 |
| **medium** | 1.5GB | 慢 | 较好 | **推荐（默认）** |
| large-v3 | 3GB | 最慢 | 最好 | 有 GPU 时可考虑 |

> 即使使用 large-v3 模型，中文转录质量仍不及 Qwen3-ASR-Flash 云端方案。

**声纹分离说明：**
- pyannote.audio 基于声纹特征区分说话人，输出 SPEAKER_00/01/... 标签
- 采访场景通常 2 人（采访者+受访人），脚本默认 `min_speakers=2, max_speakers=2`
- SPEAKER 标签需在 Step 3.5 中由 LLM 映射为"采访者"/"受访人"角色

### Step 3.5: LLM 智能说话人识别（必须执行！）

**重要：** 无论云端还是本地转录，都需要通过 LLM 完成说话人识别，但任务不同：

- **云端模式**：Qwen3-ASR-Flash 输出为连续文本（无说话人信息），LLM 需做完整的语义分析切分
- **本地模式**：pyannote.audio 已基于声纹区分出 SPEAKER_00/SPEAKER_01，LLM 只需将标签映射为"采访者"/"受访人"角色（任务更简单，准确率更高）

> **注意：** 本地转录（faster-whisper）的文本质量较差，可能影响 LLM 角色映射判断。如发现识别效果不佳，建议切换到云端转录方案。

#### 方法 A：云端模式 — LLM 语义分析切分

**方式 A1：Agent 自身执行（推荐）**

如果 Agent 本身即是 LLM（如 Claude Code、Codex、WorkBuddy 等），直接阅读转录文本并按以下 prompt 输出结果：

```
You are a professional transcript editor. Below is a raw transcription of an interview video. The text contains dialogue from two speakers: the interviewer (采访者) and the interviewee (受访人), but they are mixed together in one continuous block. Each line starts with a timestamp like [MM:SS] indicating its position in the video.

Your task:
1. Split the text into individual dialogue turns (each question and each answer should be separate).
2. Label each turn with **采访者** or **受访人**, followed by the timestamp of its first line.
3. Each turn should be on its own line(s), separated by a blank line.
4. Do NOT merge multiple questions into one block or multiple answers into one block.
5. Keep the original wording exactly as-is, do not paraphrase.
6. Preserve the timestamp at the start of each dialogue turn.
7. If a short utterance like "嗯" or "明白" is from the interviewer, label it as 采访者.

Output format:
**采访者** [MM:SS]
[content]

**受访人** [MM:SS]
[content]

**采访者** [MM:SS]
[content]

...and so on for each turn.

IMPORTANT: Output ONLY the labeled dialogue with timestamps. No preamble, no summary, no explanation.

Raw transcript:
{raw_text}
```

**方式 A2：调用外部 LLM API**

如需通过 Python 调用 Qwen-Plus API：

```python
import dashscope
dashscope.api_key = API_KEY

prompt = """You are a professional transcript editor. Below is a raw transcription of an interview video. The text contains dialogue from two speakers: the interviewer (采访者) and the interviewee (受访人), but they are mixed together in one continuous block. Each line starts with a timestamp like [MM:SS] indicating its position in the video.

Your task:
1. Split the text into individual dialogue turns (each question and each answer should be separate).
2. Label each turn with **采访者** or **受访人**, followed by the timestamp of its first line.
3. Each turn should be on its own line(s), separated by a blank line.
4. Do NOT merge multiple questions into one block or multiple answers into one block.
5. Keep the original wording exactly as-is, do not paraphrase.
6. Preserve the timestamp at the start of each dialogue turn.
7. If a short utterance like "嗯" or "明白" is from the interviewer, label it as 采访者.

Output format:
**采访者** [MM:SS]
[content]

**受访人** [MM:SS]
[content]

...and so on for each turn.

IMPORTANT: Output ONLY the labeled dialogue with timestamps. No preamble, no summary, no explanation.

Raw transcript:
{raw_text}"""

response = dashscope.Generation.call(
    model='qwen-plus',
    messages=[{'role': 'user', 'content': prompt}],
    result_format='message'
)
result = response.output.choices[0].message.content
```

#### 方法 B：本地模式 — LLM 角色映射

本地转录已包含 SPEAKER_00/SPEAKER_01 标签，LLM 只需判断哪个是采访者、哪个是受访人：

```
以下是一段采访的转录文本，已通过声纹分离区分出两个说话人（SPEAKER_00 和 SPEAKER_01）。
每段对话开头有时间码 [MM:SS]，表示该段在视频中的位置。
请根据对话内容判断哪个是采访者（提问方），哪个是受访人（回答方），然后将标签替换为"采访者"和"受访人"。

判断规则：
- 采访者：提问题，句子短，含引导性词汇
- 受访人：回答问题，句子长，讲述个人经历和观点

严格要求：
1. 严格保持原文内容不变，只替换说话人标签
2. 保留每段对话开头的时间码
3. 不要添加任何额外说明

转录文本：
{raw_text}
```

然后将 LLM 输出替换 MD 文件中的原始对话文本，并更新"说话人识别"元数据：
- 云端模式：`LLM 语义分析`
- 本地模式：`pyannote.audio 声纹分离 + LLM 角色映射`

**长文本处理：** LLM 单次输入建议不超过 8000 字符，超过时分段处理后拼接。

### Step 3.6: 生成内容摘要与人物信息（必须执行！）

**重要：** 说话人识别（Step 3.5）完成后，必须调用 LLM 对转录内容生成摘要和受访人人物信息，并将结果插入到文档正文最前面（静帧之后、对话内容之前）。这一步让读者快速了解采访的核心内容和受访人背景。

**方式 A：Agent 自身执行（推荐）**

如果 Agent 本身即是 LLM，直接阅读已分好说话人的转录文本并按以下 prompt 输出结果。

**方式 B：调用外部 LLM API**

```python
import dashscope
dashscope.api_key = API_KEY

prompt = """你是一个专业的采访内容编辑助手。以下是一段采访的转录文本，已按采访者和受访人区分好段落。请基于对话内容生成以下两部分：

## 一、内容摘要

用 3-5 句话概括本次采访的核心内容，包括：
- 采访的主要话题和讨论方向
- 受访人表达的核心观点或态度
- 对话中提到的关键事件或经历

## 二、人物信息

从对话内容中提取受访人的关键信息，以列表形式呈现。提取以下字段（如对话中未提及则标注"未提及"）：

| 字段 | 内容 |
|------|------|
| 学校/单位 | |
| 专业/学院 | |
| 年级/身份 | |
| 家乡 | |
| 关键经历 | |
| 核心观点 | |

严格要求：
1. 仅基于转录文本内容提取，不要编造或推测
2. 内容简洁精炼，摘要不超过 150 字
3. 人物信息中"关键经历"和"核心观点"各不超过 50 字
4. 输出格式严格为 Markdown

转录文本：
{transcribed_text}"""

response = dashscope.Generation.call(
    model='qwen-plus',
    messages=[{'role': 'user', 'content': prompt}],
    result_format='message'
)
summary_content = response.output.choices[0].message.content
```

**插入文档：** 将 LLM 输出的摘要和人物信息插入到 `<标题>.md` 文件中，位置在静帧引用行之后、元数据之前。最终文档结构为：

```markdown
![人物静帧](人物静帧.jpg)

## 内容摘要

<LLM 生成的摘要内容>

## 人物信息

<LLM 生成的人物信息表格>

---

> 转录工具：Qwen3-ASR-Flash / faster-whisper
> 说话人识别：LLM 语义分析
> 摘要与人物信息：LLM 生成
> 转录日期：YYYY-MM-DD

---

## 采访记录

**采访者** [00:00]
<对话内容>

**受访人** [00:15]
<对话内容>

**采访者** [01:30]
<对话内容>

...
```

**长文本处理：** 同 Step 3.5，超过 8000 字符时分段处理后合并摘要。

### Step 4: 输出与分发

根据用户需求选择输出方式。**本地 Markdown 文件始终生成**（Step 3 已完成），以下为可选的分发目标：

#### 4A. 在线文档平台（用户指定时执行）

用户可能需要将转录文档上传到在线协作平台。根据用户指定的平台选择对应工具：

**钉钉文档示例：**

如用户环境已配置钉钉 CLI（如 `dws`），可使用以下命令上传：

```bash
# 先移除 MD 中的人物静帧引用行（本地图片无法上传）
# 用 Python 读取 MD，删除静帧引用行，写入 _upload.md

dws doc create --name "<拍摄时间+人物简介>" --content-file "_upload.md" --content-format markdown
```

**内容上限处理：** 部分平台 API 限制内容长度（如钉钉 doc create 限制 10000 字符）。超长文档需分段：
1. 将完整内容按 8000 字符分割（留余量），在 `采访者` / `受访人` 标签边界切分，保持段落完整
2. 先创建文档上传第一段
3. 后续段落通过追加 API 上传

**插入人物静帧：**
```bash
dws doc media insert --node "<node_id>" --file "人物静帧.jpg" --index 0 -y
```

**其他平台：** 飞书文档、腾讯文档、Notion 等平台，参照对应平台的 API/SDK 进行上传。

#### 4B. 本地文件输出（默认）

转录完成后 `<标题>.md` 已生成在 output_dir 中，包含：
- 第一行：人物静帧引用（本地路径）
- **内容摘要**：LLM 生成的 3-5 句话概括（Step 3.6 生成）
- **人物信息**：受访人关键信息表格（Step 3.6 生成）
- 元数据：转录工具、说话人识别方法、摘要生成方法、转录日期
- 正文：带时间码和 `**采访者**` / `**受访人**` 标签的对话内容（如 `**采访者** [05:30]`）

可直接交付给用户，或后续按需上传到任意平台。

#### 4C. 其他平台（按需扩展）

核心交付物为 Step 3.6 生成的 Markdown 文件（含摘要、人物信息、对话正文）。用户可根据需要上传到任意平台，参照对应平台的 API/CLI 工具进行操作。

### Step 5: 清理临时文件

```bash
rm _seg*.mp3 _upload.md *_raw.txt *segments.json transcribe_config.json
```

保留的文件：
- `<标题>.md`（最终转录文档）
- `人物静帧.jpg`（人物静帧图片）

## 说话人识别说明

**方法演进：**
1. ❌ 启发式方法（关键词+段落长度）：已废弃，完全不可靠，所有对话混在一个段落
2. ✅ **云端模式：LLM 语义分析**：Qwen3-ASR-Flash 转录输出连续文本，LLM 理解对话内容智能切分，准确率 95%+
3. ✅ **本地模式：pyannote.audio 声纹分离 + LLM 角色映射**：pyannote 基于声纹区分说话人，LLM 将 SPEAKER 标签映射为采访者/受访人角色

Qwen3-ASR-Flash 不直接支持说话人分离，fun-asr 虽支持但需 OSS 文件上传（file:// 本地路径不可用）。云端最优方案：Qwen3-ASR-Flash 转录 + LLM 语义分段。本地备选方案：faster-whisper 转录 + pyannote.audio 声纹分离 + LLM 角色映射。

## 注意事项

- **文档命名规范**：文档标题为 `拍摄时间+人物简介（≤10字）` 格式，如 `26-0509 车辆学院直博生`，详见 Step 2
- **说话人识别必须用 LLM**：启发式方法已被验证不可用，转录完成后必须执行 Step 3.5（云端=语义切分，本地=角色映射）
- **LLM prompt 必须强调逐轮分段**：如果 prompt 只说"切分段落"，LLM 可能将同一说话人的所有内容合并成一大段。prompt 必须明确要求"每轮问答独立成段，不要合并同一说话人的多轮对话"，并用 `**采访者**` / `**受访人**` 标签交替输出
- **摘要与人物信息必须生成**：说话人识别完成后必须执行 Step 3.6，生成内容摘要和受访人人物信息，插入到文档正文最前面（静帧之后、元数据之前），让读者快速了解采访核心内容和受访人背景
- **LLM 调用方式**：如 Agent 自身即是 LLM（Claude Code、Codex 等），可直接在对话中执行 Step 3.5/3.6 的语义分析，无需额外 API 调用；否则使用 Python 调用 Qwen-Plus API
- **转录 API**：使用 `dashscope.MultiModalConversation.call(model="qwen3-asr-flash")`，不要用 `Transcription.call`（后者签名已变更）
- **转录方式选择**：转录前必须执行 Step 2.5 询问用户选择转录方式，并明确告知本地转录质量较差。优先推荐云端 Qwen3-ASR-Flash（准确率高），本地 faster-whisper + pyannote.audio 仅作为备选（中文质量明显较差）
- **本地声纹分离**：使用 pyannote.audio（`pyannote/speaker-diarization-3.1`），需 HuggingFace Token + 接受模型条款，采访场景固定 2 人
- Windows 路径使用正斜杠 / ，避免中文路径传给 API
- **Windows 下 `bc` 不可用**：数值计算用 Python 替代，不要在 bash 中用 `bc` 做浮点比较
- **bash heredoc 会吃掉 `\s` 转义**：正则表达式需写入 .py 文件执行，不要用 inline heredoc 传正则
- **长文本 LLM 分段**：LLM 单次输入建议不超过 8000 字符，超过时分段处理后拼接
