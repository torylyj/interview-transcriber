#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeSpeaker vs CAM++ 说话人贴标 对照测试
======================================
截取一段真实双人采访，分别用：
  - CAM++ （FunASR 内部 spk_model，preset_spk_num=2）
  - WeSpeaker（本工具 speaker_relabel_wespeaker.py）
做说话人贴标，再用 correct_speakers(LLM) 产出的「真实角色」作参照，
量化两者准确率，并给出两方法贴标的一致性。

用法：
  python benchmark_wespeaker.py --source 输出.wav --start 600 --dur 600 \
      --work-dir _bench --api-key $KEY
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = r"C:/Users/admin/.workbuddy/binaries/python/envs/transcribe2/Scripts/python.exe"
TRANSCRIBE = os.path.join(HERE, "transcribe_local.py")
RELABEL = os.path.join(HERE, "speaker_relabel_wespeaker.py")
CORRECT = os.path.join(HERE, "correct_speakers.py")
sys.path.insert(0, HERE)
import speaker_relabel_wespeaker as wspk  # 复用 evaluate()


def run(cmd):
    print(">>", " ".join(cmd[:4]), "...")
    r = subprocess.run([VENV] + cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("STDERR:", r.stderr[-1500:])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="源音频 wav/mp4")
    ap.add_argument("--start", type=float, default=600, help="切片起点(秒)")
    ap.add_argument("--dur", type=float, default=600, help="切片时长(秒)")
    ap.add_argument("--work-dir", default="_bench")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--num-speakers", type=int, default=2)
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    clip = os.path.join(args.work_dir, "clip.wav")
    # 1) 切片
    print(f"[1] ffmpeg 切片 {args.start}s ~ {args.start+args.dur}s")
    subprocess.run([
        "ffmpeg", "-y", "-i", args.source, "-ss", str(args.start),
        "-t", str(args.dur), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", clip
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2) FunASR + CAM++ 基线
    print("[2] FunASR + CAM++ 转录（含说话人标签）")
    cfg = {
        "title": "bench", "source_file": clip, "frame_path": None,
        "input_type": "audio", "mode": "local", "model": "paraformer",
        "output_dir": os.path.abspath(args.work_dir),
        "segments": [{"file": clip, "offset": 0}],
        "preset_spk_num": args.num_speakers,
    }
    cfg_path = os.path.join(args.work_dir, "clip_config.json")
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    run([TRANSCRIBE, "--config", cfg_path, "--model", "paraformer"])
    cam_path = os.path.join(args.work_dir, "bench_transcript.json")
    if not os.path.exists(cam_path):
        print("❌ CAM++ 转录失败"); sys.exit(1)

    # 3) WeSpeaker 重贴标
    print("[3] WeSpeaker 重贴标")
    wes_path = os.path.join(args.work_dir, "bench_wespeaker.json")
    run([RELABEL, "--transcript", cam_path, "--audio", clip,
         "--output", wes_path, "--num-speakers", str(args.num_speakers)])

    # 4) correct_speakers → 参考角色
    print("[4] LLM 校正（参考角色）")
    corr_path = os.path.join(args.work_dir, "corrections.json")
    run([CORRECT, cam_path, "--output", corr_path,
         "--api-key", args.api_key, "--title", "bench"])

    # 5) 评测
    cam = json.load(open(cam_path, encoding="utf-8"))
    wes = json.load(open(wes_path, encoding="utf-8"))
    cam_segs = cam.get("segments") or []
    wes_segs = wes.get("segments") or []
    ref_segs = None
    if os.path.exists(corr_path):
        corr = json.load(open(corr_path, encoding="utf-8"))
        sroles = corr.get("speaker_roles", {})
        ref_segs = [{"speaker": sroles.get(s.get("speaker", "SPEAKER_00"), "?")}
                    for s in cam_segs]

    print("\n" + "=" * 60)
    print("对照结果（切片 %.0f~%.0f 秒，%d 句）" % (args.start, args.start + args.dur, len(cam_segs)))
    if ref_segs:
        acc_cam, n, map_cam, pur_cam = wspk.evaluate(cam_segs, ref_segs)
        acc_wes, n, map_wes, pur_wes = wspk.evaluate(wes_segs, ref_segs)
        print(f"  CAM++  准确率: {acc_cam*100:.1f}%")
        print(f"  WeSpeaker 准确率: {acc_wes*100:.1f}%")
        # 两方法一致性（2 簇，取最佳对应方向）
        cam_lab = [s.get("speaker") for s in cam_segs]
        wes_lab = [s.get("speaker") for s in wes_segs]
        # 建立 wes->cam 标签映射（多数投票）
        w2c = {}
        wgroups = {}
        for i, l in enumerate(wes_lab):
            wgroups.setdefault(l, []).append(i)
        for cl, idxs in wgroups.items():
            vote = {}
            for i in idxs:
                vote[cam_lab[i]] = vote.get(cam_lab[i], 0) + 1
            w2c[cl] = max(vote, key=vote.get)
        agree = sum(1 for i in range(n) if w2c[wes_lab[i]] == cam_lab[i])
        print(f"  两方法标签一致性: {agree/n*100:.1f}%")
    else:
        print("  （无参考角色，跳过准确率评测）")
    print("=" * 60)


if __name__ == "__main__":
    main()
