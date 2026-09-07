# -*- coding: utf-8 -*-
"""
resegment_speakers.py — 多说话人语义重切（论坛式会议快速档专用）

背景：快速档 CAM++ 按 preset_spk_num=2 强制聚 2 类，但论坛式大会实际是
主持人串场 + 多位嘉宾 + 观众提问（>2 人），声纹聚类必然把多人并成 1 类。
本脚本不重转音频，直接对已有 transcript.json 的句子用 LLM 按语义重新
划分说话人（延续云端档 LLM 语义切分思路），输出 *_transcript.sem.json。

实测坑（2026-09-07 FDE大会，11 说话人全部分对）：
1. LLM 会批间自造编号（19/29/30）→ prompt 必须给编号白名单，
   非法编号回退为"上一说话人"（不臆断归并）；
2. 说话人上限按大会场景放宽到 20；
3. 批间带 12 句重叠上下文 + 全局编号表，保证跨批一致性。

用法：
  python resegment_speakers.py <标题>_transcript.json [--api-key <key>] \
      [--max-speakers 20] [--chunk-chars 6500]
# 输出 <标题>_transcript.sem.json + .meta.json（说话人描述与分布）
# 后续：build_document.py <sem.json> <document.json> --apply corrections.json
"""
import argparse, json, os, re, sys, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROMPT = """你是一名专业的会议转录整理员。下面是一场会议/论坛录音的逐句转录文本，多人发言（可能含主持人串场、多位嘉宾分享、观众提问）。原始声纹聚类错误地只聚了少数几类，现在需要你**按语义重新划分说话人**。

【已知信息】
- 目前已确认的说话人编号表：{known}
- 允许使用的编号白名单：{allowed_ids}。**只能使用白名单中的编号**：延续已出现的说话人用其已有编号；确认是新的人开始发言时，一律用 {next_id}（下一个未用编号）。**禁止输出白名单以外的任何数字编号**（不要自己另行计数）。
- 上一批结束时正在发言的说话人：{last_speaker}

【任务】
1. 从句子 {s0} 到句子 {s1}（正文部分），逐句判断说话人。延续上下文中已出现的说话人，或在新的人开始发言时用 {next_id} 新编号（最多不超过 {max_spk} 号）。
2. 判断依据：话题连贯性、问答关系（提问者/回答者）、主持人串场话术（如"接下来有请""感谢分享"之后换人）、称呼（如"安叔说一下"之后大概率是安叔发言）、观点立场一致性。
3. 注意：同一个人连续发言即使跨话题也不换编号；不要把主持人的串场词算到嘉宾头上。
4. 输出严格 JSON（不要 markdown 代码块）：
{{"speakers": {{"编号": "说话人描述（如：主持人/嘉宾A-讲ANC架构/观众提问者-培训行业）", ...本批涉及的编号}},
  "ranges": [{{"start": 起始句全局序号, "end": 结束句全局序号, "speaker": 编号}}, ...]}}

【上批末尾上下文（仅供参考衔接，仍需为正文重新判断，但要保持连续发言者的编号一致）】
{context}

【正文（需要划分的句子 {s0}-{s1}）】
{body}

只输出 JSON。"""

MAX_CHARS_DEFAULT = 6500
OVERLAP_SENTS = 12


def call_qwen(api_key, prompt, retries=3):
    import dashscope
    from dashscope import Generation
    dashscope.api_key = api_key
    for attempt in range(retries):
        try:
            resp = Generation.call(model="qwen-plus", prompt=prompt,
                                   temperature=0.1, top_p=0.8,
                                   max_tokens=4000, result_format="message")
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.message}")
            return resp.output.choices[0].message.content
        except Exception as e:
            print(f"  ⚠️ 调用失败({attempt+1}/{retries}): {e}", flush=True)
            if attempt == retries - 1:
                raise
            time.sleep(8)


