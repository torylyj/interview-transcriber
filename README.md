# 🎬 Interview Transcriber

> 采访视频一键转录技能 · 自动把视频变成**带说话人识别、内容摘要与人物信息**的结构化文档

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org)
[![中文转录](https://img.shields.io/badge/中文转录-Qwen3--ASR--Flash-brightgreen)](https://help.aliyun.com/zh/model-studio/)
[![本地模型](https://img.shields.io/badge/本地模型-SenseVoice%20%7C%20Paraformer-orange)](https://modelscope.cn)
[![Agents](https://img.shields.io/badge/Agent-WorkBuddy%20%7C%20Claude%20Code%20%7C%20Codex-purple)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-blue)](#license)

给 Agent 一段采访视频，它会自动跑完 **预处理 → 转录 → 说话人识别 → 摘要与人物信息 → 输出文档**，最后还会问你「要把文档发到哪里」。你只需要在中间选一下转录方式。

## 📑 目录

- [功能概览](#功能概览)
- [安装](#安装)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [工作流程](#工作流程)
- [输出文档结构](#输出文档结构)
- [Agent 兼容性](#agent-兼容性)
- [技术选型](#技术选型)
- [注意事项](#注意事项)
- [更新日志](#更新日志)

---

## ✨ 功能概览

| 功能 | 说明 |
|------|------|
| 🎞️ 输入预处理 | 视频：提取静帧 + 转 MP3；音频：直接用作音频（跳过转 MP3、无静帧） |
| ☁️ 云端转录 | Qwen3-ASR-Flash（推荐），中文识别准确率高 |
| 💻 本地转录 | SenseVoice / Paraformer（魔搭社区，中文优秀）+ faster-whisper（备选） |
| ⏱️ 对话时间码 | 每轮对话标注 `[MM:SS]`，精准定位视频位置 |
| 🗣️ 说话人识别 | LLM 语义分析，自动区分「采访者」与「受访人」 |
| 📝 内容摘要 | LLM 生成 3-5 句话概括采访核心内容 |
| 👤 人物信息 | LLM 提取受访人学校 / 专业 / 年级 / 家乡 / 经历 / 观点 |
| 📤 多平台分发 | 本地 Markdown / 钉钉文档 / 飞书 / Notion / 其他平台 |

---

## 📦 安装

把这个仓库链接直接发给你的 Agent，让它自动下载安装即可：

```
https://github.com/torylyj/interview-transcriber
```

安装完成后，在 Agent 对话中提到「转录采访视频」就会自动触发。

---

## 🚀 快速开始

### 前置条件

- **ffmpeg** — 视频处理（已预装或通过包管理器安装）
- **Python 3.10+** — 运行转录脚本
- **DashScope API Key** — 云端转录必需（[获取地址](https://bailian.console.aliyun.com/?tab=model#/api-key)）
- **HuggingFace Token** — *仅*本地声纹分离需要（[获取地址](https://huggingface.co/settings/tokens)），SenseVoice / Paraformer 无需

### 安装依赖

```bash
# 云端转录（推荐）
pip install dashscope

# 本地转录 — SenseVoice / Paraformer（推荐，从魔搭社区下载）
pip install funasr

# 本地转录 — faster-whisper（备选，从 HuggingFace 下载）
pip install faster-whisper   # 模型下载内置多镜像站自动降级

# 声纹分离（可选，无 Token 时跳过，改用 LLM 语义切分）
pip install pyannote.audio
```

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

Agent 收到后会自动执行完整流程，你只需在中间回答一个问题：

> **选择转录方式：**
> - **A. 云端转录**（推荐，准确率高）— 需要 DashScope API Key
> - **B. 本地转录**（离线可用，默认 SenseVoice 中文质量接近云端）— 无需 HuggingFace
>
> 回复 A 或 B

选择方式后，Agent 会根据所选方式和音频时长**确认是否需要切段**（云端超过 5 分钟必须切，本地长音频建议切、短音频可不切），然后继续自动完成：**转录 → 说话人识别 → 生成摘要与人物信息 → 输出文档**，最后主动询问你要把文档发到哪里。

### 输出结果

最终生成的 Markdown 文档包含：

1. **人物静帧**（仅视频输入）— 视频中人物画面截图（居中显示）；音频输入时无此行
2. **内容摘要** — 3-5 句话概括采访核心内容
3. **人物信息** — 受访人学校 / 专业 / 年级 / 家乡 / 关键经历 / 核心观点
4. **采访记录** — 带说话人标签和时间码的逐句对话

### 常见用法示例

| 场景 | 示例指令 |
|------|---------|
| 转录并保存到本地 | `帮我转录 D:/video.mp4，保存到桌面` |
| 转录并上传钉钉文档 | `帮我转录这个视频并上传到钉钉文档：D:/video.mp4` |
| 转录音频录音 | `帮我转录这段录音：D:/audios/interview.m4a` |
| 转录多个视频 | `帮我批量转录 D:/videos/ 目录下的所有视频` |
| 只要转录文本 | `帮我转录 D:/video.mp4，不需要摘要和人物信息` |

### 首次使用准备

**云端转录**（推荐）需要配置 DashScope API Key：

```bash
# 获取地址：https://bailian.console.aliyun.com/?tab=model#/api-key
export DASHSCOPE_API_KEY="sk-your-key-here"
```

**本地转录**默认 SenseVoice 从魔搭社区下载，**无需** HuggingFace Token。仅想启用可选 pyannote.audio 声纹分离时才需要：

```bash
# 获取地址：https://huggingface.co/settings/tokens
export HF_TOKEN="hf_your-token-here"
# 仅用于 pyannote.audio 声纹分离（可选）
# 无 Token 时跳过声纹分离，改用 LLM 语义切分说话人
```

> 💡 **提示**：默认选 A（云端转录），准确率最高且费用极低；选 B 时默认使用 SenseVoice（中文质量接近云端，从魔搭社区下载，无需 HuggingFace）。

---

## 🔄 工作流程

<div align="center">

```mermaid
flowchart TD
    IN([📁 输入文件]) --> DET{检测类型}
    DET -->|视频| S1v[Step 1 · 视频预处理<br/>静帧 + 转 MP3]
    DET -->|音频| S1a[Step 1 · 音频预处理<br/>跳过转 MP3 · 无静帧]
    S1v --> S2[Step 2 · 确定标题]
    S1a --> S2
    S2 --> S25{Step 2.5<br/>选择转录方式}
    S25 -->|A 云端| S3A[Step 3A · Qwen3-ASR-Flash]
    S25 -->|B 本地| S3B[Step 3B · SenseVoice]
    S3A --> S26
    S3B --> S26
    S26{Step 2.6<br/>是否切段?}
    S26 -->|切段| SEG[切为 4 分钟段]
    S26 -->|不切| NSEG[整段音频]
    SEG --> S35
    NSEG --> S35
    S35[Step 3.5 · 说话人识别] --> S36[Step 3.6 · 摘要 + 人物信息]
    S36 --> S4[Step 4 · 输出与分发]
    S4 --> S6[Step 6 · 询问交付位置]

    classDef cloud fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20;
    classDef local fill:#e3f2fd,stroke:#1565c0,color:#0d47a1;
    classDef main fill:#fff3e0,stroke:#ef6c00,color:#e65100;
    class S3A cloud;
    class S3B local;
    class S1v,S1a,S2,S25,S26,S35,S36,S4,S6,SEG,NSEG main;
    linkStyle default stroke-width:1px;
```

</div>

---

## 📄 输出文档结构

```markdown
# <标题>

<!-- 视频输入时插入静帧，音频输入时无此行 -->
<div align="center">
<img src="人物静帧.jpg" width="280" />
</div>

## 📝 内容摘要
<LLM 生成的 3-5 句话概括>

## 👤 受访人信息
| 字段 | 内容 |
|------|------|
| 学校/单位 | ... |
| 专业/学院 | ... |
| 年级/身份 | ... |
| 家乡 | ... |
| 关键经历 | ... |
| 核心观点 | ... |

## 📋 文档信息
> 转录工具：Qwen3-ASR-Flash / SenseVoice
> 说话人识别：LLM 语义分析
> 摘要与人物信息：LLM 生成
> 转录日期：2026-07-09

## 💬 采访记录
**采访者** [00:00]
<对话内容>

**受访人** [00:15]
<对话内容>
...
```

---

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

---

## 🔧 技术选型说明

### 转录方式对比

| 对比项 | 云端 (Qwen3-ASR-Flash) | 本地 SenseVoice | 本地 faster-whisper |
|--------|------------------------|-----------------|---------------------|
| 中文准确率 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 模型来源 | 阿里云 API | 魔搭社区（国内直连） | HuggingFace（需镜像） |
| 模型大小 | 无需下载 | ~500MB | ~3GB |
| 说话人分离 | 不支持（需 LLM） | 不支持（需 LLM/pyannote） | 不支持（需 LLM/pyannote） |
| 网络 | 需要 | 不需要 | 不需要（下载时需要） |
| 成本 | 免费额度内极低 | 免费 | 免费 |
| 推荐场景 | **日常使用** | 无 API/离线场景 | 通用多语言场景 |

### 说话人识别方案

```
云端模式: Qwen3-ASR-Flash 连续文本 → LLM 语义切分 → 采访者/受访人
本地模式(SenseVoice/Paraformer): FunASR 转录 → LLM 语义切分 或 pyannote.audio 声纹分离 → 采访者/受访人
本地模式(faster-whisper): faster-whisper 转录 → LLM 语义切分 或 pyannote.audio 声纹分离 → 采访者/受访人
```

> 启发式方法（关键词+段落长度）已废弃，准确率不可接受。

### LLM 调用方式

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| Agent 自身执行 | Claude Code、Codex、WorkBuddy 等 | Agent 本身即是 LLM，直接在对话中分析转录文本，无需额外 API 调用 |
| 调用外部 API | Agent 不便直接处理时 | 通过 Python 调用 `dashscope.Generation.call(model='qwen-plus')` |

---

## ⚠️ 注意事项

- **文档命名规范**：`拍摄时间+人物简介`，如 `26-0509 车辆学院直博生`（人物简介 ≤10 字）
- **Windows 路径**：使用正斜杠 `/`，避免中文路径传给 API
- **长文本处理**：LLM 单次输入建议不超过 8000 字符，超长需分段
- **在线文档上传**：部分平台 API 限制内容长度，超长文档需分段上传
- **本地转录质量**：SenseVoice / Paraformer（阿里达摩院中文模型）质量接近云端，从魔搭社区下载；faster-whisper 中文质量一般，仅作通用备选
- **模型下载镜像**：SenseVoice / Paraformer 从魔搭社区下载（国内直连，无需 HuggingFace）；faster-whisper 内置多镜像站自动降级（hf-mirror.com → HuggingFace 官方）；pyannote.audio 需 HuggingFace Token，无 Token 时可跳过声纹分离

---

## 📝 更新日志

| 日期 | 内容 |
|------|------|
| 2026-07-10 | 支持音频输入（跳过转 MP3、无静帧）；切段决策移至选完转录方式后的 Step 2.6；工作流图增加输入类型分支 |
| 2026-07-10 | 美化 README（hero 标题 + 徽章 + 目录 + 工作流图修正），文档预览同步最新输出格式 |
| 2026-07-10 | 新增 Step 6：全流程完成后主动询问用户交付位置 |
| 2026-07-10 | 修正本地转录前置条件说明（SenseVoice 无需 HuggingFace Token） |
| 2026-07-09 | README 新增「使用说明」章节，包含基本用法、输出结果、常见示例和首次准备 |
| 2026-07-09 | 本地转录新增多模型支持：SenseVoice / Paraformer（阿里达摩院中文模型，魔搭社区下载）+ faster-whisper large-v3，替代原 faster-whisper medium |
| 2026-07-09 | 新增 Step 2.5：转录前询问用户选择转录方式，明确告知本地转录质量差异 |
| 2026-07-09 | 新增对话时间码：每轮对话标注 [MM:SS]，云端段级精度，本地精确到秒 |
| 2026-07-09 | 适配多种 AI Agent（Claude Code、Codex 等）；统一使用"采访"表述 |
| 2026-07-09 | 新增 Step 3.6：LLM 生成内容摘要与人物信息，置于文档正文最前面 |
| 2026-07-01 | 初始版本：完整工作流程（预处理→转录→说话人识别→分发） |

---

## 📄 License

MIT
