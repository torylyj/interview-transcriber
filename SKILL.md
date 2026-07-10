---
name: interview-transcriber
description: |
  采访转录全流程处理技能（支持视频与音频输入）。默认使用本地转录（SenseVoice/Paraformer 魔搭社区中文模型，离线可用、无需 API Key）；可选云端转录（Qwen3-ASR-Flash，准确率更高，需 DashScope API Key）作为升级方案。流程：检测输入类型（视频/音频，音频跳过转 MP3 且无需静帧）-> 模型按能力自动决定是否切段 -> 本地/云端转录（可选 pyannote.audio 声纹分离）-> LLM 智能说话人识别（支持多说话人，保留时间码） -> LLM 生成内容摘要与受访人人物信息（置于文档正文最前面） -> 直接生成带时间码的 Word 文档（.docx，全程无 Markdown 中间文件，视频输入时嵌入静帧）-> 自检并适度精简口语语气词 -> 交付前预览确认 -> 可选输出到在线文档平台/本地文件等。
  适用于任何支持 bash 命令执行和文件读写的 AI 编码代理（Agent）。全流程处理完毕后，会主动询问用户希望将整理好的文档发送到哪里，并提示云端转录作为更高精度的可选方案。
agent_created: true
---

# 采访视频转录

## 概述

将采访内容（视频或音频）全流程处理为带说话人识别的转录文档：输入预处理（音频跳过转 MP3、无静帧）-> 默认本地转录（SenseVoice，离线可用）-> 模型按能力自动决定是否切段 -> 说话人识别（支持多说话人）-> 生成摘要与人物信息 -> 直接生成 Word 文档（.docx，全程无 Markdown 中间文件）-> 自检精简语气词 -> 交付前预览确认 -> 可选分发到在线文档平台。全部处理完成后主动询问用户要将文档发送到哪里，并提示云端转录作为更高精度的可选方案。

**核心流程（Step 1-3.6）** 与输出目标无关，始终执行。**输出分发（Step 4）** 根据用户需求选择目标平台。

**转录方式选择（默认本地）：** 默认使用**本地转录（SenseVoice）**，离线可用、无需任何 API Key，开箱即用。仅当用户明确要求更高准确率、或主动提供 DashScope API Key 时，才切换为云端转录（Qwen3-ASR-Flash）。两者差异：
- **本地转录（默认）— SenseVoice/Paraformer** — 阿里达摩院中文模型，从魔搭社区下载，中文质量优秀、接近云端，无需 HuggingFace、无需 API Key，离线可用
- **本地转录 — faster-whisper large-v3（备选）** — 通用多语言模型，中文质量一般，需 HuggingFace 镜像
- **云端转录（可选升级）— Qwen3-ASR-Flash** — 中文识别准确率最高、标点断句最自然，需 DashScope API Key 与联网；流程最后会提示用户此可选方案

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

### Step 1: 输入预处理（ffmpeg）

**本技能同时支持视频输入和音频输入。** 先检测文件类型，再决定预处理步骤；音频输入无需「视频转 MP3」这一步，也没有静帧。

**1a. 检测输入类型**

| 类型 | 扩展名 |
|------|--------|
| 视频 | `.mp4` `.mov` `.avi` `.mkv` `.flv` `.wmv` `.webm` |
| 音频 | `.mp3` `.wav` `.m4a` `.aac` `.flac` `.ogg` `.wma` |

**1b. 视频输入 → 提取静帧 + 转 MP3**

```
# 提取人物静帧（视频第 5 秒，800px 宽，文档中按 280px 居中显示）
ffmpeg -i "输入.mp4" -ss 5 -vframes 1 -q:v 2 -vf "scale=800:-1" "人物静帧.jpg" -y

# 视频转 MP3（16kHz 单声道 192kbps），作为后续转录的工作音频
ffmpeg -i "输入.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y
```

- `frame_path = "人物静帧.jpg"`（视频才有画面）
- `audio_file = "输出.mp3"`（工作音频，供后续转录使用）

**1c. 音频输入 → 跳过 MP3 转换，无静帧**

音频本身就是音频，无需「视频转 MP3」预处理；音频没有画面，也不提取静帧。

```
# 可选：统一重采样为 16kHz 单声道（ASR 模型推荐格式，非必须）
ffmpeg -i "输入.m4a" -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y
```

- `frame_path = null`（音频无画面）
- `audio_file = "输出.mp3"`（重采样后）或直接使用原始音频文件（如已是 16k 单声道）

**1d. 多段输入合并（如用户指定多个文件需合并转录）**

```
# 先将每个文件转为统一格式的 MP3，再用 ffmpeg concat filter 合并
```

> **切段不在 Step 1 进行**：是否切段由 Agent 按所选转录模型的时长能力在 **Step 2.6** 中自动决策（不询问用户，详见该步）。

### Step 2: 确定文档标题

**文档命名规范：**

文档标题采用 `拍摄时间+人物简介` 格式：
- **拍摄时间**：按以下 fallback 链提取（不强制依赖文件夹命名）：① 文件夹名含 `YY-MMDD` 模式（如 `清华26-0509` → `26-0509`）；② 文件名含 `YY-MMDD`；③ 文件创建/修改时间格式化为 `YY-MMDD`；④ 均失败时标记为 `未知日期`，仍保留人物简介
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

