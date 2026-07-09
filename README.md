# Interview Transcriber | 采访视频转录技能

> 将采访视频一键转化为带说话人识别、内容摘要和人物信息的结构化转录文档。适用于任何支持命令执行的 AI 编码代理。

## ✨ 功能概览

| 功能 | 说明 |
|------|------|
| 视频预处理 | ffmpeg 提取人物静帧 + 转 MP3 音频 + 4 分钟切段 |
| 云端转录 | Qwen3-ASR-Flash（推荐），中文识别准确率高 |
| 本地转录 | faster-whisper + pyannote.audio 声纹分离（备选，无需 API） |
| 对话时间码 | 每轮对话标注 [MM:SS] 时间码，定位视频位置 |
| 说话人识别 | LLM 语义分析，自动区分「采访者」与「受访人」 |
| 内容摘要 | LLM 生成 3-5 句话概括采访核心内容 |
| 人物信息 | LLM 提取受访人学校/专业/年级/家乡/关键经历/核心观点 |
| 多平台分发 | 本地 Markdown / 钉钉文档 / 飞书 / Notion / 其他平台 |

## ⬇️ 安装

把下面的链接发给你的 Agent，让它自动下载安装：

```
https://github.com/torylyj/interview-transcriber
```

安装完成后，在你的 Agent 对话中提到"转录采访视频"即可自动触发该技能。

## 📖 使用说明

使用非常简单，**只需要告诉 Agent 你的视频地址**，剩下的全部自动完成。

### 基本用法

在对话中直接发送视频路径：

```
帮我转录这个采访视频：D:/videos/interview_001.mp4
```

或者：

```
帮我转录这个视频 /Users/me/Desktop/采访视频.mov
```

Agent 收到后会自动执行完整流程，你只需在中间回答一个问题：

> **选择转录方式：**
> - A. 云端转录（推荐，准确率高）— 需要 DashScope API Key
> - B. 本地转录（质量较差，离线可用）— 需要 HuggingFace Token
>
> 回复 A 或 B

回答后 Agent 会继续自动完成：转录 → 说话人识别 → 生成摘要与人物信息 → 输出文档。

### 输出结果

最终生成的 Markdown 文档包含：

1. **人物静帧** — 视频中人物画面截图
2. **内容摘要** — 3-5 句话概括采访核心内容
3. **人物信息** — 受访人学校/专业/年级/家乡/关键经历/核心观点
4. **采访记录** — 带说话人标签和时间码的逐句对话

```
**采访者** [00:00]
你当时为什么选择这个专业？

**受访人** [00:15]
其实我一开始想学的是另一个方向...
```

### 常见用法示例

| 场景 | 示例指令 |
|------|---------|
| 转录并保存到本地 | `帮我转录 D:/video.mp4，保存到桌面` |
| 转录并上传钉钉文档 | `帮我转录这个视频并上传到钉钉文档：D:/video.mp4` |
| 转录多个视频 | `帮我批量转录 D:/videos/ 目录下的所有视频` |
| 只要转录文本 | `帮我转录 D:/video.mp4，不需要摘要和人物信息` |

### 首次使用准备

如果选择**云端转录**（推荐），需要配置 DashScope API Key：

```bash
# 获取地址：https://bailian.console.aliyun.com/?tab=model#/api-key
export DASHSCOPE_API_KEY="sk-your-key-here"
```

如果选择**本地转录**，需要配置 HuggingFace Token：

```bash
# 获取地址：https://huggingface.co/settings/tokens
export HF_TOKEN="hf_your-token-here"
# 模型下载已内置 hf-mirror.com 镜像站，国内直接可用
```

> 💡 **提示**：不确定选哪个？默认选 A（云端转录），准确率远高于本地，且费用极低。

## 🤖 Agent 兼容性

本技能以 Markdown 指令文件（`SKILL.md`）形式编写，不依赖任何特定平台。任何支持 bash 命令执行、文件读写、Python 脚本运行的 AI 编码代理均可使用：

