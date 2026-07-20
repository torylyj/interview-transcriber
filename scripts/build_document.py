"""
build_document.py — 结构化文档组装器（Step 3.5/3.6/3.7 的本地标准实现）

输入：transcribe_local.py 产出的 `<标题>_transcript.json`
      （含 `segments`：Paraformer + CAM++ 已产出「每句一个片段」，
        自带真实 speaker（SPEAKER_XX，按声纹聚类）/ start / end；
        SenseVoice 则返回整段一块、start/end 均为 0，需插值估算）
输出：`<标题>_document.json`（供 build_docx.py 直接渲染为 .docx）

为什么需要它（2026-07-13 复盘）：
  - 之前在临时脚本里手写切分，把 SenseVoice 的 <|withitn|> 当"段间分隔"切，
    导致段 1 整段丢失、段 3 丢失、时间码错乱。本脚本直接消费 transcript.json
    的结构化 segments，彻底绕开脆弱的文本正则切分。
      - 时间码处理分两路：
          ① Paraformer-VAD 路径：transcript.json 的 segments 已带真实句级
             start/end（来自 sentence_info），本脚本直接在其真实跨度内按从句占比
             插值，精确到句；
          ② SenseVoice 路径：sentence_timestamp 对该模型不生效，每段整块、
             start/end 均为 0，故按「各段 offset + 时长（ffprobe）」整段线性插值
             （段内为估算值，段落边界才精确，勿标「精确到秒」）。
      - 说话人分离：已由 Paraformer + CAM++ 在模型内完成（transcribe_local.py
    加载 spk_model，generate() 返回每句 speaker id 并自动聚类）。本脚本
    直接消费 segments 里真实的 speaker 字段，按说话人聚合为 turn；
    说话人命名：不做采访者/受访人这类角色判定，统一按「首次出现顺序」
    中性命名为 说话人1、说话人2、说话人3……（assign_speaker_labels）；
    如需真名/角色，再用 --apply corrections.json 的 speaker_roles 覆盖。

用法：
  # 1) 先看解析结果 + 说话人分布，供 Agent 复核命名
  python build_document.py transcript.json --review

  # 2) 自动按首次出现顺序统一命名为 说话人1/2/3……并写出 document.json（summary/person_info 留空待 Agent 填）
  python build_document.py transcript.json document.json --config transcribe_config.json --auto

  # 2.5) 如需把 说话人1/2 改成真名/角色，用 corrections.json 落盘最终 document.json：
  #      准备 corrections.json：{"speaker_roles": {"说话人1":"张三","说话人2":"李四"},
  #                                  "summary":"...", "summary_sections":[{"title":"…","content":"…"}, ...],
  #                                  "person_info":[...]}
  #      再应用（按 说话人N 映射名称，自动合并连续同名为 turn，写出 document.json）：
  python build_document.py transcript.json document.json --apply corrections.json

  # 3) 作为库被 Agent 调用：parse_sentences() / assign_speaker_labels() / assemble_document()
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
        speaker = s.get("speaker", "SPEAKER_00")
        seg_start = float(s.get("start", 0) or 0)
        seg_end = float(s.get("end", 0) or 0)
        if seg_end > seg_start:
            # 真实时间码（Paraformer + VAD + CAM++ 返回句级 sentence_info）：
            # 直接以该句真实跨度内按从句占比插值，精确到句。
            span_start, span_end = seg_start, seg_end
        else:
            # 无时间码（SenseVoice 整段一块，start/end 均为 0）：
            # 回退到「各段 offset + 音频时长（ffprobe）」整段线性插值。
            offset = 0.0
            duration = 0.0
            if config_segs and i < len(config_segs):
                c = config_segs[i]
                offset = float(c.get("offset", 0) or 0)
                fpath = c.get("file", "")
                duration = seg_duration(fpath) if fpath else 0.0
            span_start, span_end = offset, offset + duration
        parts = split_sentences(text)
        n = len(parts)
        if n == 0:
            continue
        for j, p in enumerate(parts):
            if not p:
                continue
            start = span_start + (span_end - span_start) * (j / n)
            end = span_start + (span_end - span_start) * ((j + 1) / n)
            sentences.append({
                "idx": idx,
                "start": round(start, 1),
                "end": round(end, 1),
                "speaker": speaker,
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


# ── 角色命名（轻量，分离已由 CAM++ 完成） ─────────────────────
# CAM++ / 云端 LLM 只给出「谁在何时说」（SPEAKER_XX / 说话人标签），
# 这一步**不做**采访者/受访人这类角色判定，统一按「首次出现顺序」中性命名。
def assign_speaker_labels(sentences: list) -> dict:
    """按说话人首次出现顺序，统一命名为 说话人1/2/3……

    返回 {原始 speaker_id: "说话人N"}。与旧版「逐句启发式 / 采访者受访人判定」不同，
    这里只是中性顺序编号，不依赖提问特征，稳定且可预期。
    """
    order = []
    seen = set()
    for s in sentences:
        sp = s.get("speaker", "SPEAKER_00")
        if sp not in seen:
            seen.add(sp)
            order.append(sp)
    return {sp: f"说话人{idx + 1}" for idx, sp in enumerate(order)}

def apply_role_labels(turns: list, role_map: dict) -> list:
    """把 turn 的 speaker（SPEAKER_XX / 原始标签）按 role_map 重命名为 说话人N / 自定义名。"""
    for t in turns:
        t["speaker"] = role_map.get(t["speaker"], t["speaker"])
    return turns


def split_paragraphs(sents: list) -> list:
    """将一轮内的多条句子按长度/句数切成多个段落，每段带首句时间码。

    长独白（如某说话人一口气讲 1000+ 字）若整块输出极难阅读，
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