### Step 2.5: 确定转录方式（默认本地）& 创建转录配置

**默认使用本地转录（SenseVoice），无需询问用户。** 仅在以下情况才切换为云端或询问：
- 用户主动要求"用云端 / 用 Qwen / 用 API 转录"，或提供了 DashScope API Key
- 用户明确要求使用其他本地模型（如 paraformer / whisper）

否则直接以本地模式（`mode: "local"`，默认 sensevoice）创建配置并继续，**不打断用户确认**。

如需让用户选择（例如用户未明确、但你判断需要确认），可提出以下问题：

---

> 请选择转录方式（默认本地，可跳过直接开始）：
>
> **A. 本地转录（SenseVoice，默认）** — 离线可用，无需 API Key
> - 阿里达摩院中文模型，从魔搭社区下载，中文质量优秀、接近云端
> - 无需 HuggingFace、无需 API Key，开箱即用
> - 可选模型：sensevoice（默认）/ paraformer / whisper
>
> **B. 云端转录（Qwen3-ASR-Flash，可选升级）** — 准确率最高
> - 中文识别准确率最高、标点断句最自然
> - 需要 DashScope API Key（阿里云百炼，有免费额度）与联网
>
> 回复 A（或留空）使用本地；回复 B 并附上 API Key 使用云端：

---

**根据用户选择（或不选择）创建配置：**

- 用户明确要求云端（B）→ 创建 `mode: "cloud"` 配置，需确认 DashScope API Key
- 默认 / 用户选本地（A）→ 创建 `mode: "local"` 配置，模型默认 sensevoice；HuggingFace Token 可选（用于声纹分离，无则跳过）
- **如用户未明确选择，默认使用本地转录（`mode: "local"`），不询问、不打断**

根据用户选择，在工作目录创建 transcribe_config.json：

**云端转录配置（mode: cloud）：**
```
{
  "mode": "cloud",
  "api_key": "<用户的DashScope API Key>",
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "source_file": "<原始输入文件名，如 输入.mp4 / 输入.m4a>",
  "input_type": "video 或 audio",
  "audio_file": "<Step 1 产出的工作音频，如 输出.mp3>",
  "frame_path": "人物静帧.jpg 或 null（音频输入时为 null）",
  "output_dir": "<输出目录>"
  // segments 在 Step 2.6 根据切段决策后填入，此处暂不写
}
```

**本地转录配置（mode: local）：**
```
{
  "mode": "local",
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "source_file": "<原始输入文件名，如 输入.mp4 / 输入.m4a>",
  "input_type": "video 或 audio",
  "audio_file": "<Step 1 产出的工作音频，如 输出.mp3>",
  "frame_path": "人物静帧.jpg 或 null（音频输入时为 null）",
  "output_dir": "<输出目录>",
  "hf_token": "<HuggingFace Access Token，用于 pyannote.audio 声纹分离，可选>",
  "model": "sensevoice",
  "max_speakers": 2  // 声纹分离说话人上限；群访等多人场景可设更大值（如 5）
  // segments 在 Step 2.6 根据切段决策后填入，此处暂不写
}
```

**model 字段可选值：**
| 值 | 模型 | 下载源 | 中文质量 | 大小 | 需要 HF Token |
|----|------|--------|---------|------|--------------|
| `sensevoice` | SenseVoiceSmall | 魔搭社区 | ⭐⭐⭐⭐ | ~500MB | 否 |
| `paraformer` | Paraformer-large | 魔搭社区 | ⭐⭐⭐⭐ | ~800MB | 否 |
| `whisper` | faster-whisper large-v3 | HuggingFace | ⭐⭐⭐ | ~3GB | 否（但需镜像） |

如果用户还没有 DashScope API Key（仅云端转录需要），引导用户去 https://bailian.console.aliyun.com/?tab=model#/api-key 注册获取。详细说明见 references/dashscope_setup.md。

如果用户还没有 HuggingFace Token（仅本地声纹分离需要，ASR 模型不需要），引导用户：
1. 注册 HuggingFace 账号：https://huggingface.co/join
2. 生成 Access Token：https://huggingface.co/settings/tokens
3. 接受 pyannote 模型条款：https://huggingface.co/pyannote/speaker-diarization-3.1

> **无 Token 也可用**：SenseVoice/Paraformer 从魔搭社区下载，无需 HuggingFace。仅 pyannote.audio 声纹分离需要 Token。无 Token 时可跳过声纹分离，转录后使用 LLM 语义切分说话人（同云端模式）。

**模型下载说明：**

| 模型 | 下载源 | 需要 HF Token | 国内速度 |
|------|--------|--------------|---------|
| SenseVoiceSmall | 魔搭社区 (modelscope.cn) | 否 | ⭐⭐⭐⭐⭐ 直连 |
| Paraformer-large | 魔搭社区 (modelscope.cn) | 否 | ⭐⭐⭐⭐⭐ 直连 |
| faster-whisper | HuggingFace (需镜像) | 否 | ⭐⭐⭐ 需镜像 |
| pyannote.audio | HuggingFace (需镜像) | 是 | ⭐⭐⭐ 需镜像 |

