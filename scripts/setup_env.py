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
        · pyannote.audio（声纹分离，需 HF Token；**已废弃**——本地说话人改由 CAM++ 说话人嵌入，免 Token）
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
#   "pyannote.audio"  # 声纹分离，需 HF Token；已废弃——本地说话人改由 CAM++ 嵌入
OPTIONAL_DEPS = ["faster-whisper", "pyannote.audio"]

# 包名 -> import 模块名（用于「已装则跳过」真实探测，避免重复下载）
PKG_IMPORT = {
    "funasr": "funasr",
    "modelscope": "modelscope",
    "python-docx": "docx",
    "pillow": "PIL",
    "dashscope": "dashscope",
    "faster-whisper": "faster_whisper",
    "pyannote.audio": "pyannote",
}

def is_importable(mod: str) -> bool:
    """真实探测某模块是否已可 import（不依赖 pip 记录）。"""
    try:
        __import__(mod)
        return True
    except Exception:
        return False

# ── ffmpeg 国内静态构建（npmmirror 二进制镜像，Windows x64）──
# ffmpeg-static 的 win64 文件名即 ffmpeg-win32-x64（npm 历史命名），直接是可执行文件
FFMPEG_MIRROR_BASE = "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1"
FFMPEG_FILES = {
    "ffmpeg.exe": "ffmpeg-win32-x64",
    "ffprobe.exe": "ffprobe-win32-x64",
}


def log(msg):
    print(f"[setup] {msg}")


def install_one_package(pkg: str) -> bool:
    """逐个包安装（隔离失败）：任一镜像装上即返回 True，全部失败返回 False。"""
    for mirror in PYPI_MIRRORS:
        host = urllib.parse.urlparse(mirror).netloc
        cmd = [sys.executable, "-m", "pip", "install",
               "-i", mirror, "--trusted-host", host, pkg]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            continue
    return False

def install_python_deps(extra: bool = False, force: bool = False):
    deps = list(PY_DEPS)
    if extra:
        deps += OPTIONAL_DEPS
        log("含不推荐可选包（faster-whisper / pyannote.audio）")
    skipped, failed = 0, []
    for pkg in deps:
        mod = PKG_IMPORT.get(pkg, pkg)
        if not force and is_importable(mod):
            log(f"↷ {pkg} 已安装（import {mod} OK），跳过")
            skipped += 1
            continue
        log(f"→ 安装 {pkg} …")
        if install_one_package(pkg):
            log(f"  ✅ {pkg} 安装成功")
        else:
            log(f"  ❌ {pkg} 在所有镜像均安装失败")
            failed.append(pkg)
    if skipped:
        log(f"ℹ️ 已跳过 {skipped} 个已安装组件（未重复下载）")
    if failed:
        log(f"⚠️ 以下包安装失败（其余已装好，可单独重试）：{', '.join(failed)}")
        log("   单独重试：")
        for pkg in failed:
            log(f"     {sys.executable} -m pip install -i https://mirrors.aliyun.com/pypi/simple {pkg}")
        return False
    log(f"✅ Python 依赖处理完成（共 {len(deps)} 个，其中已装跳过 {skipped} 个）")
    return True


def detect_gpu() -> bool:
    """检测是否有可用的 NVIDIA GPU（用于选择 torch 版本）。"""
    # 优先用已装的 torch 直接探；未装则退化为 nvidia-smi
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        pass
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def install_torch(gpu: bool, force: bool = False) -> bool:
    """安装 torch + torchaudio：有 GPU 装 CUDA 版（cu128），否则 CPU 版。

    已装且版本匹配时自动跳过（尤其避免重复下载 2.7GB CUDA 版）。
    无论哪种，本地转录引擎（SenseVoice/Paraformer）都仍是默认推理方式，
    GPU 只是加速，不改变「默认本地模型」的策略。
    """
    # ── 已装检测：避免重复下载 ──
    if not force:
        try:
            import torch  # noqa: F401
            has_cuda = bool(torch.cuda.is_available())
        except Exception:
            has_cuda = False
        else:
            if gpu and has_cuda:
                log("↷ torch 已装（CUDA 版，GPU 可用），跳过下载")
                return True
            if not gpu:
                log("↷ torch 已装（可兼容 CPU 推理），跳过下载")
                return True
            # 想要 GPU 但当前是 CPU 版 → 需重装为 CUDA 版
            log("⚠️ torch 已装但为 CPU 版、无 CUDA，将重装为 CUDA 版…")
    if gpu:
        # CUDA 版官方源（cu128 匹配绝大多数现代驱动）
        log("   ⏳ 即将下载 CUDA 版 torch/torchaudio（约 2.7GB，可能耗时十余分钟）…")
        cmd = [sys.executable, "-m", "pip", "install", "torch", "torchaudio",
               "--index-url", "https://download.pytorch.org/whl/cu128"]
    else:
        # CPU 版走国内镜像
        log("   ⏳ 即将下载 CPU 版 torch/torchaudio（约 200MB）…")
        cmd = [sys.executable, "-m", "pip", "install", "-i", PYPI_MIRRORS[0],
               "--trusted-host", urllib.parse.urlparse(PYPI_MIRRORS[0]).netloc,
               "torch", "torchaudio"]
    try:
        subprocess.run(cmd, check=True)
        log("✅ torch/torchaudio 安装成功" + ("（CUDA 版，本地模型走 GPU 加速）" if gpu else "（CPU 版）"))
        return True
    except subprocess.CalledProcessError as e:
        log(f"❌ torch 安装失败：{e}")
        return False


