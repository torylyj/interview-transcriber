---
name: interview-transcriber
display_name: 音视频转文档
description: |
  音视频转文档全流程处理技能（支持视频与音频输入，也支持「一段音视频拆成多段文件」合并转录）。三档模型选择（Step 2.5）：① 快速 = FunASR Paraformer-large + CAM++（中文高精度、速度最快、离线、无需 API Key）；② 精准 = MOSS-Transcribe-Diarize 0.9B 端到端（转录+说话人+时间戳一次生成，分离最稳、标点自然；⚠️ 首次需联网下载 ~1.8GB 模型 + torch/transformers 推理栈，GPU 版约 2.7GB；16GB 显存实测安全，段长已收紧到 8 分钟）；③ 云端 = Qwen3-ASR-Flash（需 DashScope Key）。开始前检测本机 GPU 配置自动推荐档位，用户三选一、随时可切。流程：检测输入类型（视频/音频，音频跳过转 MP3 且无需静帧）-> 模型按能力自动决定是否切段 -> 按所选档位转录 -> 说话人分离（精准档 MOSS 端到端一次生成并自动归并为采访者/受访者、快速档 Paraformer+CAM++ 在模型内完成且 LLM 语义校正必做、云端 LLM 语义切分，支持多说话人）-> LLM 生成内容摘要与人物信息 -> 直接生成带时间码的 Word 文档（.docx；分发到在线平台时导出临时 Markdown，上传后即删）-> 自检精简语气词 -> 交付前预览确认 -> 可选分发到在线文档平台。
  若用户把一段音视频拆成多个视频/音频文件，需请用户明确告知哪几个文件属于同一段音视频，技能自动合并转录为一篇文档。
  适用于任何支持 bash 命令执行和文件读写的 AI 编码代理（Agent）。全流程处理完毕后主动询问用户交付位置；三档模型（快速/精准/云端）随时可切换。
agent_created: true
---

# 音视频转文档（interview-transcriber）

## 概述

将音视频内容（视频或音频，也可是一段音视频被拆成的多个文件）全流程处理为带说话人识别的转录文档。核心流程始终执行：输入预处理 → 模型选择（Step 2.5：检测本机配置，快速/精准/云端三选一）→ 模型按能力自动决定是否切段 → 按所选档位转录 → 说话人分离与校正（支持多说话人）→ 生成摘要与人物信息 → 直接生成 Word 文档（.docx）→ 自检精简语气词 → 交付前预览确认 → 可选分发。全部完成后主动询问用户交付位置。

**转录方式（三档选择，见 Step 2.5）：** 快速 = FunASR Paraformer-large + CAM++（魔搭直连、无需 API Key、离线可用、中文高精度）；精准 = MOSS-Transcribe-Diarize 0.9B 端到端（说话人分离最稳）；云端 = Qwen3-ASR-Flash（需 DashScope API Key）。开始前先按本机 GPU 配置推荐，再由用户确认档位。详见 references/model_download.md。

**多段音视频（重要）：** 若用户把一段音视频拆成了多个视频/音频文件，必须请用户**明确告知哪几个文件属于同一段音视频**，技能会合并转录为一篇文档。详见文末「多段音视频输入说明」。

## Agent 适配说明

本技能以 Markdown 指令编写，任何支持 bash / 文件读写 / Python 的 AI 编码代理均可使用。

| Agent | 加载方式 |
|-------|---------|
| **WorkBuddy** | 放在 `~/.workbuddy/skills/`，对话中自动触发或 `@skill:interview-transcriber` |
| **其他 Agent / Codex** | 作为 `AGENTS.md` 注入，核心依赖 ffmpeg + Python + 可选 DashScope |

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

**1b. 视频输入 → 只提静帧，免转 MP3（默认 MOSS 路径）**
- 静帧：用 `scripts/extract_frame.py` 抽取**最清晰的一帧**（视频【五等分】各抽 1 帧、按清晰度比选，输入定位不软解整段视频），输出 800px 宽：
  ```
  python <skill_dir>/scripts/extract_frame.py "输入.mp4" "人物静帧.jpg"
  ```