**环境变量配置：**
```bash
# 使用镜像（脚本默认行为，无需手动设置）
export HF_ENDPOINT=https://hf-mirror.com

# 关闭镜像（直连 HuggingFace，需代理）
unset HF_ENDPOINT

# 自定义镜像源
export HF_ENDPOINT=https://your-mirror.com
```

**手动下载（自动下载失败时）：**

SenseVoice / Paraformer（从魔搭社区下载，国内直连）：
```bash
pip install funasr modelscope
# SenseVoice
python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"
# Paraformer
python -c "from modelscope import snapshot_download; snapshot_download('iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch')"
```

faster-whisper 模型（从 HuggingFace 下载，需镜像）：
```bash
# 方式 1: hf-mirror 镜像站（推荐）
pip install -U huggingface_hub
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download Systran/faster-whisper-medium --local-dir ./whisper-medium

# 方式 2: ModelScope 魔搭社区
pip install modelscope
# 访问 https://modelscope.cn 搜索 whisper 模型下载

# 方式 3: 浏览器手动下载
# 打开 https://hf-mirror.com/Systran/faster-whisper-medium 下载所有文件
```

pyannote.audio 声纹分离模型：
```bash
# 需先注册 HuggingFace 账号并接受模型条款
# 1. 注册: https://huggingface.co/join
# 2. 生成 Token: https://huggingface.co/settings/tokens
# 3. 接受条款: https://huggingface.co/pyannote/speaker-diarization-3.1

export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download pyannote/speaker-diarization-3.1 --token YOUR_HF_TOKEN
```

### Step 2.6: 切段决策（模型自动，不询问用户）

切段决策必须放在 Step 2.5 选定转录方式**之后**——不同方式对单次音频时长的要求不同，因此要先知道选了哪种，才能决定要不要切、怎么切。

**a. 获取工作音频时长（ffprobe）**
```
DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "输出.mp3")
```

**b. 按所选模型能力自动决策（不询问用户）**

- **云端（Qwen3-ASR-Flash）**：单次调用时长上限 **5 分钟**
  - 时长 > 5 分钟 → **必须切段**（自动按 4 分钟/段切，留 1 分钟余量避免边界截断）。仅记录日志，不打断用户确认
  - 时长 ≤ 5 分钟 → 无需切段，整段直接传入
- **本地（SenseVoice / Paraformer / whisper）**：无单次时长硬限制，但长音频会显著增加内存占用与崩溃风险
  - 较长音频（如 > 20 分钟）→ Agent **自动切段**（按 4 分钟/段）以控制内存与稳定性
  - 较短音频 → 直接整段传入，无需切段

> 切段决策完全由 Agent 基于所选模型的时长能力自动完成，**不向用户提问、不打断流程**。

**c. 切段命令（需要切段时，按 4 分钟/段）**
```
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0 -t 240 _seg1.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 240 -t 240 _seg2.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 480 -t 240 _seg3.mp3 -y
...
```

**e. 写入 segments 到配置（覆盖 Step 2.5 创建的配置文件）**

- 切段时：
  ```json
  "segments": [
    {"file": "_seg1.mp3", "offset": 0},
    {"file": "_seg2.mp3", "offset": 240},
    {"file": "_seg3.mp3", "offset": 480}
  ]
  ```
- 不切段（整段）时：
  ```json
  "segments": [
    {"file": "输出.mp3", "offset": 0}
  ]
  ```

### Step 3: 运行转录

根据 Step 2.5 确定的转录方式（配置中的 `mode` 字段，默认 `local`）执行对应脚本。

> `<skill_dir>` 指本技能文件所在目录。

#### 3A. 云端转录 — Qwen3-ASR-Flash（推荐 ✅）

使用 scripts/transcribe_qwen.py 脚本：

```
python <skill_dir>/scripts/transcribe_qwen.py --config transcribe_config.json
```

脚本执行：
1. 逐段调用 Qwen3-ASR-Flash API 转录（使用 `dashscope.MultiModalConversation.call(model="qwen3-asr-flash")`）
2. 合并所有段的文本为带时间码的原始转录文本（每段以 `[MM:SS]` 开头，基于段偏移）
3. 生成 `<标题>_transcript.json`（结构化中间数据，含 metadata + `raw_text` 原始转录文本，**不生成 Markdown**；`raw_text` 供 Step 3.5 LLM 使用，最终在 Step 3.8 由 `build_docx.py` 直接转为 .docx）

**优势：** 中文识别准确率高，标点/断句自然，专有名词识别好。

#### 3B. 本地转录 — 多模型可选（备选 ⚠️）

> **⚠️ 质量提示：**
> - **SenseVoice / Paraformer**：阿里达摩院中文模型，质量接近云端，从魔搭社区下载（国内速度快）
> - **faster-whisper large-v3**：通用多语言模型，中文质量一般，人名/专有名词错误率较高
> - 如对转录质量有要求，请优先使用 3A 云端方案

使用 scripts/transcribe_local.py 脚本：

```
python <skill_dir>/scripts/transcribe_local.py --config transcribe_config.json
# 可通过 --model 参数覆盖配置中的模型选择
python <skill_dir>/scripts/transcribe_local.py --config transcribe_config.json --model sensevoice
```

