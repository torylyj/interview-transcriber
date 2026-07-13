"""
build_document.py — 结构化文档组装器（Step 3.5/3.6/3.7 的本地标准实现）

输入：transcribe_local.py 产出的 `<标题>_transcript.json`
      （含 `segments`：每段 {speaker, text, start, end}，SenseVoice 默认整段一块，
        句间仅有语言标签 <|withitn|> 而非句分隔）
输出：`<标题>_document.json`（供 build_docx.py 直接渲染为 .docx）

为什么需要它（2026-07-13 复盘）：
  - 之前在临时脚本里手写切分，把 SenseVoice 的 <|withitn|> 当"段间分隔"切，
    导致段 1 整段丢失、段 3 丢失、时间码错乱。本脚本直接消费 transcript.json
    的结构化 segments，彻底绕开脆弱的文本正则切分。
  - 本地 SenseVoice 不返回逐句时间码（sentence_timestamp 对该模型不生效），
    故本脚本：① 按中文标点把每段切成句子；② 依各段偏移 + 时长（来自
    transcribe_config.json 的 segments 与音频文件）线性插值得到逐句时间码。
    （句级时间码为插值估算，非逐字对齐；段落级边界精确。）
  - 说话人分离：本地模型不区分说话人，统一标 SPEAKER_00。本脚本提供
    「启发式初分 + Agent 复核」两阶段：
      1) 默认按问句特征把明显提问/插话判为「采访者」，其余为「受访人」；
      2) 运行 --review 打印带时间码与建议角色的逐句清单，由 Agent（方式 A，
         无需 API Key）复核修正后写入最终 document.json 的 conversation[].speaker。

用法：
  # 1) 先看解析结果 + 建议角色，供 Agent 复核
  python build_document.py transcript.json --review

  # 2) 用启发式自动分角色并写出 document.json（summary/person_info 留空待 Agent 填）
  python build_document.py transcript.json document.json --config transcribe_config.json --auto-speakers

  # 3) 作为库被 Agent 调用：parse_sentences() / assign_roles() / assemble_document()
"""

import os
import re
import sys
import json
import argparse
import functools
import subprocess

# 所有 print 立即刷新，避免长耗时步骤输出被缓冲导致调用方误以为卡死
print = functools.partial(print, flush=True)


def fmt_ts(seconds: float) -> str:
    """秒数 → [MM:SS]"""
    total = int(round(seconds))
    mm = total // 60
    ss = total % 60
    return f"[{mm:02d}:{ss:02d}]"


# 清理 SenseVoice 输出的语言/情感/itn 等标签（如 <|zh|> <|withitn|> <|NEUTRAL|>）
_TAG_RE = re.compile(r"<\|[^|]+\|>")