| Agent | 加载方式 |
|-------|---------|
| **WorkBuddy** | 放置在 `~/.workbuddy/skills/` 目录，对话中自动触发 |
| **Claude Code** | 将 `SKILL.md` 内容追加到 `CLAUDE.md` 或通过自定义命令加载 |
| **Codex (OpenAI)** | 作为 `AGENTS.md` 或通过系统提示注入 |
| **Cursor** | 放入 `.cursorrules` 或项目上下文 |
| **其他 Agent** | 将 `SKILL.md` 作为系统提示或上下文注入即可 |

> **LLM 能力说明：** Step 3.5（说话人识别）和 Step 3.6（摘要生成）需要 LLM 能力。大多数编码代理（Claude Code、Codex、WorkBuddy 等）本身即是 LLM，可直接在对话中完成这两步，无需额外 API 调用。

## 📋 工作流程

```
视频文件 (MP4/MOV/AVI)
    │
    ▼
┌─────────────────────────────────┐
│ Step 1: 视频预处理 (ffmpeg)      │
│  ├─ 提取人物静帧 (第5秒, 800px)  │
│  ├─ 转换 MP3 (16kHz 单声道)      │
│  └─ 切分为 4 分钟段              │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ Step 2: 确定文档标题             │
│  └─ 拍摄时间+人物简介            │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ Step 2.5: 询问转录方式           │
│  ├─ A. 云端 (推荐 ✅)           │
│  └─ B. 本地 (质量较差 ⚠️)       │
│  → 根据用户选择创建配置          │
└──────────────┬──────────────────┘
               │
    ▼                          ▼
┌──────────────┐    ┌──────────────────┐
│ Step 3A:     │    │ Step 3B:         │
│ 云端转录     │    │ 本地转录         │
│ Qwen3-ASR    │    │ faster-whisper   │
│ -Flash       │    │ + pyannote.audio │
│ (推荐 ✅)    │    │ (备选 ⚠️)        │
└──────┬───────┘    └────────┬─────────┘
       │                     │
       └─────────┬───────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Step 3.5: LLM 说话人识别        │
│  Agent 自身分析 或 API 调用     │
│  → 区分「采访者」「受访人」     │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ Step 3.6: 生成摘要与人物信息    │
│  ├─ 内容摘要 (3-5句话)          │
│  └─ 人物信息 (学校/专业/年级…)  │
│  → 插入文档正文最前面           │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ Step 4: 输出与分发              │
│  ├─ 本地 Markdown 文件          │
│  ├─ 钉钉 / 飞书 / Notion 等     │
│  └─ 其他平台                    │
└─────────────────────────────────┘
```

## 📄 最终文档结构

```markdown
![人物静帧](人物静帧.jpg)

## 内容摘要
<LLM 生成的 3-5 句话概括>

## 人物信息
| 字段 | 内容 |
|------|------|
| 学校/单位 | ... |
| 专业/学院 | ... |
| 年级/身份 | ... |
| 家乡 | ... |
| 关键经历 | ... |
| 核心观点 | ... |

---

> 转录工具：Qwen3-ASR-Flash
> 说话人识别：LLM 语义分析
> 摘要与人物信息：LLM 生成
> 转录日期：2026-07-09

---

## 采访记录

**采访者** [00:00]
<对话内容>

**受访人** [00:15]
<对话内容>
...
```

## 🚀 快速开始

### 前置条件

