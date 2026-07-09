# Street Interview Transcriber | 街采视频转录技能

> 将街头采访视频一键转化为带说话人识别、内容摘要和人物信息的结构化转录文档。

## ✨ 功能概览

| 功能 | 说明 |
|------|------|
| 视频预处理 | ffmpeg 提取人物静帧 + 转 MP3 音频 + 4 分钟切段 |
| 云端转录 | Qwen3-ASR-Flash（推荐），中文识别准确率高 |
| 本地转录 | faster-whisper + pyannote.audio 声纹分离（备选，无需 API） |
| 说话人识别 | Qwen-Plus LLM 语义分析，自动区分「采访者」与「受访人」 |
| 内容摘要 | LLM 生成 3-5 句话概括采访核心内容 |
| 人物信息 | LLM 提取受访人学校/专业/年级/家乡/关键经历/核心观点 |
| 多平台分发 | 本地 Markdown / 钉钉在线文档 / 其他平台 |

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
│  Qwen-Plus 语义分析/角色映射    │
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
│  ├─ 钉钉在线文档                │
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
> 说话人识别：Qwen-Plus LLM 语义分析
> 摘要与人物信息：Qwen-Plus LLM 生成
> 转录日期：2026-07-09

---

## 采访记录

**采访者**
<对话内容>

**受访人**
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
```

### 使用方式

本技能设计为 WorkBuddy AI 助手的技能模块，在对话中自然触发：

> "帮我转录这个街采视频 H:\街头采访\清华26-0703\"

WorkBuddy 会自动执行完整流程：预处理 → 转录 → 说话人识别 → 生成摘要 → 输出文档。

### 手动运行脚本

```bash
# 1. 视频预处理
ffmpeg -i "video.mp4" -ss 5 -vframes 1 -q:v 2 -vf "scale=800:-1" "人物静帧.jpg" -y
ffmpeg -i "video.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "audio.mp3" -y

# 2. 切分音频（每段4分钟）
ffmpeg -i audio.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0 -t 240 _seg1.mp3 -y
ffmpeg -i audio.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 240 -t 240 _seg2.mp3 -y

# 3. 云端转录
python scripts/transcribe_qwen.py --config transcribe_config.json

# 或本地转录
python scripts/transcribe_local.py --config transcribe_config.json
```

转录完成后，使用 Qwen-Plus LLM 进行说话人识别和摘要生成（详见 SKILL.md 中 Step 3.5 和 Step 3.6）。

## 📁 项目结构

```
interview-transcriber/
├── SKILL.md                          # 技能定义文件（完整工作流程）
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
云端模式: Qwen3-ASR-Flash 连续文本 → Qwen-Plus LLM 语义切分 → 采访者/受访人
本地模式: pyannote.audio 声纹分离 → SPEAKER_00/01 → Qwen-Plus LLM 角色映射 → 采访者/受访人
```

> 启发式方法（关键词+段落长度）已废弃，准确率不可接受。

## ⚠️ 注意事项

- **文档命名规范**：`拍摄时间+人物简介`，如 `26-0509 车辆学院直博生`（人物简介 ≤10 字）
- **Windows 路径**：使用正斜杠 `/`，避免中文路径传给 API
- **长文本处理**：Qwen-Plus 单次输入建议不超过 8000 字符，超长需分段
- **钉钉上传**：doc create 限制 10000 字符，超长文档需分段上传
- **本地转录质量**：faster-whisper medium 模型中文质量明显差于云端，仅建议备选使用

## 📝 更新日志

| 日期 | 内容 |
|------|------|
| 2026-07-09 | 新增 Step 3.6：LLM 生成内容摘要与人物信息，置于文档正文最前面 |
| 2026-07-01 | 初始版本：完整工作流程（预处理→转录→说话人识别→分发） |

## 📄 License

MIT
