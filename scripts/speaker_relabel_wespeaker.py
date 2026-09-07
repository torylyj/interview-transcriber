#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeSpeaker 说话人重贴标工具
===========================

用 WeSpeaker 的说话人嵌入（默认 chinese = CNCeleb ResNet34，256 维）替换
FunASR/CAM++ 的句子级说话人标签。适用于已用 Paraformer 转录出「句子 + 时间戳」
但说话人标签不准（CAM++ 在短应答 / 重叠处易贴错人）的场景。

工作流程：
  1. 读取 transcript.json（segments 含 start/end 秒、text、speaker）
  2. 载入 16k 音频（wav 直接读；mp4/mov 用 ffmpeg 抽 16k 单声道）
  3. 按句裁剪音频，逐句提 WeSpeaker embedding
  4. 聚类（默认强制 2 人；可用 --num-speakers 或 --auto 自动估人数）
  5. 回写 SPEAKER_XX 标签，输出新 transcript.json

注意：wespeaker 包在 torch>=2.x 下有两处导入期崩溃（s3prl 引用已删除的
torchaudio API、diar 子模块缺 onnxruntime）。本脚本在导入 wespeaker 之前
打两个补丁：
  - 把 torchaudio.load 替换为 soundfile 实现（绕开 torchcodec 后端）
  - 这两个依赖缺失不影响 ResNet/CAM++ 嵌入提取，已通过 site-packages 的
    frontend/__init__.py 容错导入修复（见安装说明）

用法：
  python speaker_relabel_wespeaker.py --transcript in.json --audio clip.wav \
      --output out.json --num-speakers 2

可选对照评测：
  --reference-json ref.json   # 同上 segments 顺序，speaker 字段为真实角色(采访者/受访者)
                              # 输出该方法相对参考的准确率 / 纯度