def parse_json(txt):
    txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("no json object found")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", help="transcript.json（segments 含 text/speaker/start/end）")
    ap.add_argument("--api-key", default=os.environ.get("DASHSCOPE_API_KEY", ""))
    ap.add_argument("--max-speakers", type=int, default=20)
    ap.add_argument("--chunk-chars", type=int, default=MAX_CHARS_DEFAULT)
    ap.add_argument("--overlap", type=int, default=OVERLAP_SENTS)
    ap.add_argument("--output", default=None, help="输出路径，默认 <stem>.sem.json")
    args = ap.parse_args()
    if not args.api_key:
        print("FATAL: 未提供 --api-key 且环境变量 DASHSCOPE_API_KEY 为空", flush=True)
        sys.exit(1)

    t = json.load(open(args.transcript, encoding="utf-8"))
    segs = t["segments"]
    N = len(segs)
    print(f"载入 {N} 句（原始分布供参考：见脚本末尾对比）", flush=True)
    from collections import Counter
    print(f"原始声纹聚类分布: {dict(Counter(s.get('speaker','?') for s in segs))}", flush=True)

    # 切批
    chunks, i = [], 0
    while i < N:
        chars, j = 0, i
        while j < N and chars < args.chunk_chars:
            chars += len(segs[j].get("text", "")) + 6
            j += 1
        chunks.append((i, j - 1))
        i = j
    print(f"切分为 {len(chunks)} 批（每批 ≤{args.chunk_chars} 字符，重叠 {args.overlap} 句）", flush=True)

    assignment, known_ids = {}, {}
    last_speaker = "未知（这是第一批）"
    total_fallback = 0

    for ci, (s0, s1) in enumerate(chunks):
        ctx0 = max(0, s0 - args.overlap)
        context = "\n".join(f"{k}: {segs[k].get('text','')[:80]}" for k in range(ctx0, s0)) if s0 > 0 else "（无）"
        body = "\n".join(f"{k}: {segs[k].get('text','')}" for k in range(s0, s1 + 1))
        next_id = (max(known_ids.keys(), default=-1) + 1) if known_ids else 0
        allowed_ids = list(range(0, next_id + 1))
        known_str = json.dumps({str(k): v for k, v in sorted(known_ids.items())}, ensure_ascii=False) \
            if known_ids else "{}（暂无，本批从 0 开始编号）"
        prompt = PROMPT.format(
            known=known_str, allowed_ids=str(allowed_ids), next_id=next_id,
            max_spk=args.max_speakers - 1, last_speaker=last_speaker,
            s0=s0, s1=s1, context=context, body=body)
        print(f"--- 批 {ci+1}/{len(chunks)}: 句 {s0}-{s1}（{len(body)} 字符）---", flush=True)
        data = parse_json(call_qwen(args.api_key, prompt))
        prev_sp = assignment.get(s0 - 1, 0)
        covered, clamped = 0, 0
        for r in data.get("ranges", []):
            try:
                a, b, sp = int(r["start"]), int(r["end"]), int(r["speaker"])
            except Exception:
                print(f"  ⚠️ 跳过坏 range: {r}", flush=True)
                continue
            if sp not in allowed_ids or sp >= args.max_speakers:
                print(f"  ⚠️ 非法编号 {sp}（句 {a}-{b}）→ 回退说话人 {prev_sp}", flush=True)
                sp = prev_sp
                clamped += 1
            for k in range(max(a, s0), min(b, s1) + 1):
                assignment[k] = sp
                covered += 1
            prev_sp = sp
        missing = [k for k in range(s0, s1 + 1) if k not in assignment]
        if missing:
            prev = assignment.get(s0 - 1, 0)
            for k in missing:
                assignment[k] = prev
            print(f"  ⚠️ {len(missing)} 句未覆盖，沿用说话人 {prev}", flush=True)
        for k, v in data.get("speakers", {}).items():
            try:
                kid = int(k)
            except Exception:
                continue
            if kid in allowed_ids:
                known_ids.setdefault(kid, v)
        last_speaker = str(assignment[s1])
        total_fallback += clamped
        print(f"  ✅ 覆盖 {covered}/{s1-s0+1} 句（非法编号回退 {clamped} 处）；末句说话人={last_speaker}"
              f"({known_ids.get(assignment[s1], '?')})", flush=True)

    assert len(assignment) == N, f"覆盖 {len(assignment)}/{N}"
    cnt = Counter(assignment.values())
    print(f"重切完成。说话人分布: {dict(sorted(cnt.items()))}", flush=True)

    for idx, sp in assignment.items():
        segs[idx]["speaker"] = f"SPEAKER_{sp:02d}"
    t["metadata"] = t.get("metadata", {})
    t["metadata"]["speaker_method"] = "qwen-plus semantic re-segmentation (multi-speaker forum)"

    out = args.output or re.sub(r"\.json$", "", args.transcript) + ".sem.json"
    json.dump(t, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    meta = {"speaker_descriptions": {str(k): v for k, v in sorted(known_ids.items())},
            "distribution": {f"SPEAKER_{k:02d}": v for k, v in sorted(cnt.items())},
            "chunks": len(chunks), "invalid_fallbacks": total_fallback}
    json.dump(meta, open(out.replace(".json", ".meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"✅ 已写出: {out}", flush=True)
    print("说话人描述: " + json.dumps(meta["speaker_descriptions"], ensure_ascii=False), flush=True)
    print("下一步：build_document.py <sem.json> <document.json> --apply corrections.json"
          "（speaker_roles 按 meta 描述映射 说话人1/2/3 → 主持人/嘉宾/观众提问…）", flush=True)


if __name__ == "__main__":
    main()