def which(prog):
    return shutil.which(prog)


# ── 安装后自检（review）：逐项核对，漏装一目了然 ──
# 元组：(import 名, 展示名, 安装包名)
VERIFY_PACKAGES = [
    ("funasr", "funasr（本地 ASR）", "funasr"),
    ("modelscope", "modelscope（模型下载）", "modelscope"),
    ("docx", "python-docx（生成 .docx）", "python-docx"),
    ("PIL", "pillow（静帧清晰度）", "pillow"),
    ("dashscope", "dashscope（云端转录 + 说话人 LLM）", "dashscope"),
]

def verify_environment(verbose: bool = True) -> bool:
    """逐项核对所有必要组件是否真的可用；返回 True 表示全部 PASS。"""
    results = []  # (展示名, ok, detail)

    # 1) Python 包：真实 import 一次，而非只看 pip 记录
    for mod, label, pkg in VERIFY_PACKAGES:
        try:
            __import__(mod)
            results.append((label, True, "import OK"))
        except Exception as e:
            results.append((label, False, f"import 失败：{type(e).__name__}: {e}"))

    # 2) ffmpeg / ffprobe：PATH 或 技能目录/tools/ffmpeg/bin 任一存在即可
    for prog in ("ffmpeg", "ffprobe"):
        found = which(prog)
        if not found and sys.platform == "win32":
            local = os.path.join(TOOLS_FFMPEG_DIR, f"{prog}.exe")
            found = local if os.path.isfile(local) else None
        if found:
            results.append((f"{prog}（音视频处理）", True, found))
        else:
            results.append((f"{prog}（音视频处理）", False, "未找到（PATH 与 tools/ffmpeg/bin 均无）"))

    all_ok = all(ok for _, ok, _ in results)
    if verbose:
        print("-" * 60)
        log("组件自检（review）结果：")
        for label, ok, detail in results:
            mark = "✅" if ok else "❌"
            log(f"  {mark} {label} — {detail}")
        print("-" * 60)
        if all_ok:
            log("全部组件就绪，可以开始转录。")
        else:
            missing = [label for label, ok, _ in results if not ok]
            log(f"⚠️ 有 {len(missing)} 个组件缺失：{', '.join(missing)}")
            log("   修复方式：")
            log("   - Python 包缺失 -> 重新运行 `python scripts/setup_env.py`（会逐包补齐，不影响已装项）")
            log("   - ffmpeg 缺失 -> 重新运行 `python scripts/setup_env.py`（Windows 自动下载静态构建）")
            log("   或单独运行 `python scripts/setup_env.py --verify` 仅复查、不安装。")
        print("-" * 60)
    return all_ok


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
    ap.add_argument("--force", action="store_true", help="忽略已装检测，强制重新安装/升级所有组件")
    ap.add_argument("--verify", action="store_true", help="仅做组件自检（review），不安装任何东西")
    a = ap.parse_args()

    print("=" * 60)
    print("采访转录技能 · 环境安装（全国内镜像）")
    print("=" * 60)

    if a.verify:
        # 仅复查模式：不安装，只核对当前环境
        ok = verify_environment(verbose=True)
        print("=" * 60)
        sys.exit(0 if ok else 1)

    if not a.ffmpeg_only:
        # 先确保 torch（GPU 检测 → 装 CUDA 版，否则 CPU 版），
        # 再装其余依赖；已装且版本匹配的组件会自动跳过，不重复下载。
        gpu = detect_gpu()
        if gpu:
            log("🔧 检测到 NVIDIA GPU，将确保安装 CUDA 版 torch/torchaudio（本地模型走 GPU 加速）…")
        else:
            log("ℹ️ 未检测到 GPU，将确保安装 CPU 版 torch/torchaudio…")
        if not a.force:
            log("   （已装且版本匹配的组件会自动跳过，不会重复下载；用 `--force` 可强制重装）")
        else:
            log("   （--force：忽略已装检测，强制重装/升级所有组件）")
        log("   若只想用云端 Qwen3-ASR-Flash（不装本地推理栈），可改用 `python setup_env.py --deps-only` 仅装轻量依赖。")
        install_torch(gpu, force=a.force)
        install_python_deps(extra=a.extras, force=a.force)
    if not a.deps_only:
        download_ffmpeg()

    # ── 装完强制 review：逐项核对，漏装当场暴露 ──
    print("=" * 60)
    ok = verify_environment(verbose=True)
    print("=" * 60)
    if ok:
        log("安装流程结束，全部组件已确认就绪。下一步：把采访视频/音频交给 Agent 即可。")
    else:
        log("安装流程结束，但自检发现缺失组件（见上方 ❌）。请按提示修复后，")
        log("再运行 `python scripts/setup_env.py --verify` 复查，全部 ✅ 后再开始转录。")
    log("提示：首次转录会下载本地模型（SenseVoice ~500MB），耗时约 1–5 分钟，")
    log("      之后自动缓存，后续转录秒级启动。")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
