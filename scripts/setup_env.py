#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
采访转录技能 · 环境与依赖安装（全国内镜像，无需访问 GitHub / 国外 PyPI）

功能：
  1. Python 依赖（默认仅需 5 个）：funasr / modelscope（本地转录）/
     python-docx（生成 .docx）/ pillow（静帧清晰度）/ dashscope（云端转录 +
     说话人 LLM），通过 阿里云 / 清华 / 腾讯云 的 PyPI 镜像自动降级安装
     （默认直连国外 PyPI 经常超时，故强制走国内镜像）。
     ⚠️ 已移出默认安装（不推荐、可省）：
        · faster-whisper（~3GB 模型，中文一般）
        · pyannote.audio（声纹分离，需 HF Token；说话人改由 LLM 语义切分，免 Token）
       如需，见 requirements.txt 注释手动安装。
  2. ffmpeg（仅 Windows 缺失时）：从 npmmirror 二进制镜像下载 ffmpeg-static
     静态构建（含 ffprobe），放入 技能目录/tools/ffmpeg/bin，extract_frame.py
     会自动优先使用该路径，无需手动加 PATH。
  3. 幂等：已满足的依赖跳过；ffmpeg 已在 PATH 则跳过下载。

用法：
  python scripts/setup_env.py               # 安装 Python 依赖 + 按需下载 ffmpeg
  python scripts/setup_env.py --ffmpeg-only
  python scripts/setup_env.py --deps-only
"""

import os
import sys
import ssl
import shutil
import subprocess
import urllib.parse
import urllib.request
import argparse

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_FFMPEG_DIR = os.path.join(SKILL_DIR, "tools", "ffmpeg", "bin")

# ── 国内 PyPI 镜像（按顺序自动降级）──
# 实测可达（已连通性测试）：阿里云 / 清华 / 腾讯云 均 HTTP 200
PYPI_MIRRORS = [
    "https://mirrors.aliyun.com/pypi/simple",                     # 阿里云（推荐）
    "https://pypi.tuna.tsinghua.edu.cn/simple",                  # 清华
    "https://mirrors.cloud.tencent.com/pypi/simple",                 # 腾讯云
]
# 默认安装：覆盖云端 + 本地（SenseVoice/Paraformer）两种模式的最小集合
PY_DEPS = [
    "funasr", "modelscope",          # 本地转录（模型从魔搭社区国内直连）
    "python-docx", "pillow",          # 生成 .docx + 静帧清晰度
    "dashscope",                       # 云端转录 + 说话人/摘要 LLM
]
# 已移出默认（不推荐、可省）：
#   "faster-whisper"  # ~3GB 模型，中文一般
#   "pyannote.audio"  # 声纹分离，需 HF Token；说话人改由 LLM 语义切分
OPTIONAL_DEPS = ["faster-whisper", "pyannote.audio"]

# ── ffmpeg 国内静态构建（npmmirror 二进制镜像，Windows x64）──
# ffmpeg-static 的 win64 文件名即 ffmpeg-win32-x64（npm 历史命名），直接是可执行文件
FFMPEG_MIRROR_BASE = "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1"
FFMPEG_FILES = {
    "ffmpeg.exe": "ffmpeg-win32-x64",
    "ffprobe.exe": "ffprobe-win32-x64",
}


def log(msg):
    print(f"[setup] {msg}")


def install_python_deps(extra: bool = False):
    deps = list(PY_DEPS)
    if extra:
        deps += OPTIONAL_DEPS
        log("含不推荐可选包（faster-whisper / pyannote.audio）")
    for mirror in PYPI_MIRRORS:
        host = urllib.parse.urlparse(mirror).netloc
        log(f"尝试通过 PyPI 镜像安装依赖：{mirror}")
        cmd = [sys.executable, "-m", "pip", "install",
               "-i", mirror, "--trusted-host", host, *PY_DEPS]
        try:
            subprocess.run(cmd, check=True)
            log(f"✅ Python 依赖安装完成（镜像：{host}）")
            return True
        except subprocess.CalledProcessError:
            log(f"⚠️ 镜像 {host} 安装失败，尝试下一个…")
    log("❌ 所有 PyPI 镜像均安装失败，请检查网络或手动执行：")
    log("   " + sys.executable + " -m pip install -i https://mirrors.aliyun.com/pypi/simple " + " ".join(PY_DEPS))
    return False


def which(prog):
    return shutil.which(prog)


def download_ffmpeg():
    if sys.platform != "win32":
        if not which("ffmpeg"):
            log("当前非 Windows 且未检测到 ffmpeg，请自行安装：")
            log("  macOS:   brew install ffmpeg")
            log("  Debian:  sudo apt install ffmpeg")
            log("  Windows: 本脚本自动从国内镜像下载，请在 Windows 上运行")
        else:
            log(f"✅ 已检测到系统 ffmpeg：{which('ffmpeg')}")
        return

    if which("ffmpeg"):
        log(f"✅ 系统已存在 ffmpeg（{which('ffmpeg')}），跳过下载")
        return

    os.makedirs(TOOLS_FFMPEG_DIR, exist_ok=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ok = True
    for exe, remote in FFMPEG_FILES.items():
        url = f"{FFMPEG_MIRROR_BASE}/{remote}"
        dest = os.path.join(TOOLS_FFMPEG_DIR, exe)
        log(f"下载 ffmpeg 静态构建：{remote} → {dest}")
        try:
            with urllib.request.urlopen(url, context=ctx, timeout=180) as r:
                data = r.read()
            with open(dest, "wb") as f:
                f.write(data)
            log(f"  ✅ {exe}（{len(data) // 1024} KB）")
        except Exception as e:
            log(f"  ❌ 下载失败：{e}")
            ok = False
    if ok:
        log(f"✅ ffmpeg 已安装到：{TOOLS_FFMPEG_DIR}")
        log("   脚本会自动优先使用该路径的 ffmpeg / ffprobe，无需手动加 PATH")
    else:
        log(f"❌ ffmpeg 下载失败，可手动下载后放入：{TOOLS_FFMPEG_DIR}")
        log("   镜像：https://registry.npmmirror.com/-/binary/ffmpeg-static/")


def main():
    ap = argparse.ArgumentParser(description="采访转录技能环境安装（国内镜像）")
    ap.add_argument("--ffmpeg-only", action="store_true", help="仅下载 ffmpeg")
    ap.add_argument("--deps-only", action="store_true", help="仅安装 Python 依赖")
    ap.add_argument("--extras", action="store_true", help="额外安装不推荐包（faster-whisper / pyannote.audio，默认不装）")
    a = ap.parse_args()

    print("=" * 60)
    print("采访转录技能 · 环境安装（全国内镜像）")
    print("=" * 60)
    if not a.ffmpeg_only:
        install_python_deps(extra=a.extras)
    if not a.deps_only:
        download_ffmpeg()
    print("=" * 60)
    log("安装流程结束。下一步：把采访视频/音频交给 Agent 即可。")
    log("提示：首次转录会下载本地模型（SenseVoice ~500MB），耗时约 1–5 分钟，")
    log("      之后自动缓存，后续转录秒级启动。")
    print("=" * 60)


if __name__ == "__main__":
    main()