- **音频无需预转**：默认 MOSS 路径下 config 的 `segments` 直接写原始视频路径，`transcribe_local.py` 内部自动提取 16k 单声道 WAV（pcm，无损、比 MP3 编码快）喂给模型、用完即删——用户无感。
- `frame_path="人物静帧.jpg"`，`segments=[{"file":"<原始视频绝对路径>","offset":0}]`
- 仅快速档（Paraformer/SenseVoice）或云端档才需要预转 MP3：`ffmpeg -i "输入.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y`

**1c. 音频输入 → 原样直入，无静帧**
- 默认 MOSS 路径：音频文件直接写进 `segments`，无需重采样（模型内部处理）。
- 回退/云端路径才转 MP3：`ffmpeg -i "输入.m4a" -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y`
- `frame_path=null`

**1d. 多段输入合并**：见文末「多段音视频输入说明」（合并命令见 references/segment_commands.md）。

> 切段不在 Step 1 进行：由 Step 2.6 按模型能力自动决策（不询问用户）。

### Step 2: 确定文档标题

`拍摄时间+人物简介（≤10字）`。拍摄时间用 fallback 链：① 文件夹名 `YY-MMDD` → ② 文件名 `YY-MMDD` → ③ 文件元数据时间 → ④ 标记「未知日期」。人物简介由 Agent 提炼（学校/专业/年级/家乡等，≤10字）。示例：`26-0509 车辆学院直博生`。

### Step 2.5: 模型选择（快速 / 精准 / 云端，按本机配置推荐）

**三档定义：**

| 档位 | 引擎 | 模型大小 | config 写法 | 特点 |
|------|------|------|------|------|
| **① 快速** | FunASR Paraformer-large + CAM++ | Paraformer-large ~900MB + CAM++ ~30MB（首次联网下载，之后离线） | `mode:"local"`, `model:"paraformer"` | 中文高精度、速度最快、离线可用、无需 Key；说话人走声纹聚类，**必须接 LLM 语义校正（3.5B）**；标点/分段较弱，**推荐接 LLM 文本精修（3.56）** |
| **② 精准** | MOSS-Transcribe-Diarize 0.9B 端到端 | 0.9B 模型 ~1.8GB + torch GPU 推理栈 ~2.7GB（首次联网下载） | `mode:"local"`, `model:"moss"` | 转录+说话人+时间戳一次生成，分离最稳、标点最自然；速度慢（约 1.5–2 倍实时），显存要求高（≥16GB） |
| **③ 云端** | Qwen3-ASR-Flash | **无需本地模型** | `mode:"cloud"` + api_key | 不吃本机算力、长音频 4 分钟/段；需 DashScope Key，说话人走 LLM 语义切分 |

> 文档「文档信息」中的转录工具一行会自动带上档位与模型大小标注（`build_docx.py` 的 `_tool_with_size`）。

