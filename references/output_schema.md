# 输出数据结构与文档结构

## `<标题>_document.json`（Step 3.5/3.6/3.7 写入，Step 3.8 直接生成 .docx）

```json
{
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "frame_path": "人物静帧.jpg 或 null（音频输入时为 null）",
  "input_type": "video 或 audio",
  "source_file": "<原始输入文件名，如 输入.mp4 / 输入.m4a>",
  "transcription_tool": "通义千问 Qwen3-ASR-Flash（阿里云百炼）或 SenseVoice/Paraformer 模型名",
  "speaker_method": "LLM 语义分析（qwen-plus，免 HF Token）",
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

- `frame_path` 为 `null`（音频输入）时，`build_docx.py` 自动跳过静帧插入。
- `person_info` / `summary` 缺失时对应章节自动省略。

## 最终 `.docx` 文档结构（build_docx.py 渲染结果）

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

> 时间码精度已在文档信息中醒目标注：本地模式精确到秒；云端模式段内为估算值（4 分钟粒度），请勿当作精确时间。
