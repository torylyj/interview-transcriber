# LLM Prompt 模板（Step 3.5 / Step 3.6）

> 两种方式通用说明：
> - **方式 A（推荐）**：Agent 自身即 LLM，直接按下面的 prompt 在对话中处理，无需 API 调用。
> - **方式 B（外部 API）**：非 LLM Agent 用 `python <skill_dir>/scripts/call_qwen.py` 调用 qwen-plus：
>   `python <skill_dir>/scripts/call_qwen.py --prompt-file <prompt.txt> --model qwen-plus`
>   把下列 prompt 写入 `<prompt.txt>` 即可（将 `{raw_text}` / `{transcribed_text}` 替换为实际文本）。
>
> **长文本处理**：LLM 单次输入建议 ≤ 8000 字符，超过时分段处理后再拼接。

---

## Step 3.5 方法 A：云端模式 — LLM 语义分析切分

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

---

## Step 3.5 方法 B：本地模式 — LLM 角色映射

本地转录已包含 `SPEAKER_00 / SPEAKER_01 …` 标签，LLM 只需判断哪个是采访者、哪个是受访人（或其他角色）：

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

> 本地 SenseVoice/Paraformer 中文质量优秀，配合 LLM 语义切分角色映射效果好；如个别长回答切分不佳，可在 Step 3.9 预览环节由用户纠正或改用云端。

---

## Step 3.6 生成内容摘要与人物信息

```
你是一个专业的采访内容编辑助手。以下是一段采访的转录文本，已按采访者和受访人区分好段落。请基于对话内容生成以下两部分：

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
{transcribed_text}
```

> Agent 自身执行方式 A 时，可直接按以上结构输出，再整理进 `_document.json`。