**推荐逻辑（先检测，再推荐）：**

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
```

- **显存 ≥ 16GB**（如 RTX 4070 Ti SUPER / 4080 / 3090）→ 推荐 **精准（MOSS）**：8 分钟/段实测峰值 ~10.3GB，安全
- **显存 8–12GB** → 推荐 **快速（FunASR，GPU 加速）**：MOSS 在小显存 OOM 风险高，不建议
- **无 NVIDIA GPU** → 有 DashScope Key 推荐 **云端**；没有则 **快速（CPU 版）**（慢但可用）
- **长音频（>30 分钟）且追时效** → 即使显存够也提示：精准档约 1.5–2 倍实时，可改快速档

**交互方式：** 用一句话告知检测结果 + 推荐档位及理由，然后请用户三选一（WorkBuddy 用 AskUserQuestion，其他 Agent 用文字提问）；用户回答"你定/直接来"即按推荐档执行，全程可随时说"换快速/换精准/换云端"切换。选本地档时按下方提示交代首次模型下载耗时；选云端档则确认 api_key 已就绪。

> ⚠️ **首次转录提醒（必须执行）**：真正运行转录（Step 3）之前，先用一句话告知用户——「本次为首次转录，将联网下载本地模型（快速档 FunASR Paraformer-large ~900MB + CAM++；精准档 MOSS 0.9B ~1.8GB + torch 推理栈 GPU 版约 2.7GB），耗时数分钟，请耐心等待；下载完成后自动缓存，之后转录秒级启动」。脚本 `transcribe_local.py` 启动时也会打印同样提示，避免用户面对数分钟静默误以为卡死。

配置 `transcribe_config.json`（推荐直接用 `python <skill_dir>/scripts/prepare.py <输入> --model <paraformer|moss>` 一键生成：自动识别类型、抽静帧、按所选模型能力决定切段、写入 config；**快速档视频转 16k 音频（MP3/WAV）**；**精准档（moss）免转 MP3**，模型内部自提 16k WAV）：

- 云端（`mode: "cloud"`）：需 `api_key`。云端无原生说话人分离，由 LLM 语义切分，群访等多说话人同样支持。
- 本地（`mode: "local"`）：`model` = `paraformer`（快速档，脚本默认）/ `moss`（精准档）/ `sensevoice`（极速轻量备选）。**快速档说话人由 CAM++ 声纹聚类（免 HF Token），但街头采访短应答/抢话下偶尔贴反——务必接 LLM 语义校正（Step 3.5B）**。
- 配置模板（cloud/local）见 references/dashscope_setup.md；模型下载/镜像/HF Token 说明见 references/model_download.md。

### Step 2.6: 切段决策（模型自动，不询问）

用 ffprobe 获取音频时长，按所选模型能力自动决策（详见 references/segment_commands.md）：
- **快速档（FunASR Paraformer）**：>20 分钟建议切（4 分钟/段）；短音频整段。
- **精准档（MOSS 端到端）**：≤15 分钟整段直入；>15 分钟按 **8 分钟/段**切（`prepare.py` 已内置 `MOSS_SEG_SEC=480`，16GB 显存实测安全值；旧版 12 分钟段曾 CUDA 死锁——GPU 100% 但永不完成）。MOSS 速度约 1.5–2 倍实时，长音频优先考虑快速档。
- **云端 Qwen3-ASR-Flash**：>5 分钟必切（4 分钟/段，留余量）；≤5 分钟整段。
- `prepare.py` 已内置以上决策。结果写入 config 的 `segments`（切段：offset 递增；不切：`[{"file":"<原始文件>","offset":0}]`）。

### Step 3: 运行转录

> `<skill_dir>` 为本技能目录。

**3A. 云端（可选方式）**：`python <skill_dir>/scripts/transcribe_qwen.py --config transcribe_config.json` — 逐段调用 qwen3-asr-flash，生成 `<标题>_transcript.json`（含 metadata + `raw_text`，无 Markdown）。

**3B. 本地（快速/精准档）**：`python <skill_dir>/scripts/transcribe_local.py --config transcribe_config.json --model <paraformer|moss>`（`--model` 缺省即 `paraformer` 快速档，与 Step 2.5 所选档位一致）。**精准档（moss）**：MOSS-Transcribe-Diarize 0.9B 端到端，说话人由模型分离并自动归并为 采访者/受访者（`_transcript.json` 已带 `SPEAKER_XX`）；跑完**检查说话人分布**，异常（如单一说话人占 95%+、问答粘连成超长轮）→ 回退快速档 `--model paraformer` 重跑。**快速档（paraformer）**：CAM++ 在模型内声纹聚类分人。两者随后都接 Step 3.5/3.5B。依赖安装见 references/model_download.md。

### Step 3.5: 说话人识别（本地已模型内完成，但需 LLM 校正）

- **本地快速档（FunASR Paraformer + CAM++）**：说话人由 CAM++ 在模型内按声纹聚类，`_transcript.json` 每段带 `SPEAKER_XX`；脚本按「提问密度 + 平均轮长」归并为 **采访者/受访者** 两角（两人对话默认即此命名）。**但纯声纹聚类在街头采访（短应答、抢话、噪声）下偶尔会把两人贴反或同人抖成多号**，所以快速档必须接 LLM 语义校正（见 3.5B），不能只靠聚类。**精准档（MOSS）**分离最稳，分布健康时角色通常已正确，仅做轻量复核。
- **云端**：Qwen3-ASR-Flash 无原生说话人分离，仍需 LLM 语义切分。方法 A（Agent 自身 LLM）直接按 references/prompts.md 的 prompt 输出；方法 B（外部 API）用 `python <skill_dir>/scripts/call_qwen.py --prompt-file speaker_prompt.txt`。

#### Step 3.5B: 本地说话人 LLM 校正（本地档必做，保证质量）

CAM++ 只给「谁在何时说」，不保证角色正确。用 `correct_speakers.py` 调 Qwen-Plus 按问答语义校正角色、并一并产出 摘要/人物信息，生成标准 `corrections.json`：

```bash
python <skill_dir>/scripts/correct_speakers.py <标题>_transcript.json \
    --api-key $DASHSCOPE_API_KEY