def group_turns(sentences: list) -> list:
    """将连续同说话人的句子合并为一个 turn；长 turn 自动切成多段（每段带时间码）。

    说话人已由 CAM++ 在模型内判定（SPEAKER_XX），此处仅按说话人聚合。
    返回的 turn 结构：
      {"speaker", "start", "end", "timestamp", "text", "paragraphs": [{"ts","text"}, ...]}
    `text` 保留全量文本以兼容旧渲染；`paragraphs` 为按段展示用。
    """
    turns = []
    cur = None
    for s in sentences:
        if cur and cur["speaker"] == s["speaker"]:
            cur["_sents"].append(s)
            cur["end"] = s["end"]
        else:
            if cur:
                turns.append(_finalize_turn(cur))
            cur = {"speaker": s["speaker"], "_sents": [s], "start": s["start"], "end": s["end"]}
    if cur:
        turns.append(_finalize_turn(cur))
    return turns


def assemble_document(
    transcript_data: dict,
    conversation: list,
    summary: str = "",
    summary_sections: list = None,
    person_info: list = None,
    speaker_method: str = "CAM++ 说话人嵌入（FunASR spk_model，按声纹自动聚类）",
    summary_method: str = "LLM 生成（Agent 方式 A）",
) -> dict:
    """组装最终 document.json。字段严格对齐 build_docx.py 渲染 schema。

    summary_sections: 分板块摘要列表，元素为 {"title": "...", "content": "..."}；
                     为 None/[] 时不渲染分板块章节（仅显示 summary 一句总结）。
    """
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
        "summary_sections": summary_sections if summary_sections is not None else [],
        "person_info": person_info if person_info is not None else [],
        "conversation": conversation,
    }