- **ffmpeg** — 视频处理（已预装或通过包管理器安装）
- **Python 3.10+** — 运行转录脚本
- **DashScope API Key** — 云端转录必需（[获取地址](https://bailian.console.aliyun.com/?tab=model#/api-key)）
- **HuggingFace Token** — 仅本地转录需要（[获取地址](https://huggingface.co/settings/tokens)）

### 安装依赖

```bash
# 云端转录（推荐）
pip install dashscope

# 本地转录（备选）
pip install faster-whisper pyannote.audio
# 模型下载已内置 hf-mirror.com 镜像站，无需额外配置
```

### 在 AI Agent 中使用

将 `SKILL.md` 加载到你的 Agent 上下文中（方式见上方兼容性表格），然后在对话中说：

> "帮我转录这个采访视频 /path/to/video/"

Agent 会自动执行完整流程：预处理 → 转录 → 说话人识别 → 生成摘要 → 输出文档。

### 手动运行脚本

如果你只想使用转录脚本部分，不依赖 Agent：

```bash
# 1. 视频预处理
ffmpeg -i "video.mp4" -ss 5 -vframes 1 -q:v 2 -vf "scale=800:-1" "人物静帧.jpg" -y
ffmpeg -i "video.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "audio.mp3" -y

# 2. 切分音频（每段4分钟）
ffmpeg -i audio.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0 -t 240 _seg1.mp3 -y
ffmpeg -i audio.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 240 -t 240 _seg2.mp3 -y

# 3. 创建配置文件 transcribe_config.json（格式见 SKILL.md Step 2）

# 4. 云端转录
python scripts/transcribe_qwen.py --config transcribe_config.json

# 或本地转录
python scripts/transcribe_local.py --config transcribe_config.json
```

转录完成后，使用 LLM 进行说话人识别和摘要生成（详见 `SKILL.md` 中 Step 3.5 和 Step 3.6）。

## 📁 项目结构

```
interview-transcriber/
├── SKILL.md                          # 技能定义文件（完整工作流程 + Agent 适配说明）
├── README.md                         # 本文件
├── scripts/
│   ├── transcribe_qwen.py            # 云端转录脚本 (Qwen3-ASR-Flash)
│   └── transcribe_local.py           # 本地转录脚本 (faster-whisper + pyannote)
└── references/
    └── dashscope_setup.md            # DashScope API 配置指南
```

## 🔧 技术选型说明

### 转录方式对比

| 对比项 | 云端 (Qwen3-ASR-Flash) | 本地 (faster-whisper) |
|--------|------------------------|----------------------|
| 中文准确率 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 标点断句 | 自然准确 | 不够准确 |
| 专有名词 | 识别好 | 错误率高 |
| 说话人分离 | 不支持（需 LLM 补充） | pyannote.audio 声纹分离 |
| 网络 | 需要 | 不需要 |
| 成本 | 免费额度内极低 | 免费（需 GPU 更佳） |
| 推荐场景 | **日常使用** | 无网络/API 不可用 |

### 说话人识别方案

```
云端模式: Qwen3-ASR-Flash 连续文本 → LLM 语义切分 → 采访者/受访人
本地模式: pyannote.audio 声纹分离 → SPEAKER_00/01 → LLM 角色映射 → 采访者/受访人
```

> 启发式方法（关键词+段落长度）已废弃，准确率不可接受。

### LLM 调用方式

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| Agent 自身执行 | Claude Code、Codex、WorkBuddy 等 | Agent 本身即是 LLM，直接在对话中分析转录文本，无需额外 API 调用 |
| 调用外部 API | Agent 不便直接处理时 | 通过 Python 调用 `dashscope.Generation.call(model='qwen-plus')` |

## ⚠️ 注意事项

- **文档命名规范**：`拍摄时间+人物简介`，如 `26-0509 车辆学院直博生`（人物简介 ≤10 字）
- **Windows 路径**：使用正斜杠 `/`，避免中文路径传给 API
- **长文本处理**：LLM 单次输入建议不超过 8000 字符，超长需分段
- **在线文档上传**：部分平台 API 限制内容长度，超长文档需分段上传
- **本地转录质量**：faster-whisper medium 模型中文质量明显差于云端，仅建议备选使用
- **模型下载镜像**：本地转录脚本已内置 `hf-mirror.com` 镜像站，无需额外配置；如需更换可通过 `HF_ENDPOINT` 环境变量自定义

## 📝 更新日志

| 日期 | 内容 |
|------|------|
| 2026-07-09 | README 新增「使用说明」章节，包含基本用法、输出结果、常见示例和首次准备 |
| 2026-07-09 | 本地转录脚本内置 HuggingFace 镜像站（hf-mirror.com），避免国内无法下载模型 |
| 2026-07-09 | 新增 Step 2.5：转录前询问用户选择转录方式，明确告知本地转录质量较差 |
| 2026-07-09 | 新增对话时间码：每轮对话标注 [MM:SS]，云端段级精度，本地精确到秒 |
| 2026-07-09 | 适配多种 AI Agent（Claude Code、Codex 等）；统一使用"采访"表述 |
| 2026-07-09 | 新增 Step 3.6：LLM 生成内容摘要与人物信息，置于文档正文最前面 |
| 2026-07-01 | 初始版本：完整工作流程（预处理→转录→说话人识别→分发） |

## 📄 License

MIT
