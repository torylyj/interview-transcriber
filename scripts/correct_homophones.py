"""
correct_homophones.py — LLM 后处理同音字校对（Step 3.55）

输入：<标题>_transcript.json（来自 transcribe_local.py / transcribe_qwen.py）
输出：<标题>_transcript.corrected.json（同结构，仅替换 segments[].text 中的同音字）

为什么需要它：
  中文 ASR 模型（Paraformer / SenseVoice / Qwen3-ASR-Flash）会按读音识别，
  经常出现同音字错误，如：
    - 在 ↔ 再（再 = 表重复动作；在 = 表位置/存在）
    - 做 ↔ 作（动词 vs 助词/名词）
    - 的 ↔ 得 ↔ 地（修饰 vs 补语 vs 状语）
    - 了 ↔ 啦 ↔ 咯（语气词易混）
    - 记 ↔ 纪 ↔ 计（如 记忆/记忆/记忆）
    - 系 ↔ 戏 ↔ 细
    - 辩 ↔ 辨 ↔ 辫
    - 帐 ↔ 账
    - 复 ↔ 覆
    - 像 ↔ 象
    - 报 ↔ 抱
    - 数字/人名/专名（同音替换）
  LLM 按上下文批量识别并替换，能显著提高最终 .docx 的稳定性与可读性。

两种调用方式（与本 skill 的 Step 3.5 / 3.6 一致）：
  · 方式 A（推荐）：Agent 自身即 LLM，按 references/prompts.md 的「Step 3.55 同音字校对」
    prompt 在对话中执行；把返回的 JSON corrections 落到 corrections.json，再用本脚本
    --apply-corrections 应用。
  · 方式 B：直接调用 qwen-plus 生成 corrections，应用到 transcript 后写出 corrected 版本。

用法:
  # 方式 A：打印 prompt 给 Agent（Agent 自己生成 corrections 后 --apply-corrections）
  python correct_homophones.py <transcript.json> --print-prompt

  # 方式 A：Agent 已生成 corrections.json，应用到 transcript 并写出 corrected 版本
  python correct_homophones.py <transcript.json> --apply-corrections corrections.json

  # 方式 B：直接调 qwen-plus 生成并应用 corrections（一次性）
  python correct_homophones.py <transcript.json> --call-qwen --model qwen-plus \\
      [--output <标题>_transcript.corrected.json]
"""

import os
import re
import sys
import json
import argparse
import functools
import subprocess

print = functools.partial(print, flush=True)