def main():
    parser = argparse.ArgumentParser(description="transcript.json → document.json 标准组装器")
    parser.add_argument("transcript", help="输入 transcript.json 路径")
    parser.add_argument("output", nargs="?", default=None, help="输出 document.json 路径（--review 时可省略）")
    parser.add_argument("--config", default=None, help="transcribe_config.json（提供各段偏移+音频文件以插值时间码）")
    parser.add_argument("--review", action="store_true", help="只打印逐句解析 + 说话人分布，不写文件")
    parser.add_argument("--auto", action="store_true",
                        help="自动按说话人聚合判定角色并写出 document.json（summary/person_info 留空待填）")
    parser.add_argument("--apply", default=None,
                        help="应用 corrections.json（{speaker_roles:{SPEAKER_XX:角色}, summary, summary_sections, person_info}）写出最终 document.json")
    args = parser.parse_args()

    with open(args.transcript, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Step 3.55 同音字校对：如存在 <input>.corrected.json（由 correct_homophones.py 产出），
    # 自动优先消费其中的 segments（仅替换 text，不动 speaker / start / end / metadata）
    corrected_path = os.path.splitext(args.transcript)[0] + ".corrected.json"
    if corrected_path != args.transcript and os.path.isfile(corrected_path):
        try:
            with open(corrected_path, "r", encoding="utf-8") as f:
                corrected = json.load(f)
            # 合并：保留原 transcript 的 metadata，仅替换 segments
            if corrected.get("segments"):
                old_segs = data.get("segments") or []
                new_segs = corrected["segments"]
                # 按 start/speaker 对齐，把 corrected 的 text 写回原 segments（保留所有时间码）
                # 若 corrected 长度与原不一致，降级为整段替换
                if len(new_segs) == len(old_segs):
                    for o, n in zip(old_segs, new_segs):
                        o["text"] = n.get("text", o["text"])
                    print(f"  已合并同音字校对结果：{corrected_path}（保留所有时间码/说话人标签）")
                else:
                    # 长度不一致（边界情况），整段替换 + 警告
                    data["segments"] = new_segs
                    data["raw_text"] = corrected.get("raw_text", data.get("raw_text", ""))
                    print(f"  ⚠️ 同音字校对版 segments 数量与原不一致（{len(new_segs)} vs {len(old_segs)}），已整段替换")
            if corrected.get("raw_text") and not corrected.get("segments"):
                data["raw_text"] = corrected["raw_text"]
        except Exception as e:
            print(f"  ⚠️ 读取 {corrected_path} 失败，回退用原 transcript：{e}")
    config_segs = load_config(args.config)
    sentences = parse_sentences(data, config_segs)
    print(f"解析到 {len(sentences)} 个句子（Paraformer+CAM++ 为真实说话人+句级时间码；SenseVoice 为整段插值）")

    # 说话人分布（CAM++ 已聚类）
    spk_counts = {}
    for s in sentences:
        spk_counts[s["speaker"]] = spk_counts.get(s["speaker"], 0) + 1
    print(f"说话人分布（模型聚类）: {spk_counts}")

    # ── Step 3.55 同音字校对（--apply 路径内联）──
    # 若 corrections.json 含 homophone_corrections，按 context 精确替换 sentence.text
    # 优先级：① corrected.json（已合并到 data.segments）② corrections.json 内联
    if args.apply and args.output:
        try:
            with open(args.apply, "r", encoding="utf-8") as f:
                _corr_inline = json.load(f)
        except Exception:
            _corr_inline = {}
        hc = (_corr_inline.get("homophone_corrections", []) or []) if isinstance(_corr_inline, dict) else []
        if hc:
            n_applied = 0
            for c in hc:
                orig = c.get("original", "")
                corr = c.get("corrected", "")
                ctx = c.get("context", "")
                if not orig or not corr or orig == corr or not ctx:
                    continue
                # 在所有句子中找到含 ctx 的那一处，替换其中的 orig
                for s in sentences:
                    if ctx in s["text"]:
                        s["text"] = s["text"].replace(ctx, ctx.replace(orig, corr, 1), 1)
                        n_applied += 1
                        break
            if n_applied:
                print(f"  ✓ --apply 内联同音字校对：应用 {n_applied} 处")

    if args.review or not args.output:
        print("\n=== 逐句解析（供 Agent 复核角色命名） ===")
        for s in sentences:
            ts = fmt_ts(s["start"])
            print(f"{ts} [{s['speaker']}] {s['text']}")
        if args.review:
            return

    label_map = assign_speaker_labels(sentences)
    turns = apply_role_labels(group_turns(sentences), label_map)

    if args.apply and args.output:
        try:
            with open(args.apply, "r", encoding="utf-8") as f:
                corr = json.load(f)
        except Exception as e:
            print(f"❌ 读取 corrections.json 失败：{e}")
            sys.exit(1)
        override = corr.get("speaker_roles", {}) or {}
        if override:
            for t in turns:
                t["speaker"] = override.get(t["speaker"], t["speaker"])
        summary = corr.get("summary", "") if isinstance(corr, dict) else ""
        summary_sections = corr.get("summary_sections", []) or [] if isinstance(corr, dict) else []
        person_info = corr.get("person_info", []) or [] if isinstance(corr, dict) else []
        doc = assemble_document(
            data, turns,
            summary=summary,
            summary_sections=summary_sections,
            person_info=person_info,
        )
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 最终 document.json 已写出：{args.output}")
        print(f"   说话人命名: {label_map}")
        if override:
            print(f"   自定义覆盖: {override}")
        if hc:
            print(f"   同音字校对: {len(hc)} 条 corrections（已应用 {n_applied} 处）")
        print(f"   共 {len(turns)} 个对话轮次；summary/summary_sections/person_info 已填入（无则空）")
        return

    if args.auto and args.output:
        doc = assemble_document(data, turns)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\n✅ document.json 已写出（统一说话人命名，summary/summary_sections/person_info 待 Agent 填）: {args.output}")
        print(f"   说话人命名: {label_map}")
        print(f"   共 {len(turns)} 个对话轮次")
        print("   ⚠️ 若需把 说话人1/2 改成真名/角色，用 --apply corrections.json 覆盖 speaker_roles（键为 说话人1/2/3）即可。")
        print("   ⚠️ 同时可在 corrections.json 加 summary_sections: [{title, content}, ...] 填分板块摘要。")
        return

    print("用法：")
    print("  python build_document.py transcript.json --review            # 复核逐句")
    print("  python build_document.py transcript.json out.json --config transcribe_config.json --auto     # 自动命名角色")
    print("  python build_document.py transcript.json out.json --apply corrections.json   # 覆盖命名+填 summary/summary_sections/person_info")


if __name__ == "__main__":
    main()
