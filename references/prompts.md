# LLM Prompt 模板（Step 3.5 / Step 3.6）

> 两种方式通用说明：
> - **方式 A（推荐）**：Agent 自身即 LLM，直接按下面的 prompt 在对话中处理，无需 API 调用。
> - **方式 B（外部 API）**：非 LLM Agent 用 `python <skill_dir>/scripts/call_qwen.py` 调用 qwen-plus：
>   `python <skill_dir>/scripts/call_qwen.py --prompt-file <prompt.txt> --model qwen-plus`
>   把下列 prompt 写入 `<prompt.txt>` 即可（将 `{raw_text}` / `{transcribed_text}` 替换为实际文本）。
>
> **长文本处理**：LLM 单次输入建议 ≤ 8000 字符，超过时分段处理后再拼接。
>
> **命名约定（全技能统一）**：说话人一律中性编号为 **说话人1 / 说话人2 / 说话人3……**，按「首次开口说话」的顺序分配，**不做采访者/受访人这类角色判定**。本地模式由 `build_document.py --auto` 自动完成编号；云端模式由下方 LLM prompt 直接产出 说话人N 标签。

---

## Step 3.5 方法 A：云端模式 — LLM 语义分析切分

```
You are a professional transcript editor. Below is a raw transcription of an audio/video recording. The text contains dialogue from multiple participants — they are mixed together in one continuous block and are not yet labeled. The text is grouped by audio chunk; each chunk begins with a timestamp like [MM:SS] marking that chunk's start (in cloud mode one timestamp is emitted per ~4-minute segment). Within a chunk there may be many sentences without individual timestamps.

Your task:
1. Split the text into individual dialogue turns (each question and each answer should be separate).
2. Label each turn with a neutral speaker number in order of first appearance: **说话人1** for the first speaker to appear, **说话人2** for the second, **说话人3** for the third, and so on. Do NOT use role-based labels like interviewer/interviewee. Follow with the timestamp of its first line.
3. Each turn should be on its own line(s), separated by a blank line.
4. Do NOT merge multiple questions into one block or multiple answers into one block.
5. Keep the original wording exactly as-is, do not paraphrase.
6. For each dialogue turn, attach the timestamp of the chunk it belongs to (or interpolate within the chunk by position) at the start of the turn.
7. If a short utterance like "嗯" or "明白" is from 说话人1, label it as 说话人1.

Output format:
**说话人1** [MM:SS]
[content]

**说话人2** [MM:SS]
[content]

**说话人1** [MM:SS]
[content]

...and so on for each turn.

IMPORTANT: Output ONLY the labeled dialogue with timestamps. No preamble, no summary, no explanation.

Raw transcript:
{raw_text}
```

---

## Step 3.5 方法 B：本地模式 — 模型内分离 + 中性说话人命名（无需 LLM）

> ⚠️ **v1.7.0 变更**：本地说话人分离已由 CAM++ 在模型内完成（`transcribe_local.py` 直接产出 `SPEAKER_00 / SPEAKER_01 …` 标签，**无需 LLM 切分**）。
> 说话人命名（说话人1/2/3……）交给 `build_document.py --auto` 轻量完成（按首次出现顺序中性编号，无需 LLM）。
> 仅在 `--auto` 命名不准时用 `build_document.py --apply corrections.json`（schema: `{"speaker_roles": {"说话人1":"张三", ...}, ...}`）覆盖。
> 下方 LLM prompt **仅作可选参考**：如需 LLM 辅助判定，把 `raw_text` 喂给它，再把结果整理进 `corrections.json` 的 `speaker_roles`。

本地转录已包含 `SPEAKER_00 / SPEAKER_01 …` 标签（CAM++ 声纹聚类产物），`build_document.py` 会按首次出现顺序把它们中性命名为 说话人1/说话人2/说话人3……，无需 LLM 判断角色：

```
以下是一段音视频的转录文本，已通过声纹分离区分出 N 个说话人（SPEAKER_00、SPEAKER_01 …）。
每段对话开头有时间码 [MM:SS]，表示该段在音频/视频中的位置。
请根据对话内容判断说话人顺序，然后将标签替换为中性编号"说话人1""说话人2"……（按首次出现顺序）。

判断规则：
- 说话人1：第一位开口说话的人
- 说话人2：第二位开口说话的人（其余依此类推）
- 若出现更多说话人，依次编号为 说话人3、说话人4……（保持首次出现顺序一致）

严格要求：
1. 严格保持原文内容不变，只替换说话人标签为"**说话人1**""**说话人2**"……（按首次出现顺序编号）
2. 保留每段对话开头的时间码
3. 不要添加任何额外说明

转录文本：
{raw_text}
```

> 本地 Paraformer 中文质量优秀，且说话人已由 CAM++ 在模型内分离（无需 LLM 切分）；说话人中性命名由 `build_document.py --auto` 轻量完成。如 `--auto` 命名不准，可在 Step 3.9 预览环节由用户用 `--apply` 纠正，或改用云端 Qwen3-ASR-Flash（云端无原生分离、仍需 LLM 语义切分）。

---

## Step 3.6 生成内容摘要与人物信息

```
你是一个专业的音视频内容编辑助手。以下是一段音视频的转录文本，已按说话人1/说话人2……区分好段落。请基于对话内容生成以下两部分：

## 一、内容摘要

用 3-5 句话概括本次音视频的核心内容，包括：
- 音视频的主要话题和讨论方向
- 各说话人表达的核心观点或态度
- 对话中提到的关键事件或经历

## 二、人物信息

从对话内容中提取人物的关键信息。规则：
- 字段包括：学校/单位、专业/学院、年级/身份、家乡、关键经历、核心观点。
- 若**完全未提及任何个人信息**（以上字段都无从得知），则**不输出人物信息板块**，person_info 直接为空数组 []。
- 若仅部分字段有信息，只填有内容的字段；**不要把"未提及"当成有效内容填进去**。
- 若有多位人物（如群访、多人出镜），每位人物单独一组，用 name 区分（如"人物（张同学）""旁白"）。

输出格式要求（严格）：
1. 「一、内容摘要」输出纯文本（3-5 句，≤150 字）。
2. 「二、人物信息」输出 JSON 数组（直接对应 _document.json 的 person_info 字段），放在一个 json 代码块中。示例：
[
  {
    "name": "人物（张同学）",
    "fields": [
      {"field": "学校/单位", "value": "..."},
      {"field": "专业/学院", "value": "..."},
      {"field": "年级/身份", "value": "..."},
      {"field": "家乡", "value": "..."},
      {"field": "关键经历", "value": "..."},
      {"field": "核心观点", "value": "..."}
    ]
  }
]
（若有第二位人物，在数组中再追加一个对象；单人时 name 可写"人物"或省略。）
3. 仅基于转录文本内容提取，不要编造或推测。
4. 人物信息中"关键经历"和"核心观点"各不超过 50 字。

转录文本：
{transcribed_text}
```

> Agent 自身执行方式 A 时，可直接按以上结构输出：将「一」写入 `summary`，将「二」的 JSON 数组写入 `_document.json` 的 `person_info`（无个人信息时写 `[]`，整段人物信息板块将被省略）。