**前置条件：** 根据选择的模型安装依赖：
```
# SenseVoice / Paraformer（推荐，从魔搭社区下载，无需 HuggingFace）
pip install funasr

# faster-whisper（备选，从 HuggingFace 下载）
pip install faster-whisper

# 声纹分离（所有模型通用，可选 —— 无 Token 时跳过声纹分离，改用 LLM 语义切分）
pip install pyannote.audio
```

> **模型下载说明：**
> - SenseVoice/Paraformer 从魔搭社区（modelscope.cn）自动下载，国内直连，速度快
> - faster-whisper 从 HuggingFace 下载，脚本内置多镜像站自动降级（hf-mirror.com → 官方）
> - pyannote.audio 需要 HuggingFace Token + 接受模型条款
> - 无 HuggingFace Token 时可跳过声纹分离，转录后使用 LLM 语义切分说话人（同云端模式）

脚本执行（逐段处理）：
1. 加载 ASR 模型（SenseVoice/Paraformer 从魔搭社区下载，faster-whisper 从 HuggingFace 下载）
2. 如有 hf_token，加载 pyannote.audio 声纹分离模型（首次使用自动下载）
3. 对每个音频段执行（切段时为 4 分钟段，未切段时为整段音频）：
   - **a. ASR 转录**：生成带时间戳的文本片段
   - **b. 声纹分离**（如有 Token）：pyannote.audio 识别说话人轮次
   - **c. 时间戳对齐**：将文本片段与说话人标签对齐
4. 合并所有段，输出带时间码和 `**SPEAKER_00**` / `**SPEAKER_01**` 标签的文本（时间码精确到秒）
5. 生成 `<标题>_transcript.json`（结构化中间数据，含 metadata + 带 SPEAKER 标签的 `raw_text`；**不生成 Markdown**，最终在 Step 3.8 由 `build_docx.py` 直接转为 .docx）

**本地模型对比：**
| 模型 | 来源 | 大小 | 中文质量 | 下载方式 | 推荐 |
|------|------|------|---------|---------|------|
| SenseVoiceSmall | 魔搭社区 | ~500MB | ⭐⭐⭐⭐ | 自动（国内直连） | ✅ 首选 |
| Paraformer-large | 魔搭社区 | ~800MB | ⭐⭐⭐⭐ | 自动（国内直连） | ✅ 备选 |
| faster-whisper large-v3 | HuggingFace | ~3GB | ⭐⭐⭐ | 镜像站降级 | ⚠️ 通用 |

> SenseVoice/Paraformer 为阿里达摩院专为中文优化的模型，质量明显优于 Whisper，且从国内魔搭社区下载，无需翻墙。
> Whisper large-v3 虽为最大通用模型，但中文质量仍不及 SenseVoice。

**声纹分离说明：**
- pyannote.audio 基于声纹特征区分说话人，输出 SPEAKER_00/01/... 标签
- 默认说话人范围 `min_speakers=1, max_speakers=2`；群访等多人场景可在 `transcribe_config.json` 设 `max_speakers`（如 5）放宽
- SPEAKER 标签需在 Step 3.5 中由 LLM 映射为具体角色（采访者/受访人，或群访中的记者乙、旁白等）

### Step 3.5: LLM 智能说话人识别（必须执行！）

**重要：** 无论云端还是本地转录，都需要通过 LLM 完成说话人识别，但任务不同：

- **云端模式**：Qwen3-ASR-Flash 输出为连续文本（无说话人信息），LLM 需做完整的语义分析切分，并识别所有出现的说话人（通常采访者+受访人，也可能有其他人）
- **本地模式**：pyannote.audio 已基于声纹区分出多个说话人（SPEAKER_00/SPEAKER_01/…），LLM 将标签映射为对应的角色名（采访者/受访人，或其他如记者乙、旁白等）

> **注意：** 本地转录（faster-whisper）的文本质量较差，可能影响 LLM 角色映射判断。如发现识别效果不佳，建议切换到云端转录方案。

#### 方法 A：云端模式 — LLM 语义分析切分

**方式 A1：Agent 自身执行（推荐）**

如果 Agent 本身即是 LLM（如 Claude Code、Codex、WorkBuddy 等），直接阅读转录文本并按以下 prompt 输出结果：