"""
import argparse
import json
import os
import sys
import tempfile
import shutil
import subprocess
import numpy as np
import soundfile as sf
import torch
import torchaudio

# ── 补丁 1：用 soundfile 替换 torchaudio.load（绕开 torchcodec 后端）──
def _sf_load(uri, normalize=True, **kwargs):
    data, sr = sf.read(uri, dtype="int16", always_2d=True)  # (frames, ch) int16
    wav = data.astype(np.float32).T  # (ch, frames)，int16 量纲
    if normalize:
        wav = wav / 32768.0
    return torch.from_numpy(np.ascontiguousarray(wav)), int(sr)

torchaudio.load = _sf_load

import wespeaker  # noqa: E402  (必须在 torchaudio.load 补丁之后)


def load_audio_16k(path: str):
    """返回 (waveform int16 ndarray [n], sr)。mp4/mov 先用 ffmpeg 抽 16k 单声道。"""
    ext = os.path.splitext(path)[1].lower()
    tmp = None
    if ext in (".mp4", ".mov", ".mkv", ".avi", ".flv"):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        cmd = [
            "ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
            "-sample_fmt", "s16", tmp.name,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        path = tmp.name
    data, sr = sf.read(path, dtype="int16", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1).astype(np.int16)
    if sr != 16000:
        # 简单重采样用 torchaudio（仅重采样，不触发 torchcodec 文件加载）
        t = torch.from_numpy(data.astype(np.float32)).unsqueeze(0)
        t = torchaudio.transforms.Resample(sr, 16000)(t)
        data = (t.squeeze(0).clamp(-32768, 32767).numpy()).astype(np.int16)
        sr = 16000
    if tmp is not None:
        os.remove(tmp.name)
    return data, sr


def extract_embeddings(model, audio_int16, sr, segments, tmpdir, min_dur=0.3):
    """逐句裁剪 -> 临时 wav -> WeSpeaker embedding。返回 (names, emb_array[N,D])。"""
    names, paths = [], []
    for i, seg in enumerate(segments):
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", 0.0))
        a = int(round(s * sr))
        b = int(round(e * sr))
        if b <= a:
            b = a + 1
        chunk = audio_int16[a:b].copy()
        min_len = int(min_dur * sr)
        if len(chunk) < min_len:
            pad = min_len - len(chunk)
            pre = pad // 2
            post = pad - pre
            chunk = np.concatenate([
                np.zeros(pre, dtype=np.int16), chunk, np.zeros(post, dtype=np.int16)
            ])
        p = os.path.join(tmpdir, f"seg_{i:05d}.wav")
        sf.write(p, chunk, sr, subtype="PCM_16")
        names.append(f"seg_{i:05d}")
        paths.append(p)
    # 用 extract_embedding_list（内部批量前向）提取
    scp = os.path.join(tmpdir, "wav.scp")
    with open(scp, "w", encoding="utf-8") as f:
        for n, p in zip(names, paths):
            f.write(f"{n} {p}\n")
    utt_names, embs = model.extract_embedding_list(scp)
    # 按 segments 顺序对齐（extract_embedding_list 顺序与 scp 一致）
    emb_dict = {n: e for n, e in zip(utt_names, embs)}
    emb_list = [np.asarray(emb_dict[n]) for n in names]
    return np.vstack(emb_list).astype(np.float64)


def cluster_speakers(embs, num_speakers, auto=False):
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    if auto:
        best_k, best_score, best_labels = 2, -1, None
        for k in range(2, 5):
            cl = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
            labels = cl.fit_predict(embs)
            try:
                s = silhouette_score(embs, labels, metric="cosine")
            except Exception:
                s = -1
            if s > best_score:
                best_score, best_k, best_labels = s, k, labels
        return best_labels, best_k

    cl = AgglomerativeClustering(n_clusters=num_speakers, metric="cosine", linkage="average")
    labels = cl.fit_predict(embs)
    return labels, num_speakers


def evaluate(out_segments, ref_segments):
    """out_segments[i].speaker = 方法标签(SPEAKER_XX)；ref_segments[i].speaker = 真实角色。
    通过多数投票把方法标签映射到真实角色，计算准确率与逐簇纯度。"""
    pred = [s.get("speaker", "") for s in out_segments]
    truth = [s.get("speaker", "") for s in ref_segments]
    n = min(len(pred), len(truth))
    clusters = {}
    for i in range(n):
        clusters.setdefault(pred[i], []).append(i)
    # 多数投票映射
    mapping = {}
    for c, idxs in clusters.items():
        vote = {}
        for i in idxs:
            vote[truth[i]] = vote.get(truth[i], 0) + 1
        mapping[c] = max(vote, key=vote.get) if vote else "?"
    correct = sum(1 for i in range(n) if mapping[pred[i]] == truth[i])
    acc = correct / n if n else 0.0
    # 逐簇纯度
    purity = {}
    for c, idxs in clusters.items():
        vote = {}
        for i in idxs:
            vote[truth[i]] = vote.get(truth[i], 0) + 1
        tot = len(idxs)
        purity[c] = (max(vote.values()) / tot if tot else 0.0, tot)
    return acc, n, mapping, purity


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True, help="输入 transcript.json (含 segments)")
    ap.add_argument("--audio", required=True, help="对应音频 wav/mp4")
    ap.add_argument("--output", required=True, help="输出重贴标后的 transcript.json")
    ap.add_argument("--model", default="chinese", help="wespeaker 模型名 (默认 chinese)")
    ap.add_argument("--num-speakers", type=int, default=2, help="强制说话人数 (默认 2)")
    ap.add_argument("--auto", action="store_true", help="自动估计人数(2-4)代替 --num-speakers")
    ap.add_argument("--reference-json", default=None, help="同序 segments，speaker=真实角色，做评测")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--keep-original", action="store_true", help="在原 segment 上保留旧 speaker 字段")
    args = ap.parse_args()

    data = json.load(open(args.transcript, encoding="utf-8"))
    segments = data.get("segments") or data.get("transcript") or []
    if not segments:
        print("❌ 无 segments"); sys.exit(1)

    print(f"载入 wespeaker 模型 '{args.model}' on {args.device} ...")
    model = wespeaker.load_model(args.model)
    # 模型在 cuda 上？wespeaker 内部 self.device；extract 默认用模型 device

    print(f"载入音频 {args.audio} ...")
    audio_int16, sr = load_audio_16k(args.audio)
    print(f"  音频长度 {len(audio_int16)/sr:.1f}s, sr={sr}")

    tmpdir = tempfile.mkdtemp(prefix="wspk_")
    try:
        print(f"逐句提嵌入 ({len(segments)} 句) ...")
        embs = extract_embeddings(model, audio_int16, sr, segments, tmpdir)
        print(f"  嵌入矩阵 {embs.shape}")
        labels, k = cluster_speakers(embs, args.num_speakers, auto=args.auto)
        print(f"  聚类人数 = {k}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    for i, seg in enumerate(segments):
        if args.keep_original:
            seg["speaker_cam"] = seg.get("speaker")
        seg["speaker"] = f"SPEAKER_{int(labels[i]):02d}"

    data["segments"] = segments
    data["speaker_method"] = "WeSpeaker (%s, ResNet34/CNCeleb 256d) 嵌入 + AHC 余弦聚类" % args.model
    json.dump(data, open(args.output, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ 写出 {args.output}")

    if args.reference_json:
        ref = json.load(open(args.reference_json, encoding="utf-8"))
        ref_segs = ref.get("segments") or ref.get("transcript") or []
        acc, n, mapping, purity = evaluate(segments, ref_segs)
        print(f"\n=== 评测（vs 参考角色）===")
        print(f"  样本数: {n} | 准确率: {acc*100:.1f}%")
        for c, (p, tot) in purity.items():
            print(f"  簇 {c}: 纯度 {p*100:.1f}% (共 {tot} 句) -> 多数映射 {mapping[c]}")


if __name__ == "__main__":
    main()
