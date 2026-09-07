# 🎬 音视频转文档

> 音视频一键转文档技能 · 自动把视频/音频变成**带说话人识别、内容摘要与人物信息**的结构化文档

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org)
[![中文转录](https://img.shields.io/badge/中文转录-Qwen3--ASR--Flash-rightgreen)](https://help.aliyun.com/zh/model-studio/)
[![本地模型](https://img.shields.io/badge/本地模型-FunASR%20%7C%20MOSS%20%7C%20SenseVoice-orange)](https://modelscope.cn)
[![Agents](https://img.shields.io/badge/Agent-WorkBuddy%20%7C%20Codex-purple)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-blue)](#license)

给 Agent 一段音视频，它会自动跑完 **预处理 → 转录 → 说话人识别 → 摘要与人物信息 → 输出文档**，最后还会问你「要把文档发到哪里」。开始转录前 Agent 会检测你的显卡配置，从**快速 / 精准 / 云端**三档模型里推荐一个，你确认或改选即可。

## 📑 目录

- [功能概览](#功能概览)
- [安装](#安装)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [输出文档结构](#输出文档结构)
- [性能预估](#性能预估)
- [最低硬件配置](#最低硬件配置)
- [注意事项](#注意事项)
- [更新日志](#更新日志)

---

## ✨ 功能概览

| 功能 | 说明 |
|------|------|
| 🎞️ 输入预处理 | 视频：提取**最清晰静帧** + 转 MP3；音频：直接用作音频（跳过转 MP3、无静帧） |
| 🧩 多段合并 | 一段音视频拆成多个文件？明确告知后自动合并转录为一篇文档 |
| ⚡ 快速转录（默认档） | **SenseVoice-Small q8 量化**（FunASR GGUF/llama.cpp 运行时：单 exe ~5MB + 模型 254MB，纯 CPU ~33 倍实时，**零 Python/torch 依赖**，自带标点） |
| 🎯 精准转录（推荐档之一） | MOSS-Transcribe-Diarize 0.9B 端到端：转录+说话人+时间戳一次生成，说话人分离最稳、标点自然（建议 ≥16GB 显存） |
| ☁️ 云端转录 | Qwen3-ASR-Flash（可选方式，需 DashScope API Key，不吃本机算力） |
| ⏱️ 对话时间码 | 每轮对话标注 `[MM:SS]`，精准定位视频位置 |
| 🗣️ 说话人识别 | 快速档：GGUF 运行时无内分离 → **LLM 语义重切**（`resegment_speakers.py`，2 人~20 人自适应）；精准档：MOSS 端到端一次生成；自动区分说话人（支持多说话人）；统一中性命名为 说话人1/2/3……（不做采访者/受访人角色判定） |
| 📝 内容摘要 | LLM 生成 3–5 句话概括音视频核心内容 |
| 👤 人物信息 | LLM 提取人物信息；**未提及则整段省略**，多人时每人一个独立表格 |
| 📤 多平台分发 | 本地 Word(.docx) / 钉钉文档 / 飞书 / Notion / 其他平台 |

---

## 📦 安装

把这个仓库链接直接发给你的 Agent，让它自动下载安装即可：

```
https://github.com/torylyj/interview-transcriber
```

安装完成后，在 Agent 对话中提到「转文档」或「转音视频」就会自动触发。

---

## 🚀 快速开始

### 前置条件

- **ffmpeg** — 视频处理。Windows 缺失时 Agent 会自动从**国内镜像**下载静态构建；也可手动用 choco / winget / brew 安装。
- **Python 3.10+** — 运行转录脚本。
- **DashScope API Key** — 仅**云端转录**需要（[获取地址](https://bailian.console.aliyun.com/?tab=model#/api-key)）；本地转录完全不需要。
- **无需 HuggingFace Token** — 说话人识别全部模型内（MOSS）或 LLM 语义重切（快速档/云端）完成；已移出 faster-whisper / pyannote。

> 💡 **安装是自动的**：把本技能交给 Agent 后，首次使用它会自动通过**国内镜像**装好依赖与 ffmpeg（如需手动触发：`python scripts/setup_env.py`）。你通常不需要手动装任何东西。

---

## 📖 使用说明

使用非常简单，**只需要告诉 Agent 你的视频或音频地址**，剩下的全部自动完成。

### 基本用法

```
# 视频
帮我转录这个采访视频：D:/videos/interview_001.mp4

# 音频（无需视频转 MP3，也不会提取静帧）
帮我转录这段采访录音：D:/audios/interview_001.m4a
```

Agent 收到后会先检测你的显卡配置（nvidia-smi），**推荐「快速 / 精准 / 云端」三档之一**：显存 ≥16GB 推荐精准（MOSS 分离最稳）、其余一律先推快速（SenseVoice q8 纯 CPU 任何机器都能跑）、无 NVIDIA 显卡且有 Key 时推荐云端。你确认后它自动执行完整流程，全程可随时说「换快速/换精准/换云端」切换。

- 如果想用**云端转录**，随时告诉 Agent「用云端转录」（需 DashScope API Key），它会切换为 Qwen3-ASR-Flash。
- 如果**一个采访被拆成了多段视频/音频**，只需在开头说明「这 N 个文件是同一段采访」，Agent 会自动合并转录成一篇文档。

### 常见用法示例

| 场景 | 示例指令 |
|------|---------|
| 转录并保存到本地 | `帮我转录 D:/video.mp4，保存到桌面` |
| 转录并上传钉钉文档 | `帮我转录这个视频并上传到钉钉文档：D:/video.mp4` |
| 转录音频录音 | `帮我转录这段录音：D:/audios/interview.m4a` |
| 多段合并采访 | `这段采访我分了 3 段：a.mp4 b.mp4 c.mp4，它们是同一段采访，帮我合并转录` |
| 转录多个视频 | `帮我批量转录 D:/videos/ 目录下的所有视频` |
| 只要转录文本 | `帮我转录 D:/video.mp4，不需要摘要和人物信息` |

### 首次使用准备（仅云端需要）

**云端转录**需要配置 DashScope API Key：

```bash
# 获取地址：https://bailian.console.aliyun.com/?tab=model#/api-key
export DASHSCOPE_API_KEY="sk-your-key-here"
```

> 💡 **提示**：三档模型按本机配置推荐——快速（SenseVoice q8 GGUF，~260MB 零依赖、离线、纯 CPU）、精准（MOSS，分离最稳，建议 16GB 显存）、云端（Qwen3-ASR-Flash，需 DashScope API Key）。Agent 会先给出推荐，你三选一即可。

---

## 📄 输出文档结构

> 以下为文档内容结构；最终以 **Word 文档（.docx）** 形式交付，由 `scripts/build_docx.py` 直接读取结构化 JSON 生成（分发到在线平台时导出临时 Markdown，上传后即删）。

1. **人物静帧**（仅视频输入）— 视频中人物画面截图（居中显示）；音频输入时无此行
2. **内容摘要** — 3–5 句话概括音视频核心内容
3. **人物信息**（可选：短视频未提个人信息则整段省略；多位人物各用一个表格）— 学校 / 专业 / 年级 / 家乡 / 关键经历 / 核心观点
4. **对话记录** — 带说话人标签和时间码的逐句对话

---

## ⏱️ 性能预估

以一段 **20 分钟音视频** 为例（本机实测环境：NVIDIA RTX 4070 Ti SUPER + 模型已缓存）：

| 环节 | 本地快速档（SenseVoice q8，CPU） | 云端模式（Qwen3-ASR-Flash） |
|------|------|------|
| 视频提取音频（ffmpeg） | 20–40 秒 | 20–40 秒 |
| 模型加载（每次新进程） | 10–30 秒 | — |
| ASR 转录 | **<1 分钟**（纯 CPU ~33 倍实时，无需 GPU） | **2–4 分钟**（分 5 段上传+服务端） |
| 说话人命名+摘要+自检（LLM/轻量） | 1–3 分钟 | 1–3 分钟 |
| 抽最清晰静帧 | 10–20 秒 | 10–20 秒 |
| 生成 .docx | <10 秒 | <10 秒 |
| **本机首次** | **≈ 4–8 分钟** | **≈ 4–8 分钟** |
| **本机后续** | **≈ 4–8 分钟** | **≈ 4–8 分钟** |

> 🎯 **精准档（MOSS）速度**：端到端自回归，约 1.5–2 倍实时（20 分钟音频约 30–40 分钟），换取最稳的说话人分离与标点；追时效请用快速档或云端。

- **本机「首次≈后续」**：因为模型已缓存在本地，首次不再有下载开销。技能里的「首次转录会下载模型」提醒只对**全新机器第一次跑**才生效。
- **全新机器首次**（换电脑）：本地模式额外加 ①快速档免 pip（零 Python 依赖）/精准档 pip 装依赖 ~1–2 分钟（国内镜像）+ ②模型下载（快速档 GGUF 运行时+模型仅 ~260MB，数秒到一分钟；精准档 MOSS ~1.8GB + torch 推理栈，GPU 版约 2.7GB，魔搭国内直连），即首次快速档 **3–6 分钟**、精准档 **6–15 分钟**；云端模式永远不需要下载模型。
- **本地与云端耗时相当**（都约 4–8 分钟）；本地完全离线、无需 Key，云端需联网与 Key，两种方式都能满足常规转录需求。

---

## 💻 最低硬件配置

本地转录对硬件要求不高（快速档 SenseVoice q8 GGUF 仅需运行时 5MB + 模型 254MB，**纯 CPU 零 Python 依赖**；旧 Paraformer 引擎另需 funasr/torch 栈 + ~800MB 模型）；**精准档（MOSS）另需 ≥16GB 显存**：

### 纯 CPU 模式（无显卡也行）

| 项 | 最低要求 | 说明 |
|----|---------|------|
| CPU | 任意 x86-64 双核，2.0GHz+ | 近 10 年内的电脑基本满足 |
| 内存 | 8GB（建议 16GB） | Paraformer-large ~0.8GB + torch 推理峰值 4–6GB |
| 硬盘 | 10GB 可用 | 环境 ~1.5GB + 模型 0.5–1GB + 系统/临时 |
| 显卡 | 不需要 | 完全用 CPU 跑 |
| 系统 | Windows 10/11、Linux、macOS | 脚本用正斜杠，跨平台 |
| **20 分钟视频耗时** | **约 20–60 分钟** | CPU 约 0.3–1x 实时 |

### 带 NVIDIA 显卡（GPU 加速）

| 项 | 最低要求 | 说明 |
|----|---------|------|
| GPU | NVIDIA 显卡，≥4GB 显存，支持 CUDA | 入门级 GTX 1650 4GB / RTX 3050 4GB 即可 |
| 显存占用 | 快速档 GGUF **无需 GPU**；旧 Paraformer 推理约 3–4GB | 4GB 显存绰绰有余 |
| 精准档（MOSS）要求 | **建议 ≥16GB 显存** | 8 分钟/段实测峰值 ~10.3GB；8–12GB 显存请用快速档 |
| 驱动 | 支持 CUDA 12.x（仅精准档/旧引擎需要） | 需对应 NVIDIA 驱动版本 |
| **20 分钟视频耗时** | **约 1–2 分钟**（快速档纯 CPU 即此速度） | 本机 RTX 4070 Ti SUPER 16GB 即此档（精准档 MOSS 约 30–40 分钟） |

> ⚠️ **硬性约束：**
> 1. 必须是 **NVIDIA 显卡** 才能用已装的 CUDA 版 torch；AMD / Intel 核显无法用 CUDA，只能退回 CPU。
> 2. **本地说话人分离**：快速档（GGUF）**无模型内分离** → 必接 Step 3.5C LLM 语义重切；精准档（MOSS）端到端一次生成；旧 Paraformer 引擎由 CAM++ 声纹聚类给出每句说话人 id，再经 LLM 语义校正兜底；仅云端 Qwen3-ASR-Flash 无原生分离、仍走 LLM 语义切分。
> 3. **ffmpeg 必需**（视频抽静帧、提取音频），独立下载项，不算在 Python 环境里。
> 4. **首次需联网**：下载模型（快速档 GGUF 运行时+模型仅 ~260MB；精准档 MOSS ~1.8GB + torch 栈，魔搭国内直连）+ pip 依赖（仅精准档/旧引擎）；之后可完全离线跑 ASR。

---

## ⚠️ 注意事项

- **文档命名规范**：`拍摄时间+人物简介`，如 `26-0509 车辆学院直博生`（人物简介 ≤10 字）。
- **多段音视频合并**：必须**明确告知哪几个文件属于同一段音视频**，Agent 才会合并转录为一篇文档；未说明则每个文件各成一篇。
- **智能静帧**：由 `scripts/extract_frame.py` 将视频**五等分、各抽 1 帧**并按清晰度比选最清晰的一张（输入定位，不软解整段视频，避免黑屏/字幕遮挡帧）。
- **三档模型选择**：快速（SenseVoice q8 GGUF）/ 精准（MOSS）/ 云端（Qwen3-ASR-Flash）。Agent 先检测显卡配置推荐一档，你三选一；未表态则按推荐档执行，随时可切。
- **时间码精度**：快速档 GGUF 为 VAD 段级真实时间码（段内切句为插值估算，段落边界精确）；精准档 MOSS / 旧 Paraformer 为真实句级时间码；云端段内为估算值（4 分钟粒度），文档中已标注，请勿当作精确时间。
- **Windows 路径**：使用正斜杠 `/`，避免中文路径传给 API。
- **长文本处理**：LLM 单次输入建议不超过 8000 字符，超长需分段。
- **在线文档上传**：部分平台 API 限制内容长度，超长文档需分段上传。

---

## 📝 更新日志

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.13.2 | 2026-09-07 | **快速档多镜像下载 + CUDA GPU 加速实测**：① 下载渠道扩到多镜像——GGUF 模型新增**魔搭直连**（FunAudioLLM/SenseVoiceSmall-GGUF、fsmn-vad-GGUF，实测 ~4MB/s 国内可用，首选）+ hf-mirror（标注 LFS xet 重定向不稳、仅备选）；运行时 GitHub 直连 + ghfast.top / gh-proxy.com / gh.llkk.cc 社区加速前缀；`transcribe_gguf.py` 缺失提示同步列出全部镜像。② **GPU 加速验证**：v0.2.6 提供 `funasr-llamacpp-windows-x64-cuda.zip`（412MB，内置 cuBLAS CUDA 13 DLL，免装 Toolkit；SHA-256 已核验）+ Blackwell sm_120（RTX 50 系）+ Vulkan（AMD/Intel）；RTX 4070 Ti SUPER 实测 199s 音频推理 7.37s→3.59s（**2.05×**）、端到端 8.0s→5.3s，输出与 CPU 仅 3 处 1–2 字微差（等价）；用法 `--backend cuda --runtime-dir runtime-cuda`。③ model_download.md 重写快速档章节（镜像排序表 + GPU 实测数据 + SHA-256） |
| v1.13.1 | 2026-09-07 | **多视角一致性审查修复（v1.13.0 遗留）**：① SKILL.md「说话人识别说明」「注意事项」与 README「性能/硬件/首次下载」共 15+ 处仍写「快速档 = Paraformer+CAM++」的 v1.12 旧文案，全部对齐 v1.13.0（快速档 = SenseVoice q8 GGUF 无内分离 → 3.5C）；② 修复 SKILL.md Step 6 乱码残句；③ Step 3.56/3.65 时间码说明对齐 GGUF VAD 段级时间码；④ 新增 `scripts/pack_release.py`（SkillHub 上传打包：排除 .git/__pycache__/缓存，文件数 ≤200 校验，可选出 zip）；⑤ 新增 `references/qa_checklist.md` 冒烟自检清单；⑥ frontmatter 增加 version 字段 |
| v1.13.0 | 2026-09-07 | **快速档引擎更换：Paraformer-large → SenseVoice-Small q8（GGUF）**：实测（FDE 会议 199s + 北大街采 90s）纯 CPU ~33 倍实时、自带标点+数字规整、中文 CER 7.99%，运行时 5MB + 模型 254MB **零 Python/torch 依赖**。新增 `scripts/transcribe_gguf.py`（复用 transcribe_config.json，`--srt` 取 VAD 级时间戳，**内置日文假名伪影过滤**——SenseVoice 在说话人切换处偶发「さいや」类语种标签）；快速档无内分离 → Step 3.5C 语义重切升级为**快速档必做**；Step 3.5B 限定旧 Paraformer 引擎与 MOSS 复核；档位表/推荐逻辑/切段/通知模板/时间码说明全面改写；旧 Paraformer-large 保留为可选引擎（`transcribe_local.py --model paraformer`） |
| v1.12.3 | 2026-09-07 | **新增 Step 3.5C 多说话人语义重切（`scripts/resegment_speakers.py`）**：快速档 CAM++ 的 `preset_spk_num=2` 是双人采访假设，论坛式大会（主持人+多嘉宾+观众）必然把多人并成 1 类。本脚本不重转音频，直接对 transcript.json 逐句做 LLM 语义重分段——内置编号白名单（防 LLM 批间自造编号）、非法编号回退上一说话人、批间 12 句重叠上下文+全局编号表；实测 155 分钟/11 说话人大会全部分对。输出 `.sem.json` + `.meta.json`（含说话人描述供角色映射）。触发条件与双人采访排除规则写入 SKILL.md |
| v1.12.2 | 2026-09-07 | **快速档文本精修 + 文档格式优化**：① 新增 `scripts/refine_paragraphs.py`（Step 3.56）——LLM 对 document.json 逐轮做标点修复（治 Paraformer+ct-punc 的「因。为」错位）、按语义重排自然段（治长独白 ~160 字机械切段的胡乱换行）、轻度精简语气词；单轮长度校验失败自动回退原文，续段时间码按字数占比插值；快速档强烈推荐、MOSS 可跳过。② `build_docx.py` 长独白续段改为**时间码一行 + 内容另起一行**（原为同行拼接，docx 与 Markdown 导出同步修改）。③ 「文档信息·转录工具」自动追加档位与模型大小标注（`_tool_with_size`：快速档 Paraformer-large ~900MB + CAM++ ~30MB / 精准档 MOSS 0.9B ~1.8GB + torch GPU 栈 ~2.7GB / 云端无需本地模型），SKILL.md Step 2.5 档位表加「模型大小」列 |
| v1.12.1 | 2026-09-07 | **三档模型选择（快速/精准/云端）+ 文档全面对齐**：Step 2.5 升级为「模型选择」环节——① 快速 = FunASR Paraformer+CAM++（速度最快、离线、无需 Key）；② 精准 = MOSS 端到端（分离最稳、标点自然）；③ 云端 = Qwen3-ASR-Flash（需 Key）。开始前 `nvidia-smi` 检测显存自动推荐：≥16GB → 精准、8–12GB → 快速、无 N 卡 → 云端/CPU 快速；用户三选一、随时可切。同步清除 SKILL.md/README 中「默认 Paraformer / MOSS 仅回退」与「默认 MOSS」并存的旧文案，切段/说话人/硬件/性能章节全部按三档改写 |
| v1.12.0 | 2026-09-07 | **MOSS 端到端 + 说话人 LLM 语义校正 + 安全加固**：① `prepare.py` MOSS 分片由 12 分钟收紧到 **8 分钟/段**（`MOSS_SEG_SEC=480`，16GB 显存实测峰值 ~10.3GB；12 分钟段曾 CUDA 死锁）；② 新增 `correct_speakers.py`——Qwen-Plus 按「问答语义+占比+连续性+短回应归并」校正说话人角色，并一并产出 summary/summary_sections/person_info（`build_document.py --apply` 直接消费）；③ `build_docx.py` 表格单元格 `_md_escape` 先折叠空白再判公式前缀（修 md 导出注入 bypass），新增 `test_md_escape.py` 20 条回归用例；④ 新增 WeSpeaker 重贴标/benchmark 等辅助脚本与 `run_win_transcribe.ps1` |
| v1.11.0 | 2026-07-20 | **新增 Step 3.55 同音字校对（LLM 后处理，按上下文批量替换）**：中文 ASR 模型按读音识别，常把同音字搞混（在↔再、做↔作、的↔得↔地、了↔啦↔咯、记↔纪↔计、系↔戏↔细、辩↔辨↔辫、帐↔账、复↔覆、像↔象、报↔抱，以及数字/人名/专名的同音替换）。① 新增 `scripts/correct_homophones.py` —— 方式 A 打印 prompt 让 Agent 自己跑 LLM、方式 B `--call-qwen` 直接调 qwen-plus；按 `context` 精确替换 `segments[].text`（无 context 或 context 不匹配的 corrections 会跳过并在 stderr 提示「可能 LLM 幻觉」，避免误伤）。② `build_document.py` 自动检测 `<标题>_transcript.corrected.json` 并优先消费（仅替换 text，保留 speaker/start/end/metadata）；同时 `--apply` 内联支持 `corrections.json` 里的 `homophone_corrections` 字段，一步产出最终 document.json。③ SKILL.md 加 Step 3.55；`prompts.md` 新增同音字校对 prompt 模板（与 `correct_homophones.py` 同步维护）；`test_interview/test_homophones.py` 端到端 PASS（4 条 corrections 真实应用 3 处 + 跳过 1 处 context 不匹配）。 |
| v1.10.1 | 2026-07-20 | **说话人配色收敛（去掉大色块 + 去掉背景高亮，改用色相差异大的彩色圆点）**：v1.10.0 用 🟥🟧🟨🟩🟦🟪🟫⬛ 大色方块 + WD_COLOR_INDEX 背景高亮三重冗余，但前两位说话人会拿到 🟥红/🟧橙，**色相太接近难分**（用户反馈）。收敛为单一来源的彩色圆点 emoji（🔴红 → 🔵蓝 → 🟢绿 → 🟡黄 → 🟣紫 → ⚫黑 → 🟤棕 → ⚪白 → 🟠橙 → 🔘灰 循环），色相尽量分散；默认说话人1=🔴红、说话人2=🔵蓝，相邻说话人配色差距大。`build_docx.py` 删去 `_SPEAKER_HIGHLIGHT` / `_speaker_visual` / `_add_label_runs`，还原回简单的 `_speaker_emoji` + `add_inline_runs`，更轻量 |
| v1.10.0 | 2026-07-20 | **说话人区分强化（三重冗余）+ 内容摘要分板块 + 文档信息精简**：① 每个说话人在每轮首次说话位置用**彩色大色块**（🟥🟧🟨🟩🟦🟪🟫⬛ 循环）+ **说话人名加粗** + **Word 背景高亮（WD_COLOR_INDEX 标准 16 色循环）**三重标识，同一说话人跨轮次保持同一颜色/色块，肉眼/打印/复制粘贴都能一眼分清；② 内容摘要新增 `summary_sections` 字段——除原总结性摘要外，按主题拆成 2+ 个 H2 板块（每个板块 = `{title, content}`），LLM prompt 与 `assemble_document`/`--apply` schema 同步；③ 文档信息板块精简：移除「时间码精度」「摘要与人物信息」两行，仅保留源文件/输入类型/转录工具/说话人识别/转录日期 5 行。`output_schema.md` / `prompts.md` / `test_build_docx.py` 同步 |
| v1.9.0 | 2026-07-14 | **取消 600s 强制终止，改为向用户报告并让用户选择**：① `transcribe_local.py` 模型加载（首次下载）**移除硬超时**，网速慢也能把模型下完；新增 `load_model_with_status()`，每累计满 600s 打印 `⚠️ 已超 600s` 状态横幅（不中断、继续下载）；② `with_timeout` 改为**超时抛异常**（不再 `os._exit` 强杀），`call_qwen.py` 同步；③ SKILL.md 明确 Agent 行为：转录后台启动并轮询，看到横幅即向用户报告并询问「继续/中止」，由用户决策。根治"网速慢时模型没下完就被 kill" |
| v1.8.0 | 2026-07-14 | **技能更名 + 说话人统一中性命名 + 每轮配色标识**：① 技能名「采访转录成文档」→「音视频转文档」（更通用，采访仍覆盖）；② 说话人不再做采访者/受访人这类角色判定，统一按「首次出现顺序」中性命名为 说话人1、说话人2、说话人3……（`build_document.py` 的 `assign_speaker_labels` 按序编号，稳定可预期），真名/角色用 `--apply` 覆盖 `speaker_roles`（键为 说话人1/2/3）；③ 每个说话人一轮的「首次说话位置」用不同颜色的表情（🔴🟠🟡🟢🔵🟣…）标识，`.docx` 与上传用 Markdown 均生效，便于快速区分。文档全量同步。 |
| v1.6.0 | 2026-07-14 | **默认本地模型切换为 Paraformer-large（高精度）**：不再默认下载 SenseVoice-small（small 模型中文精度不足）；SenseVoice 降级为可选轻量项（`--model sensevoice`，要速度/多语言/情感标签时用）。附：修复切换后 `build_document.py` 句级时间码 bug——Paraformer-VAD 返回真实句级 sentence_info，原按段索引对齐插值的逻辑会导致时间码错位/归零，改为「有真实时间码用真实跨度、SenseVoice 才回退插值」。中文准确率（尤其嘈杂/口音场景）与标点恢复均提升。 |
| v1.7.0 | 2026-07-14 | **说话人分离交还模型（Paraformer + CAM++）**：本地不再依赖 LLM 语义切分——Paraformer-large 加载 `spk_model="cam++"`，单次 `generate()` 即产出「每句说话人 id + 真实句级时间码 + 标点」（按声纹自动聚类、无需指定人数、无需 HF Token）。`build_document.py` 改为按真实说话人聚合，仅剩轻量「角色命名」（`--auto` 按说话人聚合提问特征自动判采访者，`--apply` 可覆盖）；`--apply` schema 改为 `{speaker_roles, summary, person_info}`。彻底移除不可靠的逐句启发式与繁重的 LLM 切分，skill 大幅简化。 |
| v1.5.1 | 2026-07-14 | **更新日志细化版本号**：按提交历史为每项独立更新编唯一版本，不再多个更新共用同一版本号 |
| v1.5.0 | 2026-07-14 | **安装幂等化（杜绝重复下载）**：`setup_env.py` 安装前用 `is_importable()` 真实 import 探测；Python 依赖已装即跳过（`--force` 可强制重装）；`install_torch` 已装且版本匹配（要 GPU 且有 CUDA / 要 CPU 有 torch）也跳过，根治「2.7GB CUDA torch 每次运行都重复下载」；`gotchas.md` 新增坑 1.3 作回归护栏。commit `f3bc742` |
| v1.4.5 | 2026-07-13 | **PM 视角整改（去个人化 + 闭环工具化）**：① 删掉钉钉个人身份/收件人等"错误案例"，分发规则泛化为通用最佳实践；② 修 P0 事实矛盾——`output_schema.md` 不再写"本地模式精确到秒"，与 `build_docx.py`/`gotchas` 一致为"句级插值估算、段落边界精确"；③ 补说话人识别工具断点：`build_document.py` 新增 `--apply corrections.json`，Agent（方式 A）复核后一键落盘最终 `document.json`；④ `build_docx.py` 新增 `--no-frame`；⑤ 新增 `prepare.py` 一键生成 `transcribe_config.json`；⑥ 诚实化定位：display_name 去"秒变"、描述主动交代首跑下载量与本地/云端取舍；⑦ Step 5 保留 `_document.json`；⑧ `transcribe_local.py` 元数据不再误标 qwen-plus；`prompts.md` 云端方法A 与"仅段级时间戳"对齐 |
| v1.4.4 | 2026-07-13 | **新增 gotchas 踩坑清单**：`references/gotchas.md` 汇总实测坑（GPU 进程回收、时间码插值、钉钉图不渲染、`dws auth status` 卡 2 分钟、同主题 overwrite 等），并修正 SKILL 旧陈述、补钉钉通用规则、脚本告警 |
| v1.4.3 | 2026-07-13 | **长轮次自动分段**：`build_document.py` 将长独白按 ~160 字/4 句切成多段（每段带时间码），`.docx` 与在线文档均逐段呈现，根治"一大块难读" |
| v1.4.2 | 2026-07-13 | **人物信息条件化（无则省略／多人多表）**：`person_info` 升级为支持多人（`[{name, fields}]`）；短视频未提个人信息时整段省略，多位人物各渲染独立表格；同步更新 `build_docx.py` 渲染与 `prompts.md` 提取指令 |
| v1.4.1 | 2026-07-13 | **GPU 自动检测 + 标准 build_document.py**：`setup_env.py` 检测到 NVIDIA 即装 CUDA 版 torch（本地模型仍默认）；新增标准 `build_document.py` 消费结构化 `segments`，根除手写 `<|withitn|>` 切分导致段丢失的 bug |
| v1.4.0 | 2026-07-13 | **健壮性加固（超时看门狗 + 环境自检防漏装）**：`transcribe_local.py`/`call_qwen.py` 加 `with_timeout` 软超时（超时**抛异常友好退出**，不再 `os._exit` 强制杀进程）；模型加载不设硬超时（网速慢可慢慢下载完），单段 ASR 900s / LLM 调用 180s 超时抛异常后退出，根治"转着转着就没声了"的卡死；`setup_env.py` 改为逐包安装 + 新增 `verify_environment()` 真实 import 自检 |
| v1.3.2 | 2026-07-11 | **静帧抽取优化（五等分，不软解整段）**：`extract_frame.py` 改为将视频严格**五等分**、从每段中心各抽 1 帧按清晰度比选最清晰帧，采用 ffmpeg 输入定位只解码目标点附近极少帧；并移除误入仓库的预览页 `docs/interview-transcriber.html` |
| v1.3.1 | 2026-07-11 | **补充文档：性能预估 + 最低硬件配置**：新增「⏱️ 性能预估」与「💻 最低硬件配置」，并梳理修正若干表述（默认本地、SKILL 重复文本、模型下载体积范围） |
| v1.3.0 | 2026-07-11 | **精简依赖（默认仅 5 包）+ 国内镜像连通性修复**：移出 faster-whisper / pyannote，说话人统一 LLM 语义切分；外网下载改国内镜像 |
| v1.2.8 | 2026-07-10 | **产品经理视角优化（P1–P9/P11 + 多段合并 + SKILL 瘦身）**：新增多段采访合并说明、统一 `call_qwen.py` 调用、全流程进度反馈、SKILL 由 808 行精简至 ~178 行、默认本地转录 |
| v1.2.7 | 2026-07-10 | **移除 Markdown 中间文件**：转录 → `_transcript.json` → `_document.json` → `.docx` 直出，全程无 .md |
| v1.2.6 | 2026-07-10 | 最终交付改为 **Word(.docx)**；新增 Step 3.8 |
| v1.2.5 | 2026-07-10 | 新增 Step 3.7：文档生成后自检、适度精简口语语气词 |
| v1.2.4 | 2026-07-10 | 切段决策改为模型按能力自动处理，不再询问用户 |
| v1.2.4 | 2026-08-04 | 安全与合规修复：Markdown 导出动态内容转义（防链接/HTML/表格/公式注入）；ffmpeg 下载恢复 TLS 证书校验；API Key 统一从 `DASHSCOPE_API_KEY` 环境变量读取；移除平台命名；GBK 控制台 emoji 打印降级 |
| v1.2.3 | 2026-07-10 | 支持音频输入（跳过转 MP3、无静帧）；切段决策移至选完转录方式后的 Step 2.6 |
| v1.2.2 | 2026-07-10 | 美化 README（hero 标题 + 徽章 + 目录 + 工作流图修正），文档预览同步最新输出格式 |
| v1.2.1 | 2026-07-10 | 新增 Step 6：全流程完成后主动询问用户交付位置 |
| v1.2.0 | 2026-07-10 | 修正本地转录前置条件说明（Paraformer/SenseVoice 无需 HuggingFace Token） |
| v1.1.5 | 2026-07-09 | 新增 Step 3.6：LLM 生成内容摘要与人物信息，置于文档正文最前面 |
| v1.1.4 | 2026-07-09 | 适配多种 AI Agent（Codex 等）；统一使用"采访"表述 |
| v1.1.3 | 2026-07-09 | 新增对话时间码：每轮对话标注 [MM:SS]（本地为句级插值估算，段落边界精确） |
| v1.1.2 | 2026-07-09 | 新增 Step 2.5：转录前询问用户选择转录方式 |
| v1.1.1 | 2026-07-09 | 本地转录新增多模型支持：SenseVoice / Paraformer（魔搭社区）+ faster-whisper large-v3，替代原 faster-whisper medium |
| v1.1.0 | 2026-07-09 | README 新增「使用说明」章节（基本用法、输出结果、常见示例、首次准备） |
| v1.0.0 | 2026-07-01 | 初始版本：完整工作流程（预处理→转录→说话人识别→分发） |

---

## 📄 License

MIT