```
You are a professional transcript editor. Below is a raw transcription of an interview. The text contains dialogue from the interview participants — typically an interviewer (采访者) and an interviewee (受访人), but there may be more (e.g. other reporters in a group interview, a narrator, etc.). All speakers are mixed together in one continuous block. Each line starts with a timestamp like [MM:SS] indicating its position in the audio/video.

Your task:
1. Split the text into individual dialogue turns (each question and each answer should be separate).
2. Label each turn with the appropriate speaker role: **采访者** for interviewer, **受访人** for interviewee, and clear consistent labels for any other speakers (e.g. **记者乙**, **旁白**). Follow with the timestamp of its first line.
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

prompt = """You are a professional transcript editor. Below is a raw transcription of an interview. The text contains dialogue from the interview participants — typically an interviewer (采访者) and an interviewee (受访人), but there may be more (e.g. other reporters in a group interview, a narrator, etc.). All speakers are mixed together in one continuous block. Each line starts with a timestamp like [MM:SS] indicating its position in the audio/video.

Your task:
1. Split the text into individual dialogue turns (each question and each answer should be separate).
2. Label each turn with the appropriate speaker role: **采访者** for interviewer, **受访人** for interviewee, and clear consistent labels for any other speakers (e.g. **记者乙**, **旁白**). Follow with the timestamp of its first line.
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
以下是一段采访的转录文本，已通过声纹分离区分出 N 个说话人（SPEAKER_00、SPEAKER_01 …）。
每段对话开头有时间码 [MM:SS]，表示该段在视频中的位置。
请根据对话内容判断哪个是采访者（提问方），哪个是受访人（回答方），然后将标签替换为"采访者"和"受访人"。

判断规则：
- 采访者：提问题，句子短，含引导性词汇
- 受访人：回答问题，句子长，讲述个人经历和观点
- 若出现更多说话人（如群访中的其他记者、旁白等），按其在对话中的实际角色命名（如"记者乙""旁白"），并保持命名一致

严格要求：
1. 严格保持原文内容不变，只替换说话人标签为"**采访者**"和"**受访人**"
2. 保留每段对话开头的时间码
3. 不要添加任何额外说明

转录文本：
{raw_text}
```

然后将 LLM 输出整理为结构化数据，写入 `<标题>_document.json`（字段定义见 Step 3.6）。说话人识别方式记录为：
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

## 二、受访人信息

从对话内容中提取受访人的关键信息，以表格形式呈现。提取以下字段（如对话中未提及则标注"未提及"）：

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

**写入结构化文档数据（`_document.json`）：** Step 3.5/3.6/3.7 全部完成后，Agent 将最终结果整理为 `<标题>_document.json`，由 Step 3.8 的 `build_docx.py` 直接生成 .docx。**全程不生成 Markdown 文件。**

该 JSON 的字段定义（Agent 应基于 `<标题>_transcript.json` 的 metadata 字段 + 自身 LLM 输出组合而成）：

```json
{
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "frame_path": "人物静帧.jpg 或 null（音频输入时为 null）",
  "input_type": "video 或 audio",
  "source_file": "<原始输入文件名，如 输入.mp4 / 输入.m4a>",
  "transcription_tool": "通义千问 Qwen3-ASR-Flash（阿里云百炼）或 SenseVoice/Paraformer 模型名",
  "speaker_method": "LLM 语义分析 或 pyannote.audio 声纹分离 + LLM 角色映射",
  "summary_method": "LLM 生成",
  "date": "YYYY-MM-DD",
  "summary": "<LLM 生成的 3-5 句话摘要，多段落用 \\n 分隔>",
  "person_info": [
    {"field": "学校/单位", "value": "..."},
    {"field": "专业/学院", "value": "..."},
    {"field": "年级/身份", "value": "..."},
    {"field": "家乡", "value": "..."},
    {"field": "关键经历", "value": "..."},
    {"field": "核心观点", "value": "..."}
  ],
  "conversation": [
    {"speaker": "采访者", "timestamp": "[00:00]", "text": "<对话内容>"},
    {"speaker": "受访人", "timestamp": "[00:15]", "text": "<对话内容>"},
    {"speaker": "采访者", "timestamp": "[01:30]", "text": "<对话内容>"}
  ]
}
```

> `frame_path` 为 `null`（音频输入）时，`build_docx.py` 自动跳过静帧插入；`person_info` / `summary` 缺失时对应章节自动省略。

**最终 .docx 文档结构（build_docx.py 渲染结果）：**

```
# <标题>

<居中人物静帧，仅视频输入；音频输入时无此图>

📝 内容摘要
<LLM 生成的 3-5 句话概括>

👤 受访人信息
| 字段 | 内容 |
|------|------|
| 学校/单位 | ... |
| ...  | ... |

📋 文档信息
> 源文件：<source_file>
> 输入类型：视频 / 音频
> 转录工具：Qwen3-ASR-Flash / SenseVoice
> 说话人识别：LLM 语义分析
> 摘要与人物信息：LLM 生成
> 转录日期：YYYY-MM-DD
> 时间码精度：本地模式精确到秒；云端模式为段内估算值（4分钟粒度）

💬 采访记录
**采访者** [00:00]
<对话内容>

**受访人** [00:15]
<对话内容>
```

**长文本处理：** 同 Step 3.5，超过 8000 字符时分段处理后合并摘要。

### Step 3.7: 自检与语气词精简（生成文档后执行）

文档全部生成后，Agent **自行通读一遍采访记录正文**，对口语中的语气词/填充词做**适度精简**，让文字更利落。这是一次轻量润色，不是重写。

**a. 可删除的语气词/填充词（仅删明显冗余的）**

- 语气词：嗯、啊、呃、噢、哦、唉、诶、嘛、呀、哈
- 口头填充：那个、这个（作停顿填充时）、就是（无实义时）、然后（连续堆叠时）、其实（滥用时）、反正、怎么说呢
- 重复起头：如"我我我"、"就是就是"这类结巴重复

**b. 精简原则（严格遵守）**

