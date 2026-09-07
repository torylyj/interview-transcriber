#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
correct_speakers.py — 本地 FunASR 转录后的 LLM 语义校正（说话人 + 摘要 + 人物信息）

为什么需要它：
  FunASR（Paraformer/SenseVoice）+ CAM++ 说话人嵌入很快，但纯靠声纹聚类在
  街头采访（短应答、抢话、环境噪声）下偶尔会把“采访者/受访者”贴反，或把同一个人
  抖成多号。这种“谁是谁”的判定用声纹启发式不可靠，必须用 LLM 按对话语义
  （问答逻辑、称呼、内容）来校正。

它做什么：
  1. 读取 transcript.json（FunASR 产出，segments 含 SPEAKER_XX + 文本 + 时间码）
  2. 复用 build_document 的分组/命名逻辑，得到带“采访者/受访者/说话人N”标签的轮次
  3. 把对话喂给 Qwen-Plus，输出结构化 JSON：
       {
         "speaker_roles": {"采访者":"采访者","受访者":"受访者"},  # 若贴反则交换
         "summary": "一句话概述",
         "summary_sections": [{"title":"", "content":""}],
         "person_info": [{"role":"受访者","name":"","school":"","major":"","grade":""}]
       }
  4. 写出 corrections.json，交给 build_document.py --apply 合并进最终 document.json

用法：
  python correct_speakers.py transcript.json --api-key $DASHSCOPE_API_KEY
  python correct_speakers.py transcript.json --output corrections.json
  # api-key 也可走环境变量 DASHSCOPE_API_KEY
"""

import os
import sys
import json
import argparse
import functools

print = functools.partial(print, flush=True)

# 复用 build_document 的分组与命名逻辑（同目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_document import (
    assign_speaker_labels,
    group_turns,
    merge_speaker_jitter,
    apply_role_labels,
)


def load_segments(transcript_path):
    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    segs = data.get("segments") or []
    if not segs:
        # 兼容旧结构
        segs = data.get("data", {}).get("segments", []) if isinstance(data.get("data"), dict) else []
    if not segs:
        print("❌ transcript.json 中找不到 segments。")
        sys.exit(1)
    return data, segs


def build_labeled_turns(segs):
    """返回 [(speaker_label, text), ...]，speaker_label 已归并为 采访者/受访者/说话人N。"""
    segs = merge_speaker_jitter(segs)
    label_map = assign_speaker_labels(segs)
    turns = apply_role_labels(group_turns(segs), label_map)
    out = []
    for t in turns:
        sp = t.get("speaker", "")
        text = (t.get("text") or "").strip()
        if text:
            out.append((sp, text))
    return out


def build_prompt(title, turns):
    lines = []
    for i, (sp, text) in enumerate(turns, 1):
        lines.append(f"{i}. [{sp}] {text}")
    dialogue = "\n".join(lines)
    # 说话人占比统计：采访者通常提问短、轮次多但占比小；受访者回答长、占比大
    sp_count = {}
    sp_chars = {}
    for sp, text in turns:
        sp_count[sp] = sp_count.get(sp, 0) + 1
        sp_chars[sp] = sp_chars.get(sp, 0) + len(text)
    total_chars = sum(sp_chars.values()) or 1
    stats = "，".join(
        f"{sp}: {sp_count[sp]} 轮 / 约 {sp_chars[sp] * 100 // total_chars}% 文本量"
        for sp in sp_count
    )
    prompt = f"""你是一个专业的采访转录校对助手。下面是一段街头采访的转录草稿，已按说话人初步标注为「采访者/受访者」（或说话人N）。

任务：
1. 核对说话人角色是否正确——采访者=提问方，受访者=回答方。若草稿把两人贴反了，请在 speaker_roles 里交换它们的标签。
2. 连续性约束：正常对话中同一人的发言是连续的（通常 ≥2 句才换人）。若草稿出现「单人单句、来回快速切换」的碎片，多半是声纹聚类抖动，请结合对话语义把碎片归到正确的说话人，不要机械照抄草稿标注。
3. 短回应归并："嗯/对/是/好的/明白/对吧"等单字短回应一般并入说话人自己的回合，不要单独成轮。
4. 写一句 30 字以内的内容概述（summary）。
5. 可选：把概述拆成 1-3 个要点板块（summary_sections，每项含 title 与 content）。
6. 提取人物信息 person_info：对每个角色，尽量从对话中识别 姓名/学校/专业/年级；未提及的字段填空字符串。

说话人占比参考（采访者通常提问短、轮次多但占比小；受访者回答长、占比大）：
{stats}