# 输出 corrections.json（speaker_roles / summary / summary_sections / person_info）
python <skill_dir>/scripts/build_document.py <标题>_transcript.json <标题>_document.json \
    --apply corrections.json
```

> 说明：本地说话人走 CAM++ 是按声纹聚类（模型内、快），再经 3.5B 的 LLM 语义校正兜底——比旧版「纯逐句启发式」或「纯 LLM 语义切分」更稳，直接给出「谁在何时说 + 角色是否正确」。

#### Step 3.5C: 多说话人语义重切（论坛式会议快速档专用，2026-09-07 实测）

**触发条件（满足其一就考虑）：** ① 用户说明这是大会/论坛/圆桌（非双人采访）；② 快速档转录后抽查发现主持人串场轮次（"接下来有请…""感谢分享"）或嘉宾被并进同一说话人；③ 说话人分布严重失衡且轮次内出现多人对话痕迹。CAM++ 的 `preset_spk_num=2` 是双人采访假设，**论坛式 >2 人场景必然把多人并成 1 类**——此时 3.5B 的角色校正救不了"人数"本身，必须语义重切。

**做法（不重转音频）：** 用 `resegment_speakers.py` 对已有 transcript.json 的句子做 LLM 语义级说话人重分段：

```bash
python <skill_dir>/scripts/resegment_speakers.py "<输出目录>/<标题>_transcript.json" \
    --api-key $DASHSCOPE_API_KEY
# 输出 <标题>_transcript.sem.json（仅改 speaker 字段）+ .meta.json（说话人描述+分布）
```

- 内置实测修复：**编号白名单**（LLM 批间自造编号→非法编号回退上一说话人）、上限 20 人、批间 12 句重叠上下文 + 全局编号表保证跨批一致。
- 50 分钟音频约 11 批（~5 分钟）；输出 meta 里 LLM 给出的说话人描述很准（含"安叔""安娜"等称呼线索），据此写 `corrections.json` 的 `speaker_roles`（说话人1/2/3… → 主持人/嘉宾·XX/观众提问·XX）再 `build_document.py --apply`。
- **双人采访不要用本步**（CAM++ + 3.5B 已足够且更省）；精准档 MOSS 若也遇到 >2 人，同样适用。

### WeSpeaker 说话人重贴标（CAM++ 可选替换，2026-07-31 实测：等价、非更优）

WeSpeaker 提供 `load_model('chinese')`（CNCeleb ResNet34，256 维）作为更强的说话人嵌入模型，可替换 CAM++ 的句子级贴标。**实测结论：在真实双人采访上与 CAM++ 分区基本等价**（翻转标号后两方法一致率 92.9%，真正差异仅 7.1% 且全在转场亚秒碎片），质量未明显更优，但需多跑一个模型、且导入更脆弱。故**默认仍用 CAM++**；仅当某片段 CAM++ 明显贴反人时，用下方工具对已有 transcript 做 WeSpeaker 重贴标（不改动主转录流程）。

```bash
# 对任意已转录 transcript.json（含句子 start/end）+ 对应音频，重贴标说话人
python <skill_dir>/scripts/speaker_relabel_wespeaker.py \
  --transcript <标题>_transcript.json --audio <对应音频.wav/mp4> \
  --output <标题>_wespeaker.json --num-speakers 2
# 对照 CAM++ vs WeSpeaker（截取片段，用 LLM 角色作参照）
python <skill_dir>/scripts/benchmark_wespeaker.py --source <音频> --start 600 --dur 600 \
  --work-dir _bench --api-key $DASHSCOPE_API_KEY
