#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare.py — 采访转录前置配置生成器（减少手动胶水）

输入：一个视频/音频文件（或同采访拆成的多段文件）
输出：transcribe_config.json（供 transcribe_local.py / transcribe_qwen.py 直接读取）

自动完成：
  1. 识别输入类型（视频 / 音频）
  2. 视频：抽取最清晰静帧 + 转 16k 单声道 MP3；音频：重采样为 16k 单声道 MP3
  3. 多段同采访：先各自转 MP3，再 ffmpeg concat 合并为统一 输出.mp3
  4. ffprobe 取总时长，按所选模型能力自动切段
     - 云端 Qwen3-ASR-Flash：>5 分钟必切（4 分钟/段）
     - 本地 SenseVoice/Paraformer：>20 分钟建议切（4 分钟/段）
  5. 生成标题（文件夹/文件名 YY-MMDD + 人物简介占位；Agent 可后续改）
  6. 写出 transcribe_config.json

用法：
  python prepare.py "H:/街头采访/清华26-0713/视频.mp4"
  python prepare.py "a.mp4" "b.mp4" --title "26-0713 清华访谈" --mode local
  python prepare.py "长视频.mp4" --mode cloud --output-dir ./_work
"""

import os
import sys
import json
import argparse
import subprocess

print = __import__("functools").partial(print, flush=True)

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}


def run(cmd):
    """运行命令并打印，返回 (returncode, stdout)。"""
    print("  $ " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                print("    " + line)
        if r.returncode != 0 and r.stderr.strip():
            for line in r.stderr.strip().splitlines()[-5:]:
                print("    ⚠️ " + line)
        return r.returncode, r.stdout
    except FileNotFoundError:
        print("    ❌ 找不到可执行文件，请确认 ffmpeg 已安装并在 PATH（或 tools/ffmpeg/bin）。")
        return 1, ""
    except Exception as e:  # noqa: BLE001
        print(f"    ❌ 命令执行异常：{e}")
        return 1, ""


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXT


def ffprobe_duration(path):
    code, out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    if code != 0:
        return None
    try:
        return float(out.strip() or 0)
    except ValueError:
        return None


def to_mp3(src, dst):
    """转码为 16k 单声道 192k MP3；dst 已存在则跳过。"""
    if os.path.exists(dst):
        print(f"  ✓ 已存在，跳过转码：{dst}")
        return 0
    return run([
        "ffmpeg", "-y", "-i", src,
        "-vn", "-acodec", "libmp3lame", "-ab", "192k",
        "-ar", "16000", "-ac", "1", dst,
    ])[0]


def extract_frame(skill_dir, inputs, out_jpg):
    """对视频输入抽最清晰静帧（多视频跨片段比选）。"""
    script = os.path.join(skill_dir, "scripts", "extract_frame.py")
    if not os.path.exists(script):
        print("  ⚠️ 未找到 extract_frame.py，跳过静帧。")
        return False
    args = [sys.executable, script] + list(inputs) + [out_jpg]
    code, _ = run(args)
    return code == 0 and os.path.exists(out_jpg)


def concat_mp3(mp3_list, dst):
    """用 ffmpeg concat 合并多个 MP3 为统一 16k 单声道文件。"""
    if len(mp3_list) == 1:
        if mp3_list[0] != dst:
            return run(["ffmpeg", "-y", "-i", mp3_list[0],
                       "-acodec", "libmp3lame", "-ab", "192k",
                       "-ar", "16000", "-ac", "1", dst])[0]
        return 0
    list_file = os.path.join(os.path.dirname(dst) or ".", "_merge_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for m in mp3_list:
            f.write(f"file '{m}'\n")
    code = run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
        "-vn", "-acodec", "libmp3lame", "-ab", "192k",
        "-ar", "16000", "-ac", "1", dst,
    ])[0]
    try:
        os.remove(list_file)
    except OSError:
        pass
    return code


def derive_title(files, override):
    if override:
        return override
    # 取第一个文件的文件夹名 / 文件名里的 YY-MMDD
    import re
    for f in files:
        base = os.path.basename(f)
        m = re.search(r"(\d{2})-?(\d{2})(\d{2})", base)
        if not m:
            m = re.search(r"(\d{2})-?(\d{2})(\d{2})", os.path.basename(os.path.dirname(f)))
        if m:
            return f"{m.group(1)}-{m.group(2)}{m.group(3)} 待定人物"
    return "采访转录 待定日期"


def decide_segments(merged_mp3, mode):
    """按所选模式决定切段；返回 segments 列表。"""
    dur = ffprobe_duration(merged_mp3)
    if dur is None:
        print("  ⚠️ 取不到总时长，保守按「长音频」切段（每 4 分钟一段）。")
        dur = 9999
    threshold = 300 if mode == "cloud" else 1200
    if dur <= threshold:
        return [{"file": os.path.basename(merged_mp3), "offset": 0}]
    # 切 4 分钟/段
    seg = 240
    n = max(1, int(dur // seg) + (1 if dur % seg else 0))
    segs = []
    for i in range(n):
        seg_file = os.path.join(os.path.dirname(merged_mp3) or ".", f"_seg{i+1}.mp3")
        offset = i * seg
        segs.append({"file": os.path.basename(seg_file), "offset": offset})
    # 真正切分
    for i, s in enumerate(segs):
        seg_file = os.path.join(os.path.dirname(merged_mp3) or ".", f"_seg{i+1}.mp3")
        run([
            "ffmpeg", "-y", "-i", merged_mp3,
            "-ss", str(i * seg), "-t", str(seg),
            "-acodec", "libmp3lame", "-ab", "192k",
            "-ar", "16000", "-ac", "1", seg_file,
        ])
    return segs


def main():
    ap = argparse.ArgumentParser(description="采访转录前置配置生成器")
    ap.add_argument("inputs", nargs="+", help="视频/音频文件（同采访可传多个）")
    ap.add_argument("--mode", default="local", choices=["local", "cloud"],
                   help="local=Paraformer-large（默认,高精度）；cloud=Qwen3-ASR-Flash")
    ap.add_argument("--model", default="paraformer", choices=["sensevoice", "paraformer"],
                   help="本地模型（仅 local 模式生效；默认 paraformer 高精度，可选 sensevoice 轻量）")
    ap.add_argument("--title", default=None, help="文档标题（默认从文件名推导）")
    ap.add_argument("--output-dir", default=None, help="输出目录（默认第一个文件所在目录）")
    a = ap.parse_args()

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = a.output_dir or os.path.dirname(os.path.abspath(a.inputs[0])) or "."
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 60)
    print("采访转录 · 前置配置生成")
    print("=" * 60)

    videos, audios = [], []
    for f in a.inputs:
        if not os.path.exists(f):
            print(f"❌ 文件不存在：{f}")
            sys.exit(1)
        (videos if is_video(f) else audios).append(f)

    # 1) 各自转 MP3
    mp3_list = []
    for f in a.inputs:
        dst = os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + ".mp3")
        if to_mp3(f, dst) != 0:
            print(f"❌ 转码失败：{f}")
            sys.exit(1)
        mp3_list.append(dst)

    # 2) 合并（多段同采访）
    merged = os.path.join(out_dir, "输出.mp3")
    if concat_mp3(mp3_list, merged) != 0:
        print("❌ 合并失败。")
        sys.exit(1)

    # 3) 静帧（仅含视频时）
    frame_path = None
    if videos:
        frame_path = os.path.join(out_dir, "人物静帧.jpg")
        if not extract_frame(skill_dir, videos, frame_path):
            print("  ⚠️ 静帧抽取失败，将跳过（音频模式）。")
            frame_path = None

    # 4) 切段决策
    input_type = "video" if videos else "audio"
    segments = decide_segments(merged, a.mode)

    # 5) 标题
    title = derive_title(a.inputs, a.title)

    # 6) 写 config
    config = {
        "title": title,
        "source_file": os.path.basename(a.inputs[0]),
        "frame_path": os.path.basename(frame_path) if frame_path else None,
        "input_type": input_type,
        "mode": a.mode,
        "model": a.model if a.mode == "local" else "qwen3-asr-flash",
        "output_dir": out_dir,
        "segments": segments,
    }
    cfg_path = os.path.join(out_dir, "transcribe_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print("-" * 60)
    print(f"✅ 配置已生成：{cfg_path}")
    print(f"   标题：{title}")
    print(f"   类型：{input_type}  模式：{a.mode}  切段数：{len(segments)}")
    if frame_path:
        print(f"   静帧：{os.path.basename(frame_path)}")
    print("-" * 60)
    print("下一步：")
    if a.mode == "cloud":
        print(f"  python {skill_dir}/scripts/transcribe_qwen.py --config {cfg_path}")
    else:
        print(f"  python {skill_dir}/scripts/transcribe_local.py --config {cfg_path}")
    print(f"  （首次转录会下载本地模型，约需数分钟；之后秒级启动）")


if __name__ == "__main__":
    main()
