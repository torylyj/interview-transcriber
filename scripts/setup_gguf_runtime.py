# -*- coding: utf-8 -*-
"""
快速档 GGUF 运行时/模型自动安装（v1.13.3）

自动完成：
  1. 检测本机 NVIDIA GPU 与驱动版本（nvidia-smi，失败优雅回退 CPU）
  2. 按本机配置自动选择运行时包：CPU AVX2 / CUDA（RTX 50 系自动选 Blackwell sm_120 包）/ Vulkan
  3. 从多镜像下载（国内优先魔搭直连），SHA-256 校验后解压
  4. 幂等：已就绪的组件自动跳过，--force 强制重装

目录布局（默认 --base-dir G:/llamacpp-asr）：
  <base>/runtime/         CPU AVX2 运行时（~5MB）
  <base>/runtime-cuda/    CUDA 运行时（~412MB，含 cuBLAS DLL，免装 CUDA Toolkit）
  <base>/gguf/            sensevoice-small-q8.gguf + fsmn-vad.gguf（~256MB）

用法:
  python setup_gguf_runtime.py                       # 全自动（检测 GPU 选包）
  python setup_gguf_runtime.py --backend cuda        # 强制 CUDA 版
  python setup_gguf_runtime.py --base-dir D:/asr     # 自定义安装目录
  python setup_gguf_runtime.py --verify              # 只检查不安装
  python setup_gguf_runtime.py --force               # 强制重装

下载渠道（失败自动逐个切换）：
  模型:   魔搭 modelscope.cn（国内直连）→ HuggingFace → hf-mirror.com
  运行时: GitHub Release → ghfast.top → gh-proxy.com → gh.llkk.cc（社区加速前缀）
"""
import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

RUNTIME_TAG = "runtime-llamacpp-v0.2.6"
GITHUB_BASE = f"https://github.com/modelscope/FunASR/releases/download/{RUNTIME_TAG}"
GH_MIRRORS = ["", "https://ghfast.top/", "https://gh-proxy.com/", "https://gh.llkk.cc/"]

# 模型：魔搭（国内直连，首选）→ HF → hf-mirror（LFS 可能 302 海外，仅备选）
MODEL_MIRRORS = [
    "https://www.modelscope.cn/models/FunAudioLLM/{repo}/resolve/master/{file}",
    "https://huggingface.co/FunAudioLLM/{repo}/resolve/main/{file}",
    "https://hf-mirror.com/FunAudioLLM/{repo}/resolve/main/{file}",
]
MODELS = [
    {"repo": "SenseVoiceSmall-GGUF", "file": "sensevoice-small-q8.gguf",
     "size": 254208320, "sha256": "4ae45c94422de949b387e2e0fb10d7e14e4c42c69db30c3444ecc7d4b844b7c5"},
    {"repo": "fsmn-vad-GGUF", "file": "fsmn-vad.gguf",
     "size": 1720512, "sha256": "1270f2559c495f4e7b6e739541151027d360761a3fda43fc147034f5719f5479"},
]

# 运行时包 SHA-256（来自 funasr.com/deploy/llama-cpp.html 官方表格，windows-x64-cuda 已实测核验）
RUNTIME_SHA = {
    "funasr-llamacpp-windows-x64.zip": "f6a73a548413ba9fbaf2145263ea66ec53cbdad1fb11790dbeeee493e339492e",
    "funasr-llamacpp-windows-x64-avx2.zip": "062cda8fefadd31c3e811227116daccf448a8520f4b0bb168d225c896e65ebbd",
    "funasr-llamacpp-windows-x64-vulkan.zip": "debf8007e55011cad06081e7b8a78972f1b8fe672bc324d41e650d68821f6a6a",
    "funasr-llamacpp-windows-x64-cuda.zip": "148657911fb666b7af6ec43af2e23a0984e3259012b4c39f95631b717feb6840",
    "funasr-llamacpp-windows-x64-cuda-blackwell.zip": "e32961a753f40888182f352fa551159c5165a6a77718ae4ade316aedfea4b1c2",
    "funasr-llamacpp-linux-x64.tar.gz": "779967de1c528c2be966bcc47f246e7d3e6fcdb748d9491263062f4120f35e52",
    "funasr-llamacpp-linux-x64-avx2.tar.gz": "aaebc5470f846ce915200b35d6e9f9bd0a0d3ed399d39e49bdeb7a1f1782bc70",
    "funasr-llamacpp-linux-x64-vulkan.tar.gz": "f02d41e98e9d4041f0896661007193810f025484d2175958f7c1313d5c90ec46",
    "funasr-llamacpp-linux-arm64.tar.gz": "7bca29cfa3c9a08e235a62212ca9e00f6656e59a8f07078966a2bfda1e5aa1f9",
    "funasr-llamacpp-macos-arm64.tar.gz": "bda59474202b887190f59d25b7b42c714469efae71276072c12fa0a38de68792",
}
# CUDA 13 DLL 要求驱动 >= R580；RTX 50 系（sm_120）用 blackwell 专包
MIN_CUDA13_DRIVER = 580
EXE_NAME = "llama-funasr-sensevoice.exe"