```

⚠️ **环境坑（wespeaker 在 torch>=2.x 导入会崩，已修）**：① `wespeaker/frontend/__init__.py` 无条件 import s3prl/w2vbert，而 s3prl 引用已删除的 `torchaudio.sox_effects`/`set_audio_backend` → 崩溃；已在 `transcribe2` venv 内改成 try/except 容错（s3prl/w2vbert 置 None，只用 tfmel 前端）。② 需 `pip install onnxruntime`（diar 子模块 import）。③ `extract_embedding` 内 `torchaudio.load` 走 torchcodec 后端（未装）→ 脚本内已 shim 为 soundfile 绕过。wespeaker 装在 `transcribe2` venv。

### Step 3.55: 同音字校对（必做，提升 .docx 稳定性）

中文 ASR 模型按读音识别（Paraformer / SenseVoice / Qwen3-ASR 都会），常把同音字搞混（在↔再、做↔作、的↔得↔地、了↔啦↔咯、记↔纪↔计 等）。LLM 按上下文识别并批量替换，对最终 `.docx` 的可读性影响最大。

**两种调用方式**（与 Step 3.5/3.6 一致）：
- **方式 A（推荐）**：Agent 自身即 LLM，按 references/prompts.md § Step 3.55 的 prompt 执行；把返回 JSON 保存为 `corrections.json`（可与 Step 3.6 的 summary/summary_sections/person_info 合并），再用脚本应用。
- **方式 B**：`python <skill_dir>/scripts/correct_homophones.py <transcript.json> --call-qwen --model qwen-plus` —— 自动调 qwen-plus 生成并应用 corrections，产出 `<标题>_transcript.corrected.json`。

**应用方式**（二选一）：
1. **独立落盘**（推荐）：产出 `<标题>_transcript.corrected.json`；`build_document.py` 会**自动检测并优先消费**它（仅替换 text，不动 speaker / start / end / metadata）。
   ```bash
   python <skill_dir>/scripts/correct_homophones.py "<output_dir>/<标题>_transcript.json" \
       --apply-corrections corrections.json
   # 产出 <标题>_transcript.corrected.json
   ```
2. **合并到 `--apply`**：把 `homophone_corrections` 数组加进 `corrections.json`，与 `speaker_roles` / `summary` / `summary_sections` / `person_info` 一起作为 `--apply` 入参；`build_document.py --apply` 会内联应用同音字校对（无需写 corrected.json）。

**重要边界**：
- 同音字校对只改**字**，不改标点 / 段结构 / 说话人 / 时间码；
- 短语气词（啊/嗯/哦）的误识别通常不是同音字错误（是删除冗余），应放到 Step 3.7 处理；
- 数字/人名/专名错误 LLM 可能误判（如「林黛玉」不应改成「林戴玉」），必须人工复核 corrections 后再 --apply。

### Step 3.56: 文本精修——标点修复 + 段落重排（快速档强烈推荐）

快速档（Paraformer + ct-punc）的标点常错位（如「因。为」）或缺标点，长独白还会被按 ~160 字机械切段导致胡乱换行。用 `refine_paragraphs.py` 让 LLM 对 document.json 逐轮做：①标点恢复/归位 ②按语义重排自然段（续段时间码按字数占比插值）③轻度精简语气词；单轮长度校验失败自动回退原文，不丢内容。

```bash
python <skill_dir>/scripts/refine_paragraphs.py "<输出目录>/<标题>_document.json" \
    --api-key $DASHSCOPE_API_KEY --in-place