def clean_text(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


# 按中文/英文句末标点切句，保留标点
_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


def split_sentences(text: str) -> list:
    parts = _SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def seg_duration(file_path: str) -> float:
    """用 ffprobe 取音频时长（秒），失败返回 0。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 0)
    except Exception:
        return 0.0


def load_config(path: str) -> list:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("segments", []) or []
    except Exception:
        return []


def parse_sentences(data: dict, config_segs: list = None) -> list:
    """从 transcript.json 提取逐句列表（含插值时间码）。

    逻辑：
      - 遍历 data["segments"]（每段一块连续文本，顺序与 config.segments 一致）
      - 去掉语言标签，按标点切句
      - 该段 [offset, offset+duration] 内，按各句字符占比线性插值分配时间码
    """
    segs = data.get("segments")
    if not segs:
        # 回退：解析 raw_text
        return _parse_raw(data.get("raw_text", ""))

    sentences = []
    idx = 0
    for i, s in enumerate(segs):
        text = clean_text(s.get("text", ""))
        if not text:
            continue
        # 该段偏移与时长
        offset = 0.0
        duration = 0.0
        if config_segs and i < len(config_segs):
            c = config_segs[i]
            offset = float(c.get("offset", 0) or 0)
            fpath = c.get("file", "")
            duration = seg_duration(fpath) if fpath else 0.0
        parts = split_sentences(text)
        n = len(parts)
        for j, p in enumerate(parts):
            if not p:
                continue
            start = offset + duration * (j / n) if duration else offset
            end = offset + duration * ((j + 1) / n) if duration else offset
            sentences.append({
                "idx": idx,
                "start": round(start, 1),
                "end": round(end, 1),
                "text": p,
            })
            idx += 1
    return sentences


def _parse_raw(raw: str) -> list:
    parts = raw.split("<|withitn|>")
    out = []
    for p in parts:
        p = clean_text(p)
        # 去掉开头的 [MM:SS] **SPEAKER_00** 前缀
        if "**" in p:
            p = p.split("**", 2)[-1].strip()
        if p:
            for s in split_sentences(p):
                out.append({"idx": len(out), "start": 0.0, "end": 0.0, "text": s})
    return out


# ── 说话人角色判定（启发式，初分用） ─────────────────────
# 采访者典型特征：提问 / 短促插话。命中任一即判为采访者。
_INTERVIEWER_MARKS = [
    "吗", "呢", "怎么", "怎样", "为什么", "啥", "什么", "哪个", "哪些",
    "哪里", "多少", "几", "是不是", "对吧", "对不对", "是吗", "可以吗",
    "你说", "你觉得", "你认为", "你觉不", "能讲讲", "聊聊", "说说看",
    "ok", "okay", "嗯嗯", "好的", "好", "行",
]


def is_interviewer(text: str) -> bool:
    """启发式判断一句是否为采访者（提问/插话）。"""
    t = text.strip().rstrip("。，,. ")
    if not t:
        return False
    if t.endswith(("？", "?", "？", "？")):  # 问号结尾 → 强提问信号
        return True
    low = t.lower()
    for m in _INTERVIEWER_MARKS:
        if m in low:
            return True
    if len(t) <= 8 and not t.endswith(("。", "，", ".", ",")):  # 极短句多为插话/应答
        return True
    return False


def assign_roles(sentences: list, predicate=is_interviewer) -> list:
    """为每句打上建议角色（采访者 / 受访人）。"""
    out = []
    for s in sentences:
        role = "采访者" if predicate(s["text"]) else "受访人"
        out.append({**s, "role": role})
    return out


def split_paragraphs(sents: list) -> list:
    """将一轮内的多条句子按长度/句数切成多个段落，每段带首句时间码。

    长独白（如受访人一口气讲 1000+ 字）若整块输出极难阅读，
    故累积到 ~160 字或 4 句即切一段，提升可读性。
    """
    paras = []
    buf = []
    for s in sents:
        buf.append(s)
        total = sum(len(x["text"]) for x in buf)
        if total >= 160 or len(buf) >= 4:
            paras.append(buf)
            buf = []
    if buf:
        paras.append(buf)
    out = []
    for p in paras:
        out.append({
            "ts": fmt_ts(p[0]["start"]),
            "text": "".join(x["text"] for x in p),
        })
    return out


def _finalize_turn(cur: dict) -> dict:
    sents = cur["_sents"]
    paras = split_paragraphs(sents)
    full = "".join(x["text"] for x in sents)
    return {
        "speaker": cur["speaker"],
        "start": cur["start"],
        "end": cur["end"],
        "timestamp": paras[0]["ts"] if paras else fmt_ts(cur["start"]),
        "text": full,
        "paragraphs": paras,
    }


def group_turns(role_sentences: list) -> list:
    """将连续同角色的句子合并为一个 turn；长 turn 自动切成多段（每段带时间码）。

    返回的 turn 结构：
      {"speaker", "start", "end", "timestamp", "text", "paragraphs": [{"ts","text"}, ...]}
    `text` 保留全量文本以兼容旧渲染；`paragraphs` 为按段展示用。
    """
    turns = []
    cur = None
    for s in role_sentences:
        if cur and cur["speaker"] == s["role"]:
            cur["_sents"].append(s)
            cur["end"] = s["end"]
        else:
            if cur:
                turns.append(_finalize_turn(cur))
            cur = {"speaker": s["role"], "_sents": [s], "start": s["start"], "end": s["end"]}
    if cur:
        turns.append(_finalize_turn(cur))
    return turns


def assemble_document(
    transcript_data: dict,
    conversation: list,
    summary: str = "",
    person_info: list = None,
    speaker_method: str = "LLM 语义分析（Agent 方式 A，启发式初分 + 复核）",
    summary_method: str = "LLM 生成（Agent 方式 A）",
) -> dict:
    """组装最终 document.json。字段严格对齐 build_docx.py 渲染 schema。"""
    return {
        "title": transcript_data.get("title", "转录文档"),
        "frame_path": transcript_data.get("frame_path"),
        "input_type": transcript_data.get("input_type", "video"),
        "source_file": transcript_data.get("source_file", ""),
        "transcription_tool": transcript_data.get("transcription_tool", ""),
        "speaker_method": speaker_method,
        "summary_method": summary_method,
        "date": transcript_data.get("date", ""),
        "summary": summary,
        "person_info": person_info if person_info is not None else [],
        "conversation": conversation,
    }


def main():
    parser = argparse.ArgumentParser(description="transcript.json → document.json 标准组装器")
    parser.add_argument("transcript", help="输入 transcript.json 路径")
    parser.add_argument("output", nargs="?", default=None, help="输出 document.json 路径（--review 时可省略）")
    parser.add_argument("--config", default=None, help="transcribe_config.json（提供各段偏移+音频文件以插值时间码）")
    parser.add_argument("--review", action="store_true", help="只打印逐句解析 + 建议角色，不写文件")
    parser.add_argument("--auto-speakers", action="store_true",
                        help="用启发式自动分角色并写出 document.json（summary/person_info 留空待填）")
    args = parser.parse_args()

    with open(args.transcript, "r", encoding="utf-8") as f:
        data = json.load(f)
    config_segs = load_config(args.config)
    sentences = parse_sentences(data, config_segs)
    print(f"解析到 {len(sentences)} 个句子（逐句时间码为插值估算）")

    if args.review or not args.output:
        print("\n=== 逐句解析 + 建议角色（供 Agent 复核） ===")
        for s in sentences:
            ts = fmt_ts(s["start"])
            sug = "采访者" if is_interviewer(s["text"]) else "受访人"
            print(f"{ts} [{sug}] {s['text']}")
        if args.review:
            return

    if args.auto_speakers and args.output:
        role_sentences = assign_roles(sentences)
        conversation = group_turns(role_sentences)
        doc = assemble_document(data, conversation)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\n⚠️ document.json 已写出（启发式初分角色，summary/person_info 待 Agent 填）: {args.output}")
        print(f"   共 {len(conversation)} 个对话轮次")
        print("   ⚠️ 警告：启发式初分严重失真（实测把受访人独白里的'好/哪里'误判为采访者 20+ 处），")
        print("      此输出【不可直接作为最终交付】！必须运行 --review 经 LLM 语义复核修正 conversation[].speaker 后再定稿。")
        return

    print("用法：")
    print("  python build_document.py transcript.json --review            # 复核逐句")
    print("  python build_document.py transcript.json out.json --config transcribe_config.json --auto-speakers")


if __name__ == "__main__":
    main()
