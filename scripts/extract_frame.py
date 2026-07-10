"""
抽取视频中最清晰的一帧作为人物静帧。

实现：在视频时长内均匀抽取若干候选帧（跳过开头/结尾的黑屏、标题卡与字幕条），
用 Pillow 的拉普拉斯边缘检测（FIND_EDGES）计算清晰度（像素标准差），
选取最清晰的一张，缩放至 800px 宽后保存。

相比固定取第 5 秒，能避免取到黑屏、转场、模糊或字幕遮挡的帧。

依赖: ffmpeg（需在系统 PATH）, Pillow
用法:
  python extract_frame.py "输入.mp4" "人物静帧.jpg"
  python extract_frame.py "v1.mp4" "v2.mp4" "人物静帧.jpg"   # 多段合并采访：跨片段比选最清晰帧
"""

import os
import sys
import subprocess
import tempfile
import argparse


def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True, timeout=15)
    except Exception:
        print("错误: 未找到 ffmpeg，请先安装并加入 PATH（https://ffmpeg.org/）")
        sys.exit(1)


def get_duration(video_path: str) -> float:
    """用 ffprobe 获取视频时长（秒），失败返回 0。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def sharpness(img_path: str) -> float:
    """用拉普拉斯边缘检测（近似）的像素标准差衡量清晰度，越大越清晰。

    用直方图计算均值/方差，避免逐像素 materialize（更快、无 Pillow 弃用告警）。
    """
    try:
        from PIL import Image, ImageFilter
        with Image.open(img_path) as im:
            gray = im.convert("L")
            edges = gray.filter(ImageFilter.FIND_EDGES)
            hist = edges.histogram()  # 256 个灰度级的计数
        n = sum(hist)
        if n == 0:
            return 0.0
        mean = sum(i * c for i, c in enumerate(hist)) / n
        var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / n
        return var ** 0.5
    except Exception:
        return -1.0


def extract_candidates(video_path: str, out_dir: str, duration: float, n: int) -> list:
    """在视频均匀位置抽取 n 帧（800px 宽），返回帧路径列表。"""
    candidates = []
    if duration <= 0:
        positions = [5.0]  # 无法获取时长，兜底取第 5 秒
    else:
        lo, hi = duration * 0.08, duration * 0.92  # 跳过首尾 8%
        span = hi - lo
        positions = [lo + span * (i + 0.5) / n for i in range(n)]

    for i, pos in enumerate(positions):
        cand = os.path.join(out_dir, f"cand_{i:02d}.jpg")
        cmd = [
            "ffmpeg", "-ss", f"{pos:.2f}", "-i", video_path,
            "-vframes", "1", "-vf", "scale=800:-1", "-q:v", "2", cand, "-y",
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        except Exception:
            continue
        if os.path.exists(cand):
            candidates.append(cand)
    return candidates


def pick_best(videos: list, out_dir: str, candidates_per_video: int) -> str:
    best_path, best_score = None, -1.0
    for v in videos:
        if not os.path.exists(v):
            print(f"  ⚠️ 视频不存在，跳过: {v}")
            continue
        dur = get_duration(v)
        for c in extract_candidates(v, out_dir, dur, candidates_per_video):
            s = sharpness(c)
            if s > best_score:
                best_score, best_path = s, c
    return best_path, best_score


def main():
    parser = argparse.ArgumentParser(description="抽取视频最清晰帧（支持多视频跨片段比选）")
    parser.add_argument("videos", nargs="+", help="视频文件（可多个，用于合并采访）")
    parser.add_argument("output", help="输出静帧路径")
    parser.add_argument("--candidates", type=int, default=5, help="每个视频抽取的候选帧数（默认 5）")
    args = parser.parse_args()

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("错误: Pillow 未安装。请先执行: pip install pillow")
        sys.exit(1)

    check_ffmpeg()

    tmp = tempfile.mkdtemp(prefix="frame_")
    best_path, best_score = pick_best(args.videos, tmp, args.candidates)

    if not best_path:
        # 兜底：直接抽第 5 秒
        print("  ⚠️ 候选帧抽取失败，兜底抽取第 5 秒")
        try:
            subprocess.run(
                ["ffmpeg", "-ss", "5", "-i", args.videos[0], "-vframes", "1",
                 "-vf", "scale=800:-1", "-q:v", "2", args.output, "-y"],
                capture_output=True, text=True, check=True, timeout=60,
            )
            print(f"✅ 静帧已生成（兜底第 5 秒）: {args.output}")
        except Exception as e:
            print(f"❌ 静帧生成失败: {e}")
            sys.exit(1)
        return

    # 复制最优帧到输出（已在 800px 宽）
    try:
        with Image.open(best_path) as im:
            im.save(args.output, "JPEG", quality=90)
    except Exception:
        import shutil
        shutil.copy(best_path, args.output)
    print(f"✅ 静帧已生成（最清晰帧，清晰度评分 {best_score:.1f}）: {args.output}")


if __name__ == "__main__":
    main()
