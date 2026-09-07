# -*- coding: utf-8 -*-
"""
refine_paragraphs.py — 快速档文本精修（标点修复 + 段落重排）

问题背景：FunASR Paraformer + ct-punc 的标点常错位（"因。为"）或缺标点，
长独白按 ~160 字机械切段导致胡乱换行。本脚本用 LLM 对 document.json 的
每个对话轮次做：①标点恢复/修正 ②按语义重排自然段 ③轻度精简语气词。
不改字词原意、不增删信息；单轮校验失败自动回退原文。

用法：
  python refine_paragraphs.py <document.json> [--api-key <key>] [--in-place]
  # 默认输出 <名>.refined.json；--in-place 直接覆盖（自动备份 .bak）

MOSS 精准档标点自然，通常无需本步；快速档强烈推荐。
"""
import argparse, json, os, re, sys, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_CHARS = 6000        # 每批轮次文本预算
LEN_MIN_RATIO = 0.5     # 精修后总长 < 原长 50% → 回退
LEN_MAX_RATIO = 1.25    # 精修后总长 > 原长 125% → 回退

PROMPT = """你是会议转录整理员。下面是一场会议/采访转录的若干对话轮次（JSON 数组，i=轮次编号，speaker=说话人，text=转录原文）。

原始文本来自 ASR，存在：标点错位（如"因。为"）、缺标点、一整段无换行的长独白。

对**每个轮次**执行：
1. 恢复/修正标点：错位标点归位，缺标点补上，保持句子通顺。
2. 按语义分段：长独白在话题转换处切成自然段，每段 2~5 句；短轮次不强行分段（1 段即可）。
3. 轻度精简明显冗余的语气词/填充词（嗯、啊、那个、就是、然后堆叠），只删不改。
4. **严禁**改写字词、增删信息、改动专有名词/数字；输出必须是原文的标点与分段优化版。

只输出 JSON 数组（不要 markdown 代码块）：
[{"i": 轮次编号, "paras": ["优化后的段1", "优化后的段2"]}, ...]
每个轮次都必须出现在输出里，paras 按原文顺序拼接后应与原文内容一致（仅标点/语气词差异）。

【待处理轮次】
"""


def fmt_ts(seconds: float) -> str:
    total = int(round(seconds))
    return f"[{total // 60:02d}:{total % 60:02d}]"


def call_qwen(api_key, prompt, retries=3):
    import dashscope
    from dashscope import Generation
    dashscope.api_key = api_key
    for attempt in range(retries):
        try:
            resp = Generation.call(model="qwen-plus", prompt=prompt,
                                   temperature=0.1, top_p=0.8,
                                   max_tokens=8000, result_format="message")
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
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        raise ValueError("no json array found")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("document", help="document.json 路径")
    ap.add_argument("--api-key", default=os.environ.get("DASHSCOPE_API_KEY", ""))
    ap.add_argument("--in-place", action="store_true", help="直接覆盖原文件（备份 .bak）")
    args = ap.parse_args()
    if not args.api_key:
        print("FATAL: 未提供 --api-key 且环境变量 DASHSCOPE_API_KEY 为空", flush=True)
        sys.exit(1)

    data = json.load(open(args.document, encoding="utf-8"))
    turns = data.get("conversation") or []
    print(f"载入 {len(turns)} 轮对话", flush=True)

    # 分批：按字符预算把轮次打包
    chunks, cur, cur_chars = [], [], 0
    for idx, t in enumerate(turns):
        n = len(t.get("text", "")) + 20
        if cur and cur_chars + n > MAX_CHARS:
            chunks.append(cur)
            cur, cur_chars = [], 0
        cur.append(idx)
        cur_chars += n
    if cur:
        chunks.append(cur)
    print(f"切分 {len(chunks)} 批", flush=True)

    refined_map = {}
    fallback = 0
    for ci, idxs in enumerate(chunks):
        payload = json.dumps(
            [{"i": i, "speaker": turns[i].get("speaker", ""), "text": turns[i].get("text", "")} for i in idxs],
            ensure_ascii=False)
        print(f"--- 批 {ci+1}/{len(chunks)}（{len(idxs)} 轮 / {len(payload)} 字符）---", flush=True)
        raw = call_qwen(args.api_key, PROMPT + "\n" + payload)
        arr = parse_json(raw)
        got = 0
        for item in arr:
            try:
                i = int(item["i"])
            except Exception:
                continue
            if i not in idxs:
                continue
            paras = [p.strip() for p in item.get("paras", []) if p and p.strip()]
            if not paras:
                continue
            orig = turns[i].get("text", "")
            refined_len = sum(len(p) for p in paras)
            if refined_len < len(orig) * LEN_MIN_RATIO or refined_len > len(orig) * LEN_MAX_RATIO:
                print(f"  ⚠️ 轮 {i} 长度异常（{refined_len} vs {len(orig)}），回退原文", flush=True)
                fallback += 1
                continue
            refined_map[i] = paras
            got += 1
        print(f"  ✅ 精修 {got}/{len(idxs)} 轮", flush=True)

    # 回填：替换 text / paragraphs（时间码：首段用原轮时间，续段按字数占比线性插值）
    changed = 0
    for i, paras in refined_map.items():
        t = turns[i]
        start, end = float(t.get("start", 0)), float(t.get("end", 0))
        dur = max(end - start, 1.0)
        total_chars = sum(len(p) for p in paras) or 1
        acc = 0.0
        new_paras = []
        for k, p in enumerate(paras):
            if k == 0:
                ts = t.get("timestamp") or fmt_ts(start)
            else:
                ts = fmt_ts(start + dur * acc / total_chars)
            new_paras.append({"ts": ts, "text": p})
            acc += len(p)
        t["paragraphs"] = new_paras
        t["text"] = "".join(p["text"] for p in new_paras)
        changed += 1
    print(f"✅ 精修回填 {changed} 轮（回退 {fallback} 轮，未覆盖 {len(turns)-changed} 轮保持原文）", flush=True)

    out = args.document if args.in_place else re.sub(r"\.json$", "", args.document) + ".refined.json"
    if args.in_place:
        bak = args.document + ".bak"
        if not os.path.exists(bak):
            json.dump(data, open(bak, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"已备份原文件 → {bak}", flush=True)
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已写出: {out}", flush=True)


if __name__ == "__main__":
    main()