def load_transcript(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_prompt(transcript: dict) -> str:
    """构造 LLM 校对 prompt（与 references/prompts.md § Step 3.55 同步维护）。"""
    segs = transcript.get("segments") or []
    if not segs:
        # 回退：直接用 raw_text
        full_text = transcript.get("raw_text", "")
    else:
        lines = []
        for i, s in enumerate(segs):
            speaker = s.get("speaker", "?")
            text = (s.get("text") or "").strip()
            lines.append(f"[{i}] [{speaker}] {text}")
        full_text = "\n".join(lines)
    title = transcript.get("title", "未知标题")
    return f"""你是中文转录校对员。以下是一段音视频（标题：{title}）的转录文本（已按说话人分段，时间顺序）。
转录模型（Paraformer-large / SenseVoice / Qwen3-ASR-Flash 等）按读音识别，容易把同音字搞混。
请按上下文识别并列出**有明确证据**需要替换的同音字，按要求输出 JSON。

# 重点关注的同音字对
- 在 ↔ 再（再 = 表重复动作；在 = 表位置/存在）
- 做 ↔ 作（动词 vs 助词/名词）
- 的 ↔ 得 ↔ 地（修饰 vs 补语 vs 状语）
- 了 ↔ 啦 ↔ 咯（语气词易混，按上下文语气判断）
- 记 ↔ 纪 ↔ 计（如 记忆/记忆/记忆）
- 系 ↔ 戏 ↔ 细
- 辩 ↔ 辨 ↔ 辫
- 帐 ↔ 账
- 复 ↔ 覆
- 像 ↔ 象
- 报 ↔ 抱
- 数字/人名/专名的同音替换（如 "五四" 误识为 "无事"、"李四" 误识为 "李似"）

# 输出格式（严格 JSON，无多余说明）
{{
  "homophone_corrections": [
    {{
      "original": "原词（转录结果）",
      "corrected": "应改成的词",
      "context": "包含 original 的完整片段（用于精确匹配替换，5-30 字）",
      "reason": "为什么要改（一句话即可，如「上下文是重复动作，应为『再』」）"
    }}
  ]
}}

# 严格要求
1. 只列**有明确证据**要改的，宁缺毋滥；拿不准的不要列
2. context 必须是包含 original 的完整片段（便于精确替换，避免误伤相同词）
3. 同一原文在多处出现错误，可分多条
4. 短语气词（啊/嗯/哦）误识别可忽略，不属于同音字错误
5. 数字/人名/专名按同音字处理（但要先核对上下文是否合理）
6. 不要改标点；不要改段落结构；不要做语序调整
7. 没有任何同音字错误时，输出 {{"homophone_corrections": []}}

# 转录文本（按时间顺序，每行一条；[N] 是段索引，[speaker] 是说话人）
{full_text}

仅输出 JSON："""


def parse_llm_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON（容忍 ```json 围栏、前后多余文字）。"""
    text = text.strip()
    # 去掉 ```json ... ``` 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    # 尝试直接 parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 退化：找第一个 { 到最后一个 }
    s = text.find("{")
    e = text.rfind("}")
    if s >= 0 and e > s:
        return json.loads(text[s:e + 1])
    raise json.JSONDecodeError("未找到 JSON", text, 0)


def apply_corrections(transcript: dict, corrections: list, verbose: bool = True) -> dict:
    """按 corrections[].context 精确替换 transcript.segments[].text 中的同音字。

    替换策略：
      · 在 text 中找 context；若 context 内含 original，则把 context 内那处 original
        换成 corrected；其他位置不动（避免误伤）。
      · 若 context 不在 text 中：跳过并在 stderr 提示（防止全句误替换）。
    """
    segs = transcript.get("segments") or []
    raw_text = transcript.get("raw_text", "")
    n_applied = 0
    n_skipped = 0
    skipped_details = []

    for c in corrections or []:
        orig = c.get("original", "")
        corr = c.get("corrected", "")
        ctx = c.get("context", "")
        if not orig or not corr or orig == corr:
            continue
        if not ctx:
            # 没有 context 跳过（不做全段替换，避免误伤）
            n_skipped += 1
            skipped_details.append({"original": orig, "corrected": corr, "reason": "无 context"})
            continue
        # 在所有 segments 中尝试替换
        replaced = False
        for seg in segs:
            text = seg.get("text", "")
            if not text:
                continue
            idx = text.find(ctx)
            if idx < 0:
                continue
            new_ctx = ctx.replace(orig, corr)
            # 兜底：只替换 ctx 内的 orig 一次（避免重复字被全替换）
            new_text = text[:idx] + new_ctx + text[idx + len(ctx):]
            seg["text"] = new_text
            n_applied += 1
            replaced = True
            if verbose:
                print(f"  ✓ 第{n_applied}处:「{orig}」→「{corr}」（context: {ctx[:24]}…）")
            break
        if not replaced:
            # 在 raw_text 试试（部分转录无 segments）
            if raw_text and ctx in raw_text:
                new_ctx = ctx.replace(orig, corr)
                transcript["raw_text"] = raw_text.replace(ctx, new_ctx, 1)
                n_applied += 1
                if verbose:
                    print(f"  ✓ 第{n_applied}处:「{orig}」→「{corr}」（raw_text）")
            else:
                n_skipped += 1
                skipped_details.append({"original": orig, "corrected": corr, "context": ctx, "reason": "context 不在任何段中"})

    if verbose:
        print(f"  共应用 {n_applied} 处，跳过 {n_skipped} 处")
        if skipped_details:
            print("  ⚠️ 跳过的 corrections（context 不匹配，可能 LLM 幻觉）：")
            for d in skipped_details[:5]:
                print(f"    - {d}")
            if len(skipped_details) > 5:
                print(f"    ... 及另外 {len(skipped_details) - 5} 条")

    return transcript


def call_qwen(prompt: str, model: str) -> str:
    """方式 B：调 qwen-plus。优先用 call_qwen.py 子进程（行为一致），失败回退 dashscope 直调。"""
    # 尝试子进程调用 call_qwen.py
    here = os.path.dirname(os.path.abspath(__file__))
    call_qwen_path = os.path.join(here, "call_qwen.py")
    if os.path.isfile(call_qwen_path):
        try:
            out = subprocess.run(
                [sys.executable, call_qwen_path, "--model", model, "--prompt", prompt],
                capture_output=True, text=True, timeout=300,
            )
            if out.returncode == 0:
                return out.stdout.strip()
            print(f"⚠️ call_qwen.py 子进程失败，回退 dashscope 直调: {out.stderr.strip()[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ call_qwen.py 子进程异常，回退 dashscope 直调: {e}", file=sys.stderr)
    # 回退：dashscope 直调
    try:
        import dashscope
        from dashscope import Generation
    except ImportError:
        print("错误: dashscope 未安装。请先执行: pip install dashscope", file=sys.stderr)
        sys.exit(1)
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("错误: DASHSCOPE_API_KEY 未设置", file=sys.stderr)
        sys.exit(1)
    dashscope.api_key = api_key
    resp = Generation.call(model=model, messages=[{"role": "user", "content": prompt}], result_format="message")
    if resp.status_code == 200:
        return resp.output.choices[0].message.content.strip()
    print(f"错误: HTTP {resp.status_code} {resp.output}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="LLM 后处理同音字校对（Step 3.55）：生成/应用 corrections，写出 transcript.corrected.json"
    )
    parser.add_argument("transcript", help="输入 transcript.json 路径")
    parser.add_argument("--print-prompt", action="store_true",
                        help="仅打印 prompt（方式 A：让 Agent 自己执行 LLM 调用）")
    parser.add_argument("--apply-corrections", metavar="CORRECTIONS_JSON", default=None,
                        help="应用已有的 corrections.json（含 homophone_corrections 数组）写出 corrected transcript")
    parser.add_argument("--call-qwen", action="store_true",
                        help="直接调用 qwen-plus（方式 B）生成 corrections 并应用")
    parser.add_argument("--model", default="qwen-plus",
                        help="方式 B 调用的模型（默认 qwen-plus）")
    parser.add_argument("--output", default=None,
                        help="输出 corrected transcript 路径（默认 <input>.corrected.json）")
    args = parser.parse_args()

    transcript = load_transcript(args.transcript)
    n_segs = len(transcript.get("segments") or [])
    print(f"加载 transcript: {args.transcript}（{n_segs} 个 segments）")

    # ── 模式 1：仅打印 prompt ──
    if args.print_prompt:
        print("\n" + "=" * 60)
        print("同音字校对 prompt（方式 A：请复制到对话窗口让 Agent 执行 LLM 调用）")
        print("=" * 60 + "\n")
        print(build_prompt(transcript))
        print("\n" + "=" * 60)
        print("Agent 执行后将返回 JSON（含 homophone_corrections 数组）")
        print("请把 JSON 保存为 corrections.json，然后执行：")
        print(f"  python {os.path.basename(sys.argv[0])} {args.transcript} --apply-corrections corrections.json")
        print("=" * 60)
        return

    # ── 模式 2：应用已有 corrections ──
    if args.apply_corrections:
        try:
            with open(args.apply_corrections, "r", encoding="utf-8") as f:
                corr_obj = json.load(f)
        except Exception as e:
            print(f"❌ 读取 corrections.json 失败：{e}", file=sys.stderr)
            sys.exit(1)
        corrections = corr_obj.get("homophone_corrections", []) or []
        print(f"从 {args.apply_corrections} 加载 {len(corrections)} 条 corrections")
        corrected = apply_corrections(transcript, corrections)
        out_path = args.output or (os.path.splitext(args.transcript)[0] + ".corrected.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(corrected, f, ensure_ascii=False, indent=2)
        print(f"✅ 已写出 corrected transcript：{out_path}")
        return

    # ── 模式 3：直接调 qwen-plus 生成并应用 ──
    if args.call_qwen:
        prompt = build_prompt(transcript)
        print(f"调 {args.model} 生成 corrections（方式 B）...")
        out_text = call_qwen(prompt, args.model)
        try:
            corr_obj = parse_llm_json(out_text)
        except json.JSONDecodeError as e:
            print(f"❌ LLM 返回非 JSON：{e}\n原始输出：\n{out_text[:500]}", file=sys.stderr)
            sys.exit(1)
        corrections = corr_obj.get("homophone_corrections", []) or []
        print(f"LLM 返回 {len(corrections)} 条 corrections")
        if not corrections:
            print("  LLM 未发现任何同音字错误；如需复查，可改用方式 A 自行核对")
        corrected = apply_corrections(transcript, corrections)
        out_path = args.output or (os.path.splitext(args.transcript)[0] + ".corrected.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(corrected, f, ensure_ascii=False, indent=2)
        # 同时把 LLM 返回的 corrections 也落盘，方便审计/回退
        corr_out = (args.output or os.path.splitext(args.transcript)[0]) + ".corrections.json"
        # 但 .corrected.json 已经被 output 占用，改用 _homophone_corrections.json
        corr_out = os.path.splitext(out_path)[0].replace(".corrected", "") + "_homophone_corrections.json"
        with open(corr_out, "w", encoding="utf-8") as f:
            json.dump(corr_obj, f, ensure_ascii=False, indent=2)
        print(f"✅ 已写出 corrected transcript：{out_path}")
        print(f"   同音字 corrections 备份：{corr_out}")
        return

    # 未指定模式
    print("用法：")
    print(f"  python {os.path.basename(sys.argv[0])} <transcript.json> --print-prompt     # 方式 A：打印 prompt")
    print(f"  python {os.path.basename(sys.argv[0])} <transcript.json> --apply-corrections corrections.json   # 方式 A 应用")
    print(f"  python {os.path.basename(sys.argv[0])} <transcript.json> --call-qwen       # 方式 B：直接调 qwen-plus")
    sys.exit(1)


if __name__ == "__main__":
    main()