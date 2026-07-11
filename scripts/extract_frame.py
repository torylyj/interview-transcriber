"""
抽取视频中最清晰的一帧作为人物静帧。

实现：
  1. 用 ffprobe 仅读一次时长（不解码画面）。
  2. 将视频【五等分】，从每段中心各抽 1 帧（默认共 5 帧）。
  3. 用 Pillow 的拉普拉斯边缘检测（FIND_EDGES）计算清晰度（像素标准差），
     选取最清晰的一张，缩放至 800px 宽后保存。
  4. 支持多视频参数：跨所有片段比选全局最清晰帧（多段合并采访场景）。

性能关键：抽帧使用 ffmpeg 输入定位（`-ss POS -i 视频 -vframes 1`），
只解码目标时间点附近的极少帧，【不会软解整段视频】，本地 CPU/GPU 开销极低。
相比固定取第 5 秒，能避免取到黑屏、转场、模糊或字幕遮挡的帧。

依赖: ffmpeg（自动从系统 PATH 或 技能 tools/ffmpeg/bin 查找；缺失可运行 scripts/setup_env.py 从国内镜像下载）, Pillow
用法:
  python extract_frame.py "输入.mp4" "人物静帧.jpg"
  python extract_frame.py "v1.mp4" "v2.mp4" "人物静帧.jpg"   # 多段合并采访：跨片段比选最清晰帧
"""

import os
import sys
import shutil
import subprocess
import tempfile
import argparse
import re


def find_executable(name):
    """定位 ffmpeg / ffprobe：
    优先系统 PATH；其次技能自带 tools/ffmpeg/bin（由 scripts/setup_env.py 从国内镜像下载）。
    """
    found = shutil.which(name)
    if found:
        return found
    here = os.path.dirname(os.path.abspath(__file__))
    alt = os.path.normpath(os.path.join(here, "..", "tools", "ffmpeg", "bin", name + ".exe"))
    if os.path.isfile(alt):
        return alt
    return None


# 启动即解析 ffmpeg / ffprobe 路径，供下方 subprocess 调用
FFMPEG = find_executable("ffmpeg")
FFPROBE = find_executable("ffprobe")


def normalize_path(p):
    """将 Git Bash 风格路径 /c/Users/... 归一化为 Windows 路径 C:/Users/...，
    避免 Windows 原生程序（ffmpeg / Python）无法识别 /c/ 前缀导致文件找不到。"""
    if not p:
        return p
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return p


def check_ffmpeg():
    if FFMPEG is None:
        print("错误: 未找到 ffmpeg。请运行技能自带安装脚本（从国内镜像自动下载）：")
        print("  python <技能目录>/scripts/setup_env.py")
        print("  或手动下载 ffmpeg 静态构建放入系统 PATH：")
        print("  https://registry.npmmirror.com/-/binary/ffmpeg-static/")
        sys.exit(1)
    if FFPROBE is None:
        print("错误: 未找到 ffprobe（ffmpeg 组件）。请重新运行安装脚本或确认 ffmpeg 完整。")
        sys.exit(1)


def get_duration(video_path: str) -> float:
    """用 ffprobe 获取视频时长（秒），失败返回 0。"""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
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


def extract_candidates(video_path: str, out_dir: str, duration: float, n: int = 5) -> list:
    """将视频【五等分】，从每段中心各抽 1 帧（默认共 5 帧），返回帧路径列表。

    性能关键：使用 ffmpeg 输入定位（`-ss POS -i 视频 -vframes 1`），
    只解码该时间点附近的极少帧，【不会软解整段视频】，本地开销极低。
    """
    candidates = []
    if duration <= 0:
        positions = [5.0]  # 无法获取时长：兜底取第 5 秒（仍走输入定位，不整段解码）
    else:
        # 五等分：第 i 段中心 = (i + 0.5) / n × 总时长  →  10% / 30% / 50% / 70% / 90%
        positions = [(i + 0.5) / n * duration for i in range(n)]

    for i, pos in enumerate(positions):
        cand = os.path.join(out_dir, f"cand_{i:02d}.jpg")
        cmd = [
            FFMPEG, "-ss", f"{pos:.3f}", "-i", video_path,
            "-frames:v", "1", "-vf", "scale=800:-1", "-q:v", "2", cand, "-y",
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

    # 归一化路径（兼容 Git Bash 的 /c/... 写法，否则 Windows 原生 ffmpeg 找不到文件）
    args.videos = [normalize_path(v) for v in args.videos]
    args.output = normalize_path(args.output)

    tmp = tempfile.mkdtemp(prefix="frame_")
    best_path, best_score = pick_best(args.videos, tmp, args.candidates)

    if not best_path:
        # 兜底：直接抽第 5 秒
        print("  ⚠️ 候选帧抽取失败，兜底抽取第 5 秒")
        try:
            subprocess.run(
                [FFMPEG, "-ss", "5", "-i", args.videos[0], "-vframes", "1",
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