严格只输出如下 JSON（不要任何多余文字、不要 markdown 代码块）：
{{
  "speaker_roles": {{"采访者": "采访者", "受访者": "受访者"}},
  "summary": "",
  "summary_sections": [],
  "person_info": [
    {{"role": "采访者", "name": "", "school": "", "major": "", "grade": ""}},
    {{"role": "受访者", "name": "", "school": "", "major": "", "grade": ""}}
  ]
}}

标题：{title}

转录草稿：
{dialogue}
"""
    return prompt


def call_qwen(prompt, model, api_key, timeout=180):
    try:
        import dashscope
    except ImportError:
        print("❌ dashscope 未安装：pip install -U dashscope")
        sys.exit(1)
    dashscope.api_key = api_key
    try:
        resp = dashscope.Generation.call(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            result_format="message",
        )
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        sys.exit(1)
    # 兼容新旧 SDK：新版优先 resp.output.text，旧版 resp.output.choices[0].message.content
    if getattr(resp, "status_code", None) and resp.status_code != 200:
        print(f"❌ LLM 返回错误: HTTP {resp.status_code} {getattr(resp, 'output', '')}")
        sys.exit(1)
    out = getattr(resp, "output", None)
    if out is None:
        print("❌ LLM 返回为空。")
        sys.exit(1)
    if hasattr(out, "text") and out.text:
        return out.text
    try:
        return out.choices[0].message.content
    except Exception:
        print("❌ 无法解析 LLM 返回结构。")
        sys.exit(1)


def parse_json(text):
    """从 LLM 返回里抠出 JSON（容忍多余文字/代码块围栏）。"""
    import re
    text = text.strip()
    # 去掉 ```json ... ``` 围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    # 截取第一个 { 到最后一个 }
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        text = text[s:e + 1]
    try:
        return json.loads(text)
    except Exception as e:
        print(f"❌ JSON 解析失败: {e}\n原始返回前 500 字:\n{text[:500]}")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="FunASR 转录后的 LLM 说话人/摘要校正")
    ap.add_argument("transcript", help="transcript.json 路径")
    ap.add_argument("--output", default=None, help="corrections.json 输出路径（默认与 transcript 同目录）")
    ap.add_argument("--api-key", default=None, help="DashScope API Key（或环境变量 DASHSCOPE_API_KEY）")
    ap.add_argument("--model", default="qwen-plus", help="通义千问文本模型（默认 qwen-plus）")
    ap.add_argument("--title", default=None, help="文档标题（用于 prompt 上下文）")
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 未提供 API Key：用 --api-key 或环境变量 DASHSCOPE_API_KEY。")
        sys.exit(1)

    data, segs = load_segments(args.transcript)
    title = args.title or data.get("title", "采访转录")
    turns = build_labeled_turns(segs)
    if not turns:
        print("❌ 没有可校对的对话轮次。")
        sys.exit(1)
    print(f"  载入 {len(turns)} 个对话轮次，交给 LLM 校正说话人/摘要/人物信息…")

    prompt = build_prompt(title, turns)
    raw = call_qwen(prompt, args.model, api_key)
    corr = parse_json(raw)

    # 规整字段，确保 build_document --apply 能消费
    corr.setdefault("speaker_roles", {})
    corr.setdefault("summary", "")
    corr.setdefault("summary_sections", [])
    corr.setdefault("person_info", [])

    # 关键一致性修复：若 speaker_roles 做了标签交换（如 采访者↔受访者），
    # 必须同步把 person_info 每条的 role 键也做同样的交换，否则会出现
    # “学生信息挂在采访者头上、受访者信息为空”的错乱。
    sr = corr["speaker_roles"]
    if sr:
        for p in corr["person_info"]:
            old_role = p.get("role")
            if old_role in sr:
                p["role"] = sr[old_role]

    out_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.transcript)),
        "corrections.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(corr, f, ensure_ascii=False, indent=2)

    print(f"\n✅ corrections.json 已写出：{out_path}")
    print(f"   说话人角色: {corr['speaker_roles']}")
    if corr.get("summary"):
        print(f"   概述: {corr['summary'][:60]}{'…' if len(corr['summary']) > 60 else ''}")
    if corr.get("person_info"):
        for p in corr["person_info"]:
            print(f"   人物: {p.get('role','')} → {p.get('name','')} {p.get('school','')} {p.get('major','')} {p.get('grade','')}")
    print("\n下一步：")
    print(f"  python build_document.py \"{args.transcript}\" document.json --apply \"{out_path}\"")


if __name__ == "__main__":
    main()
