# 输出数据结构与文档结构

## `<标题>_document.json`（Step 3.5/3.6/3.7 写入，Step 3.8 直接生成 .docx）

```json
{
  "title": "<拍摄时间+人物简介，如 26-0509 车辆学院直博生>",
  "frame_path": "人物静帧.jpg 或 null（音频输入时为 null）",
  "input_type": "video 或 audio",
  "source_file": "<原始输入文件名，如 输入.mp4 / 输入.m4a>",
  "transcription_tool": "通义千问 Qwen3-ASR-Flash（阿里云百炼）或 SenseVoice/Paraformer 模型名",
  "speaker_method": "CAM++ 说话人嵌入（FunASR spk_model，本地）或 LLM 语义切分（云端 qwen-plus，免 HF Token）",
  "summary_method": "LLM 生成",
  "date": "YYYY-MM-DD",
  "summary": "<LLM 生成的 3-5 句话摘要，多段落用 \\n 分隔>",
  "person_info": [
    {
      "name": "人物（张同学）",   // 表格标题；单人可写"人物"或留空
      "fields": [
        {"field": "学校/单位", "value": "..."},
        {"field": "专业/学院", "value": "..."},
        {"field": "年级/身份", "value": "..."},
        {"field": "家乡", "value": "..."},
        {"field": "关键经历", "value": "..."},
        {"field": "核心观点", "value": "..."}
      ]
    }
    // 若有多位人物，再追加一个对象（渲染为独立表格）
  ],
  "conversation": [
    {"speaker": "说话人1", "timestamp": "[00:00]", "text": "<对话内容>"},
    {"speaker": "说话人2", "timestamp": "[00:15]", "text": "<对话内容>"},
    {"speaker": "说话人1", "timestamp": "[01:30]", "text": "<对话内容>"}
  ]
}
```

- `frame_path` 为 `null`（音频输入）时，`build_docx.py` 自动跳过静帧插入。
- `summary` 缺失时「内容摘要」章节自动省略。
- `person_info` 为空数组 `[]` 或缺失时，**整段「人物信息」板块自动省略**（未透露任何个人信息时不展示空白表格）。
- `person_info` 含多个对象时，**每位人物渲染为独立表格**（标题取各自 `name`）；单人则只渲染一个表格。

## 最终 `.docx` 文档结构（build_docx.py 渲染结果）

```
# <标题>

<居中人物静帧，仅视频输入；音频输入时无此图>

📝 内容摘要
<LLM 生成的 3-5 句话概括>

👤 人物信息（无信息则该板块整段省略；多人时每位人物一个独立表格）

— 人物（张同学）—
| 字段 | 内容 |
|------|------|
| 学校/单位 | ... |
| ...  | ... |

— 人物（李同学）—        ← 第二位人物：再多用一个表格
| 字段 | 内容 |
|------|------|
| 学校/单位 | ... |
| ...  | ... |

📋 文档信息
> 源文件：<source_file>
> 输入类型：视频 / 音频
> 转录工具：Qwen3-ASR-Flash / SenseVoice
> 说话人识别：CAM++ 说话人嵌入（本地）/ LLM 语义切分（云端）
> 摘要与人物信息：LLM 生成
> 转录日期：YYYY-MM-DD
> 时间码精度：本地 Paraformer 为真实句级时间码（VAD 句级，段落边界精确）；SenseVoice 本地为句级插值估算（段落边界精确，段内为估算值）；云端模式段内为估算值（4 分钟粒度）

💬 对话记录
**说话人1** [00:00]
<对话内容>

**说话人2** [00:15]
<对话内容>
```

> 时间码精度已在文档信息中醒目标注：本地模式为句级插值估算（段落边界精确）；云端模式段内为估算值（4 分钟粒度），请勿当作精确时间。