1. **克制**：只删**明显多余**的语气填充词，"稍微减少一点"即可，不追求全部清除——保留必要的口语自然感
2. **不改原意**：绝不改写句子结构、不替换用词、不合并或拆分句子、不调整语序
3. **保留有实义的词**："这个方案"里的"这个"、"然后我们去了"里表时序的"然后"等**有实际含义时必须保留**，只删纯停顿填充
4. **保留时间码和说话人标签**：`**采访者** [MM:SS]` / `**受访人** [MM:SS]` 格式完全不动
5. **不动摘要与人物信息**：Step 3.6 生成的摘要/表格是提炼内容，本步只处理「💬 采访记录」正文

**c. 示例**

原文：
> **受访人** [02:15]
> 嗯，就是那个，我其实当时呢，就是想着说，然后就报了这个专业。

精简后：
> **受访人** [02:15]
> 我当时想着，就报了这个专业。

**d. 执行方式**

- Agent 自身即 LLM 时，直接读取 `<标题>_document.json` 中 `conversation` 的文本内容，按上述原则精简后更新 `conversation[].text` 并写回 `_document.json`
- 精简完成后**简要告知用户**：「已通读并精简了口语语气词」，不需要逐条列出改动

### Step 3.8: 构建 Word 文档（.docx，直接生成，无中间 Markdown）

所有文本处理（转录、说话人识别、摘要生成、语气词自检）完成后，由 `build_docx.py` **直接读取 `<标题>_document.json` 生成 Word 文档（.docx）**，全程不经过 Markdown：

```
python <skill_dir>/scripts/build_docx.py "<output_dir>/<标题>_document.json" "<output_dir>/<标题>.docx"
```

- `build_docx.py` 直接渲染：文档标题、居中人物静帧（仅视频输入、`frame_path` 非 null 时）、内容摘要、人物信息表格、文档信息引用块、采访记录（加粗说话人标签 + 时间码）
- 音频输入（`frame_path` 为 null）时自动跳过图片插入
- 生成后 `<标题>.docx` 即为最终交付物，**全程不生成任何 Markdown 文件**

**依赖安装：**

```bash
pip install python-docx pillow
```

> 注：python-docx 为必需；pillow 用于提升图片兼容性（处理扩展名与真实格式不符等情况），建议一并安装。

### Step 3.9: 交付前预览与轻量确认（清理临时文件之前）

`.docx` 生成后、**Step 5 清理临时文件之前**，必须先让用户快速确认内容准确性，尤其是说话人分得对不对。此时所有中间文件（`_transcript.json` / `_document.json` / 静帧等）仍在，便于纠错。

**向用户展示的预览内容：**
- 文档标题（如 `26-0509 车辆学院直博生`）
- 说话人识别结果概览：列出所有识别出的说话人角色及其大致轮次/字数（例如：`采访者 ~18 轮`、`受访人 ~15 轮`；若识别出多于两人则说明）
- 内容摘要要点（2-3 句）
- 提示文档已生成在 `output_dir`

**确认话术（自然、不机械）：**
> 文档整理好了，先给你确认一下：标题是《XX》，识别出采访者和受访人两方（若多说话人则列出），摘要大致是……。说话人分得对吗？有要改的地方告诉我，没问题我就定稿了。

**处理规则：**
- 用户确认无误 → 继续 Step 4 / Step 5 / Step 6
- 用户指出问题 → 回到对应步骤修正（说话人颠倒/错分 → 回 Step 3.5 重映射；标题错 → 改 Step 2；摘要偏差 → 回 Step 3.6），修正后重新生成 `.docx` 并再次确认
- **此环节为轻量收尾确认，不打断主流程自动执行**；若用户明确说"直接定稿不用确认"，可跳过

### Step 4: 输出与分发

根据需求选择输出方式。**本地 Word 文档（.docx）始终生成**（Step 3.8 已完成转换），以下为可选的分发目标：

#### 4A. 在线文档平台（用户指定时执行）

用户可能需要将转录文档上传到在线协作平台。根据用户指定的平台选择对应工具：

**钉钉文档示例：**

如用户环境已配置钉钉 CLI（如 `dws`），先用 `build_docx.py --export-md` 从 `_document.json` 生成一份临时 Markdown（上传后即删，非工作中间文件），再上传：