def log(msg):
    print(msg, flush=True)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_gpu():
    """检测 NVIDIA GPU 与驱动。返回 (name, driver_major) 或 None（含 nvidia-smi 不可用的情况）。"""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        line = (p.stdout or "").strip().splitlines()
        if p.returncode == 0 and line and "," in line[0]:
            name, driver = [x.strip() for x in line[0].split(",", 1)]
            try:
                major = int(driver.split(".")[0])
            except ValueError:
                major = 0
            return name, major
    except Exception:
        pass
    return None


def pick_runtime_package(backend, gpu):
    """按后端/本机配置选择运行时包名。"""
    is_win = platform.system() == "Windows"
    ext = "zip" if is_win else "tar.gz"
    osname = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system())
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"

    if backend == "auto":
        if gpu:
            name, major = gpu
            if arch == "x64" and osname == "windows":
                pkg = (f"funasr-llamacpp-windows-x64-cuda-blackwell.{ext}"
                       if "RTX 50" in name else f"funasr-llamacpp-windows-x64-cuda.{ext}")
                if major < MIN_CUDA13_DRIVER:
                    log(f"⚠️ 驱动 {major}.x 过旧（CUDA 13 需 ≥{MIN_CUDA13_DRIVER}），回退 CPU 版；"
                        f"升级 NVIDIA 驱动后可重跑换 GPU 版")
                    pkg = f"funasr-llamacpp-windows-x64-avx2.{ext}"
                return pkg, "cuda" if "cuda" in pkg else "cpu"
            log(f"⚠️ 检测到 {name} 但暂无对应平台预编译 CUDA 包，回退 CPU")
        return (f"funasr-llamacpp-{osname}-x64-avx2.{ext}" if arch == "x64" and osname != "macos"
                else f"funasr-llamacpp-{osname}-arm64.{ext}"), "cpu"
    if backend == "cuda":
        if gpu and "RTX 50" in gpu[0] and osname == "windows" and arch == "x64":
            return f"funasr-llamacpp-windows-x64-cuda-blackwell.{ext}", "cuda"
        return f"funasr-llamacpp-{osname}-x64-cuda.{ext}", "cuda"
    if backend == "vulkan":
        return f"funasr-llamacpp-{osname}-x64-vulkan.{ext}", "vulkan"
    # cpu
    if arch == "x64" and osname != "macos":
        return f"funasr-llamacpp-{osname}-x64-avx2.{ext}", "cpu"
    return f"funasr-llamacpp-{osname}-arm64.{ext}", "cpu"


def fetch(urls, dest, expect_sha=None, label=""):
    """多镜像依次尝试下载（支持断点续传），SHA-256 校验。"""
    for url in urls:
        log(f"   ⏳ 下载 {label}…\n      {url}")
        p = subprocess.run(["curl", "-fL", "--retry", "2", "--connect-timeout", "20",
                            "-C", "-", "-o", dest, url],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0 or not os.path.exists(dest):
            log("      ✗ 失败，换下一个镜像")
            continue
        if expect_sha:
            got = sha256_of(dest)
            if got != expect_sha:
                log(f"      ✗ SHA-256 不匹配（{got[:12]}…），换下一个镜像")
                os.remove(dest)
                continue
            log("      ✓ SHA-256 校验通过")
        return True
    return False


def extract(archive, dest_dir):
    """解压到 dest_dir；若解出单一子目录且 exe 在其中，上提一层。"""
    os.makedirs(dest_dir, exist_ok=True)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest_dir)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest_dir)
    # 归位：exe 不在根目录时找一层内的 exe
    exe = os.path.join(dest_dir, EXE_NAME)
    if not os.path.exists(exe):
        for root, _dirs, files in os.walk(dest_dir):
            if EXE_NAME in files or any(f.startswith("llama-funasr") for f in files):
                for f in os.listdir(root):
                    src, dst = os.path.join(root, f), os.path.join(dest_dir, f)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                break
    os.remove(archive)