# --in-place 直接覆盖（自动备份 .bak）；不加则输出 <标题>_document.refined.json
```

- **适用**：快速档必做（效果提升最大）；精准档（MOSS）标点自然、分段合理，通常可跳过；云端档推荐。
- **时机**：build_document.py 产出 document.json 之后、build_docx.py 之前（3.7 语气词精简已内置其中，无需重复做）。
- **docx 格式约定**：每轮「角色（时间）」一行 + 内容另起一行；长独白续段也是时间码一行 + 内容另起一行（build_docx.py 已实现，勿改回同行拼接）。
- ⚠️ 50 分钟音频约 9 批 LLM 调用（~10 分钟），后台跑并轮询日志。

### Step 3.6: 生成摘要与人物信息（必须执行！）

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
直接渲染：标题、居中静帧（仅视频、`frame_path` 非 null）、**内容摘要**（含总结性摘要 + 分板块 H2 子标题）、人物信息（无则省略／多人多表）、文档信息（精简为 5 行：源文件 / 输入类型 / 转录工具 / 说话人识别 / 转录日期，**不再写时间码精度、摘要与人物信息**）、对话记录（**两行制**：每轮「角色（时间）」一行、内容另起一行，轮间空一行；角色默认 采访者/受访者（两人对话）或 说话人1/2…，无 emoji/加粗/冒号）。音频输入跳过静帧。依赖：`pip install python-docx pillow`。

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
rm -f _seg*.mp3 _seg*.wav _audio_*.wav 输出.wav _upload.md *_raw.txt *_transcript.json *_transcript.partial.json *segments.json transcribe_config.json 输出.mp3
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
- ✅ 本地快速档（FunASR Paraformer + CAM++）：Paraformer 转录 + CAM++ 说话人分离（按声纹自动聚类，免 HF Token），两人对话按「提问密度+轮长」归并为 采访者/受访者；**CAM++ 偶发贴反，必须接 LLM 语义校正（Step 3.5B 的 correct_speakers.py）兜底**。
- ✅ 本地精准档（MOSS 端到端）：转录+说话人+时间戳一次生成，分离最稳；分布异常（贴反/粘连）时回退快速档重跑。
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
- **本地快速档说话人由 CAM++ 模型内分离，再经 LLM 语义校正（Step 3.5B correct_speakers.py）兜底**；精准档 MOSS 端到端（分离最稳但慢、显存要求高）；仅云端 Qwen3-ASR-Flash 无原生分离、仍走 LLM 语义切分（启发式已废弃）。
- **DashScope 调用统一**：音频转录用 `MultiModalConversation.call(model="qwen3-asr-flash")`；文本任务（说话人/摘要/同音字）用 `scripts/call_qwen.py`（`Generation.call`, qwen-plus）。务必 `pip install -U dashscope`，勿用已变更的 `Transcription.call`（版本兼容见 references/dashscope_setup.md）
- **Step 2.5 三档模型选择**（快速 FunASR / 精准 MOSS / 云端 Qwen3-ASR）：先检测本机配置给出推荐，用户三选一；未表态按推荐档执行，随时可切
- **GPU 加速（本地两档均受益）**：`setup_env.py` 检测到 NVIDIA GPU 会自动装 CUDA 版 torch，本地 Paraformer-large/SenseVoice/MOSS 推理走 GPU（RTX 40 系约数倍提速）；无 GPU 则装 CPU 版。档位选择见 Step 2.5，不强制云端
- **输入类型自动识别**：视频才提取静帧；快速档视频**需转 16k 音频**（MP3/WAV，prepare.py 自动完成）；精准档（moss）视频免转 MP3（transcribe_local.py 内部自动提 16k WAV、用完即删）；音频 `frame_path=null` 不输出静帧
- **切段决策在 Step 2.5 选档之后、模型自动**：云端 >5 分钟必切，快速档（FunASR）>20 分钟建议切，精准档（MOSS）≤15 分钟整段、超则 8 分钟/段防 OOM，均不询问
- **本地说话人分离**：快速档由 CAM++ 模型内聚类 + LLM 语义校正（Step 3.5B）兜底；精准档（MOSS）端到端一次生成、分布异常回退快速档；云端 Qwen3-ASR-Flash 无原生分离、走 LLM 语义切分；支持多说话人（群访无需额外配置）；无需 HF Token、无需 pyannote
- **全程无需 HuggingFace**：本地说话人走 CAM++（模型内、魔搭直连），模型仅 Paraformer-large/SenseVoice；已移出 faster-whisper / pyannote
- Windows 路径用正斜杠（`C:/...` 或相对路径，勿用 Git Bash 的 `/c/...` 写法，脚本已自动兼容转换）；`bc` 不可用（用 Python 算）；bash heredoc 不吃 `\s`（正则写 .py 文件）
- **长文本 LLM 分段**：单次输入 ≤ 8000 字符，超长分段后合并
- **时间码精度**：本地 Paraformer-VAD 为真实句级时间码；SenseVoice 段内为插值估算（段落边界精确）；云端段内为估算值（4 分钟粒度）；文档已如实标注，勿当精确时间
- **收尾必须主动询问交付位置**（Step 6），未经确认不上传外部平台
- **最终交付 .docx**：转录脚本输出 `_transcript.json`，Agent 写 `_document.json`，`build_docx.py` 直接生成 .docx（分发到在线平台时导出临时 Markdown，上传后即删）
