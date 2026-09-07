# -*- coding: utf-8 -*-
"""
快速档引擎：SenseVoice-Small q8（FunASR llama.cpp / GGUF 运行时，纯 CPU、零 Python ML 依赖）

读取 prepare.py 生成的 transcribe_config.json，逐段调用 llama-funasr-sensevoice.exe
（--srt 输出 VAD 级时间戳），解析 SRT → 句子级 segments（含绝对时间码），
过滤日文假名伪影（SenseVoice 在说话人切换/噪声处偶发误触发语种标签），
输出与 transcribe_local.py 同 schema 的 <标题>_transcript.json。

说话人说明：GGUF 运行时无说话人分离（CAM++ 未打包），所有句子 speaker=SPEAKER_00，
必须接 Step 3.5C 多说话人语义重切（resegment_speakers.py）做说话人识别。

用法:
  python transcribe_gguf.py --config transcribe_config.json \
      [--runtime-dir G:/llamacpp-asr/runtime] [--gguf-dir G:/llamacpp-asr/gguf] \
      [--backend cpu|cuda|vulkan]

运行时与模型缺失时的下载说明见脚本输出。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

# 日文假名（平/片假名+促音长音等）：SenseVoice 在中英混说/切换处偶发输出，中文采访里均为伪影
KANA_RE = re.compile(r"[\u3041-\u309F\u30A0-\u30FF\u31F0-\u31FF]+")
# 句子切分：保留句末标点
SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
MIN_SENT_CHARS = 2  # 过短句子（如只剩一个语气字）并入前句

DEFAULT_RUNTIME = r"G:\llamacpp-asr\runtime"
DEFAULT_GGUF = r"G:\llamacpp-asr\gguf"


def log(msg):
    print(msg, flush=True)


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    return p


def ffprobe_duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def to_wav(src, dst):
    """统一转 16k 单声道 wav（GGUF 运行时只稳定支持 wav）"""
    p = run(["ffmpeg", "-v", "error", "-y", "-i", src,
             "-ar", "16000", "-ac", "1", dst])
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 转 wav 失败: {p.stderr[:300]}")
    return dst


def parse_srt(text):
    """解析 SRT → [{start, end, text}]（秒）"""
    out = []
    block_re = re.compile(
        r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)\s*\n(.*?)(?=\n\s*\n|\Z)",
        re.S)
    for m in block_re.finditer(text):
        g = m.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
        body = g[8].strip().replace("\n", " ")
        if body:
            out.append({"start": start, "end": end, "text": body})
    return out


def clean_and_split(srt_items):
    """过滤假名伪影 → 按句末标点切句 → 合并过短句"""
    sents = []
    for it in srt_items:
        text = KANA_RE.sub("", it["text"]).strip()
        text = re.sub(r"^[，、。．\s]+", "", text)  # 清理切头标点残留
        if not text:
            continue
        for piece in SENT_SPLIT_RE.split(text):
            piece = piece.strip()
            if not piece:
                continue
            if sents and len(piece) < MIN_SENT_CHARS:
                sents[-1]["text"] += piece
                sents[-1]["end"] = it["end"]
            else:
                sents.append({"start": it["start"], "end": it["end"], "text": piece})
    return sents


def transcribe_segment(exe, model, vad, wav_path, backend):
    cmd = [exe, "-m", model, "-a", wav_path, "--srt", "--backend", backend]
    if vad:
        cmd += ["--vad", vad]
    p = run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f"GGUF 转录失败: {p.stderr[-400:]}")
    return parse_srt(p.stdout)


def generate_raw_text(merged):
    """与 transcribe_local.generate_raw_text 同格式：时间码 + SPEAKER 标签"""
    lines = []
    cur_spk, cur_start, buf = None, 0.0, []
    for it in merged:
        if it["speaker"] != cur_spk:
            if cur_spk is not None and buf:
                lines.append("[%06.1f] %s: %s" % (cur_start, cur_spk, "".join(buf)))
            cur_spk, cur_start, buf = it["speaker"], it["start"], []
        buf.append(it["text"])
    if cur_spk is not None and buf:
        lines.append("[%06.1f] %s: %s" % (cur_start, cur_spk, "".join(buf)))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="快速档：SenseVoice q8 GGUF 转录（纯 CPU 零依赖）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--runtime-dir", default=DEFAULT_RUNTIME)
    ap.add_argument("--gguf-dir", default=DEFAULT_GGUF)
    ap.add_argument("--backend", default="cpu", choices=["cpu", "cuda", "vulkan"])
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    out_dir = cfg.get("output_dir") or os.path.dirname(os.path.abspath(args.config))
    title = cfg.get("title", "转录")

    exe = os.path.join(args.runtime_dir, "llama-funasr-sensevoice.exe")
    model = os.path.join(args.gguf_dir, "sensevoice-small-q8.gguf")
    vad = os.path.join(args.gguf_dir, "fsmn-vad.gguf")
    missing = [p for p in (exe, model, vad) if not os.path.exists(p)]
    if missing:
        log("❌ GGUF 运行时/模型缺失: " + ", ".join(missing))
        log("   下载方法：")
        log("   1) 运行时: https://github.com/modelscope/FunASR/releases/download/"
            "runtime-llamacpp-v0.2.6/funasr-llamacpp-windows-x64-avx2.zip （解压即为 runtime 目录）")
        log("   2) 模型:   https://huggingface.co/FunAudioLLM/SenseVoiceSmall-GGUF/resolve/main/sensevoice-small-q8.gguf")
        log("            https://huggingface.co/FunAudioLLM/fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf")
        sys.exit(2)

    merged = []
    seg_files = cfg.get("segments") or [{"file": cfg.get("source_file"), "offset": 0}]
    total = len(seg_files)
    for i, seg in enumerate(seg_files, 1):
        seg_path = os.path.join(out_dir, seg["file"])
        if not os.path.exists(seg_path):
            seg_path = seg["file"]  # 兼容绝对路径
        offset = float(seg.get("offset", 0))
        dur = ffprobe_duration(seg_path) or 0
        wav = to_wav(seg_path, os.path.join(out_dir, f"_gguf_tmp_{i}.wav"))
        log(f"[{i}/{total}] {os.path.basename(seg_path)}（{dur:.0f}s）转录中…")
        srt_items = transcribe_segment(exe, model, vad, wav, args.backend)
        sents = clean_and_split(srt_items)
        for s in sents:
            merged.append({"speaker": "SPEAKER_00", "text": s["text"],
                           "start": s["start"] + offset, "end": s["end"] + offset})
        os.remove(wav)
        log(f"    ✅ {len(sents)} 句（VAD {len(srt_items)} 条）")

    from collections import Counter
    log("说话人分布（未经语义重切，全部为占位）: "
        + str(dict(Counter(s['speaker'] for s in merged))))
    log(f"总句数: {len(merged)}，总字数: {sum(len(s['text']) for s in merged)}")

    data = {
        "title": title,
        "source_file": cfg.get("source_file", ""),
        "frame_path": os.path.join(out_dir, cfg["frame_path"]) if cfg.get("frame_path") else None,
        "input_type": cfg.get("input_type", "audio"),
        "transcription_tool": "SenseVoice-Small q8（GGUF/llama.cpp 运行时 ~254MB，纯 CPU，零 Python 依赖）",
        "model": "local",
        "speaker_method": "无模型内分离（GGUF 运行时不打包 CAM++）→ 占位 SPEAKER_00，必须走 Step 3.5C LLM 语义重切",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "raw_text": generate_raw_text(merged),
        "segments": merged,
    }
    out_json = os.path.join(out_dir, f"{title}_transcript.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"✅ 已写出: {out_json}")


if __name__ == "__main__":
    main()