def install_runtime(base_dir, backend, gpu, force):
    pkg, kind = pick_runtime_package(backend, gpu)
    target = os.path.join(base_dir, f"runtime{'-cuda' if kind == 'cuda' else ''}")
    exe = os.path.join(target, EXE_NAME)
    marker = os.path.join(target, ".runtime-info")
    if os.path.exists(exe) and not force:
        log(f"✓ 运行时已就绪: {target}（跳过，--force 重装）")
        return kind
    if os.path.exists(marker) and pkg in open(marker, encoding="utf-8").read() and not force:
        log(f"✓ 运行时已就绪: {target}（跳过）")
        return kind
    urls = [f"{m}{GITHUB_BASE}/{pkg}" for m in GH_MIRRORS]
    tmp = os.path.join(base_dir, pkg)
    log(f"📦 安装运行时 [{kind}]: {pkg}")
    if not fetch(urls, tmp, RUNTIME_SHA.get(pkg), pkg):
        log("   ❌ 所有镜像均失败；手动下载方法见 references/model_download.md")
        return None
    if os.path.exists(target):
        shutil.rmtree(target)
    extract(tmp, target)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(pkg)
    log(f"   ✅ 解压至 {target}")
    return kind


def install_models(gguf_dir, force):
    os.makedirs(gguf_dir, exist_ok=True)
    ok = True
    for m in MODELS:
        dest = os.path.join(gguf_dir, m["file"])
        if os.path.exists(dest) and not force:
            if sha256_of(dest) == m["sha256"]:
                log(f"✓ 模型已就绪: {m['file']}（SHA-256 匹配，跳过）")
                continue
            log(f"⚠️ {m['file']} 已存在但校验不符，重新下载")
        urls = [tpl.format(repo=m["repo"], file=m["file"]) for tpl in MODEL_MIRRORS]
        if not fetch(urls, dest, m["sha256"], m["file"]):
            log(f"   ❌ {m['file']} 所有镜像均失败")
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description="快速档 GGUF 运行时/模型自动安装（GPU 自动识别 + 多镜像）")
    ap.add_argument("--base-dir", default=r"G:\llamacpp-asr")
    ap.add_argument("--backend", default="auto", choices=["auto", "cpu", "cuda", "vulkan"],
                    help="auto=按本机 GPU/驱动自动选包（默认）")
    ap.add_argument("--force", action="store_true", help="强制重新下载安装")
    ap.add_argument("--verify", action="store_true", help="只检查不安装")
    ap.add_argument("--models-only", action="store_true")
    ap.add_argument("--runtime-only", action="store_true")
    args = ap.parse_args()

    base = os.path.abspath(args.base_dir)
    os.makedirs(base, exist_ok=True)
    gguf_dir = os.path.join(base, "gguf")

    gpu = detect_gpu()
    if gpu:
        log(f"🖥️ 检测到 NVIDIA GPU: {gpu[0]}（驱动 {gpu[1]}.x）")
    else:
        log("🖥️ 未检测到 NVIDIA GPU（或 nvidia-smi 不可用）→ 使用 CPU 版")

    if args.verify:
        exe = os.path.join(base, "runtime", EXE_NAME)
        cuda_exe = os.path.join(base, "runtime-cuda", EXE_NAME)
        ok = True
        for m in MODELS:
            p = os.path.join(gguf_dir, m["file"])
            good = os.path.exists(p) and sha256_of(p) == m["sha256"]
            log(f"{'✓' if good else '✗'} 模型 {m['file']}")
            ok &= good
        kind = "cuda" if os.path.exists(cuda_exe) else ("cpu" if os.path.exists(exe) else None)
        log(f"{'✓' if kind else '✗'} 运行时: {kind or '缺失'}"
            + ("（CUDA 版，转录自动走 GPU）" if kind == "cuda" else ""))
        sys.exit(0 if ok and kind else 2)

    if not args.models_only:
        kind = install_runtime(base, args.backend, gpu, args.force)
        if kind is None:
            sys.exit(2)
    if not args.runtime_only:
        if not install_models(gguf_dir, args.force):
            sys.exit(2)
    log("🎉 全部就绪。转录命令：transcribe_gguf.py --config ... [--backend cuda --runtime-dir <runtime-cuda>]")


if __name__ == "__main__":
    main()