```bash
# 从结构化数据导出临时 Markdown（本地图片静帧无法上传，导出时已省略引用行）
python <skill_dir>/scripts/build_docx.py "<output_dir>/<标题>_document.json" "<output_dir>/<标题>.docx" --export-md "<output_dir>/_upload.md"

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

转录与格式转换完成后，`<标题>.docx` 已生成在 output_dir 中，包含：
- **标题**：文档标题（无冗余装饰）
- **人物静帧**（仅视频输入）：居中显示于文档顶部，280px 宽度；音频输入时无此图
- **📝 内容摘要**：LLM 生成的 3-5 句话概括（Step 3.6 生成）
- **👤 受访人信息**：受访人关键信息表格（Step 3.6 生成）
- **📋 文档信息**：转录工具、说话人识别方法、摘要生成方法、转录日期等元数据
- **💬 采访记录**：带时间码和 `**采访者**` / `**受访人**` 标签的对话内容（如 `**采访者** [05:30]`）

可直接交付给用户，或后续按需上传到任意平台。

#### 4C. 其他平台（按需扩展）

核心交付物为 Step 3.8 生成的 Word 文档 `<标题>.docx`（含摘要、人物信息、对话正文）。用户可根据需要上传到任意平台：多数平台支持直接上传 .docx 文件；若平台仅接受 Markdown（如钉钉 doc create 的 markdown 模式），可在 Step 5 清理前用 `build_docx.py --export-md` 从 `_document.json` 生成临时 `_upload.md` 上传。

### Step 5: 清理临时文件

```bash
rm -f _seg*.mp3 _upload.md *_raw.txt *_transcript.json *_document.json *segments.json transcribe_config.json 输出.mp3
```

保留的文件：
- `<标题>.docx`（最终转录文档，Word 格式，直接生成、无中间 Markdown）
- `人物静帧.jpg`（人物静帧图片，仅视频输入）

### Step 6: 询问交付位置（收尾交互）

所有文档处理（转录、说话人识别、摘要与人物信息、文档生成（.docx）、临时文件清理）**全部完成后**，必须主动询问用户希望将整理好的文档发送到哪里，再执行分发。不要默默结束对话，也不要未经确认就擅自上传到任何外部平台。

**询问话术（口吻自然，不要机械生硬）：**

> 文档已经整理好了，需要我给您发在哪里？我可以总结好之后给您发送。
>
> （提示：本次使用本地转录。若需要更高的识别准确率，可改用云端 Qwen3-ASR-Flash 转录——需配置 DashScope API Key，随时告诉我即可切换。）

**可选交付目标（分发方式详见 Step 4）：**
- **钉钉文档** — 通过 `dws` CLI 创建并上传（Step 4A）
- **飞书文档 / 腾讯文档 / Notion** — 通过对应平台 API/CLI 上传（Step 4C）
- **本地文件** — `<标题>.docx` 已生成在 output_dir，直接告知路径即可交付
- **直接粘贴到对话** — 将整理好的内容直接输出在当前对话中

**执行规则：**
- 用户未指定目标时，不要擅自上传到任何外部平台，保持本地文件待命
- 用户指定目标后，再调用对应平台的 API/CLI 完成分发
- 若用户选择"本地文件"或"直接粘贴"，则无需额外操作，直接交付即可

## 说话人识别说明

**方法演进：**
1. ❌ 启发式方法（关键词+段落长度）：已废弃，完全不可靠，所有对话混在一个段落
2. ✅ **云端模式：LLM 语义分析**：Qwen3-ASR-Flash 转录输出连续文本，LLM 理解对话内容智能切分，准确率 95%+
3. ✅ **本地模式：pyannote.audio 声纹分离 + LLM 角色映射**：pyannote 基于声纹区分说话人，LLM 将 SPEAKER 标签映射为对应的角色（采访者/受访人，或群访中的其他角色）

Qwen3-ASR-Flash 不直接支持说话人分离，fun-asr 虽支持但需 OSS 文件上传（file:// 本地路径不可用）。云端最优方案：Qwen3-ASR-Flash 转录 + LLM 语义分段。本地备选方案：faster-whisper 转录 + pyannote.audio 声纹分离 + LLM 角色映射。

## 错误处理与失败恢复

全流程任一环节失败都不应让用户束手无策。各环节的失败信号与回退动作如下；回退后仍失败则明确告知用户原因与可行路径，不要静默中断。

- **Step 1 预处理（ffmpeg）失败**：文件损坏 / 格式不支持 / 无 ffmpeg。→ 提示用户检查源文件，列出 `ffmpeg -version` 验证；无法处理则终止该文件并说明，不要反复重试
- **Step 2.6 获取时长（ffprobe）失败**：→ 无法判断时长时保守按"长音频"处理（自动切段），并在日志标注"时长未知，已按切段处理"
- **Step 3 本地模型下载/加载失败**：
  - SenseVoice/Paraformer（魔搭社区）失败 → 提示网络/磁盘，给出 `pip install funasr modelscope` + `snapshot_download` 手动命令；可建议改用 Paraformer 或云端
  - faster-whisper / pyannote（HuggingFace）失败 → 脚本已内置镜像站降级；全失败则打印手动下载指南，并提示"可改用 SenseVoice（魔搭直连）或云端 Qwen3-ASR-Flash"
  - 依赖缺失（funasr/faster-whisper/pyannote 未装）→ 直接打印对应 `pip install` 命令后退出
- **Step 3 云端 API 失败/超时/配额耗尽**：
  - 偶发超时 → 自动重试（最多 2 次，指数退避）
  - 持续失败（Key 无效 / 配额用尽 / 无网络）→ 若本地模型可用则**自动降级本地转录**并告知用户；否则明确报错并给出申请/配置 DashScope Key 的指引
- **Step 3.5 LLM 说话人识别异常**：
  - 仅识别出 1 个说话人标签、或轮次数远少于音频时长预期 → 告警"说话人切分可能异常"，建议回看原始文本或改用其他识别方式（本地有 Token 时优先 pyannote 声纹分离）
  - 角色映射明显颠倒（如把长回答标成采访者）→ 在 Step 3.9 预览环节由用户发现并纠正
- **Step 3.8 生成 .docx 依赖缺失**：python-docx 未装 → 打印 `pip install python-docx pillow` 后退出，不破坏已生成的 `_document.json`（用户可稍后重跑生成）
- **Step 4 上传平台失败**（如钉钉 API 报错）→ 保留本地 `.docx`，告知用户上传失败原因，提供本地文件路径作为兜底

> 核心原则：**失败要可见、可恢复、有兜底**。任何环节出错都要给用户一个明确的"下一步"，而不是卡死或静默产出残缺文档。

## 注意事项

- **文档命名规范**：文档标题为 `拍摄时间+人物简介（≤10字）` 格式，如 `26-0509 车辆学院直博生`，详见 Step 2
- **说话人识别必须用 LLM**：启发式方法已被验证不可用，转录完成后必须执行 Step 3.5（云端=语义切分，本地=角色映射）
- **LLM prompt 必须强调逐轮分段**：如果 prompt 只说"切分段落"，LLM 可能将同一说话人的所有内容合并成一大段。prompt 必须明确要求"每轮问答独立成段，不要合并同一说话人的多轮对话"，并用 `**采访者**` / `**受访人**` 标签交替输出
- **摘要与人物信息必须生成**：说话人识别完成后必须执行 Step 3.6，生成内容摘要和受访人人物信息，插入到文档正文最前面（静帧之后、元数据之前），让读者快速了解采访核心内容和受访人背景
- **LLM 调用方式**：如 Agent 自身即是 LLM（Claude Code、Codex 等），可直接在对话中执行 Step 3.5/3.6 的语义分析，无需额外 API 调用；否则使用 Python 调用 Qwen-Plus API
- **转录 API**：使用 `dashscope.MultiModalConversation.call(model="qwen3-asr-flash")`，不要用 `Transcription.call`（后者签名已变更）
- **转录方式选择（默认本地）**：默认使用本地转录（SenseVoice，离线可用、无需 API Key），不强制询问用户。仅当用户主动要求更高准确率或提供 DashScope API Key 时才切换云端 Qwen3-ASR-Flash。faster-whisper 仅作为本地通用备选。流程最后（Step 6）会提示用户"云端转录为更高精度可选方案"
- **输入类型自动识别**：本技能同时支持视频与音频输入。视频才需要「提取静帧 + 转 MP3」；音频直接跳过 MP3 转换（本身即为音频）且不提取静帧，元数据中 `input_type` 标记 video/audio、`frame_path` 为 null 时不输出静帧图
- **切段决策在选方式之后**：是否切段取决于 Step 2.5 选定的转录方式——云端 Qwen3-ASR-Flash 单次上限 5 分钟（超时必须切），本地模型无硬限制（长音频由模型自动切、短音频整段，均不询问用户）。切段统一在 Step 2.6 完成，未切段时 segments 仅含整段一项（offset 为 0）
- **本地声纹分离（支持多说话人）**：使用 pyannote.audio（`pyannote/speaker-diarization-3.1`），需 HuggingFace Token + 接受模型条款。默认说话人范围 1-2 人，群访等多人场景可在 `transcribe_config.json` 设 `max_speakers`（如 5）放宽。无 Token 时可跳过声纹分离，转录后使用 LLM 语义切分说话人（同云端模式，支持 N 人）
- **HuggingFace 模型下载镜像**：仅 faster-whisper 和 pyannote.audio 需要 HuggingFace。SenseVoice/Paraformer 从魔搭社区下载（国内直连）。faster-whisper 脚本内置多镜像站自动降级（hf-mirror.com → HuggingFace 官方），全部失败后打印手动下载指南。pyannote.audio 需 HuggingFace Token
- Windows 路径使用正斜杠 / ，避免中文路径传给 API
- **Windows 下 `bc` 不可用**：数值计算用 Python 替代，不要在 bash 中用 `bc` 做浮点比较
- **bash heredoc 会吃掉 `\s` 转义**：正则表达式需写入 .py 文件执行，不要用 inline heredoc 传正则
- **长文本 LLM 分段**：LLM 单次输入建议不超过 8000 字符，超过时分段处理后拼接
- **生成后自检精简语气词**：文档生成后必须执行 Step 3.7，通读采访记录、适度删除口语语气词/填充词（嗯、啊、那个、就是、然后堆叠等）。原则是「稍微减少一点」——只删明显冗余的，绝不改写句子结构、不替换用词、不改变原意，仅处理正文（不动摘要/人物信息/时间码/说话人标签）
- **收尾必须主动询问交付位置**：所有处理（含临时文件清理）完成后，必须主动问用户"需要我给您发在哪里？"（Step 6），未经确认不得擅自上传到任何外部平台。用户未指定时保持本地文件待命即可
- **最终交付为 Word 文档（.docx），全程无 Markdown 中间文件**：转录脚本直接输出结构化 `<标题>_transcript.json`（含 metadata + `raw_text`），Agent 完成说话人识别 / 摘要生成 / 语气词自检后写入 `<标题>_document.json`，最后由 `scripts/build_docx.py` 直接生成 .docx（依赖 python-docx，建议装 pillow 提升图片兼容）；Step 5 清理时删除所有临时 JSON，仅保留 .docx 交付，全程不生成任何 .md 文件
