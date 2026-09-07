# 模型下载与依赖说明

## 模型对比

| 模型 | 下载源 | 需要 HF Token | 中文质量 | 大小 | 备注 |
|------|--------|--------------|---------|------|------|
| Paraformer-large（本地默认） | 魔搭社区 modelscope.cn | 否 | ⭐⭐⭐⭐⭐ 中文最高（尤其嘈杂/口音） | ~800MB | 推荐（默认） |
| SenseVoiceSmall（可选轻量） | 魔搭社区 modelscope.cn | 否 | ⭐⭐⭐⭐ 快/轻量/多语言+情感 | ~500MB | 备选（要速度/多语言/情感时选） |
| faster-whisper large-v3 | HuggingFace | 否（需镜像） | ⭐⭐⭐ 一般 | ~3GB | **已移出默认（不推荐，本地 Paraformer 已更准）** |
| pyannote.audio（声纹分离） | HuggingFace | 是 | — | ~100MB | **已废弃（说话人分离改由 CAM++ 嵌入，免 Token）** |

- SenseVoice / Paraformer 从魔搭社区下载，**国内直连、无需 HuggingFace、无需 API Key**，离线可用。
- faster-whisper / pyannote.audio **已移出默认流程**（不推荐、可省）：本地快速档说话人分离改由 **CAM++ 说话人嵌入**（`spk_model`，随 FunASR 自动从魔搭下载、免 Token），无需 pyannote 声纹模型；云端仍走 LLM 语义切分。三档模型（SKILL.md Step 2.5）：快速 = Paraformer-large（中文精度最高，尤其嘈杂/口音场景，SenseVoice 为更快/多语言/情感的可选轻量项）；精准 = MOSS-Transcribe-Diarize 0.9B 端到端（分离最稳，~1.8GB，建议 ≥16GB 显存）；云端 = Qwen3-ASR-Flash（需 API Key）。
- **ffmpeg 安装**：Windows 缺失时运行 `python scripts/setup_env.py` 自动从 **npmmirror 二进制镜像**下载静态构建（含 ffprobe），无需访问 GitHub releases（国内常下载不动）。

## 依赖安装（务必走国内镜像）

> ⚠️ 直连国外 PyPI / GitHub 经常超时下载不动。推荐一条命令自动装好（含 ffmpeg）：
> ```bash
> python scripts/setup_env.py
> ```
> 或手动指定国内 PyPI 镜像（阿里云 / 清华 / npmmirror 任选）：

```bash
PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple

# 本地 ASR（推荐，模型从魔搭社区国内直连下载）
pip install -i $PIP_MIRROR funasr modelscope
```

> ⚠️ **faster-whisper / pyannote.audio 已移出默认安装**（不推荐、可省）：
> - faster-whisper 模型 ~3GB 且中文一般，本地 Paraformer-large 已更准；
> - pyannote.audio 声纹分离需 HF Token，已废弃——本地说话人改由 CAM++ 说话人嵌入（FunASR spk_model，魔搭下载、免 Token），云端走 LLM 语义切分。
> 若确有需要：`pip install -i $PIP_MIRROR faster-whisper pyannote.audio`

## HuggingFace 镜像（faster-whisper / pyannote 已移出默认，仅高级用户需）

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内镜像（脚本默认已设置）
unset HF_ENDPOINT                          # 直连 HuggingFace（需代理）
export HF_ENDPOINT=https://your-mirror.com # 自定义镜像
```

## 手动下载（自动下载失败时）

**SenseVoice / Paraformer（魔搭社区，国内直连）：**
```bash
pip install funasr modelscope
python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"
python -c "from modelscope import snapshot_download; snapshot_download('iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch')"
```

**faster-whisper（HuggingFace，需镜像）：**
```bash
pip install -i $PIP_MIRROR -U huggingface_hub
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download Systran/faster-whisper-large-v3 --local-dir ./whisper-large-v3
# 或浏览器打开 https://hf-mirror.com/Systran/faster-whisper-large-v3 手动下载
```

**pyannote.audio 声纹分离（需先接受条款）：**
1. 注册 HuggingFace：https://huggingface.co/join
2. 生成 Token：https://huggingface.co/settings/tokens
3. 接受模型条款：https://huggingface.co/pyannote/speaker-diarization-3.1
```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download pyannote/speaker-diarization-3.1 --token YOUR_HF_TOKEN
```

## 使用提示

- 无 HuggingFace Token 也能用：SenseVoice/Paraformer 从魔搭下载，无需 HF；CAM++ 说话人嵌入同样从魔搭随 FunASR 自动下载，也无需 Token。本地说话人分离由 CAM++ 在模型内完成；云端则走 LLM 语义切分（同云端模式，支持多说话人）。
- 如对中文转录质量要求高，本地默认已用 Paraformer-large（高精度）；如需更快/多语言/情感标签可选 SenseVoice，或在流程末尾提示用户切换云端 Qwen3-ASR-Flash。


## 快速档：SenseVoice q8 GGUF 运行时（v1.13.0 起）

单 exe + 两个 GGUF 文件，**无需 Python/torch/venv**。默认解压/放置路径 `G:/llamacpp-asr/`（runtime/、runtime-cuda/ 与 gguf/），可用 `transcribe_gguf.py --runtime-dir/--gguf-dir` 覆盖。

### ⭐ 一键自动安装（首选，v1.13.3 起）

```bash
python <skill_dir>/scripts/setup_gguf_runtime.py            # 全自动
python <skill_dir>/scripts/setup_gguf_runtime.py --verify   # 只检查
python <skill_dir>/scripts/setup_gguf_runtime.py --force    # 强制重装
```

自动完成：① `nvidia-smi` 检测 GPU/驱动（驱动 ≥580 且有 N 卡 → 自动选 CUDA 包；RTX 50 系自动选 Blackwell sm_120 包；否则 CPU AVX2 包）；② 国内多镜像下载（失败自动逐个切换）；③ SHA-256 校验后解压到 `<base>/runtime[-cuda]/` 与 `<base>/gguf/`；④ 幂等——已装且校验通过的组件自动跳过。转录时 `transcribe_gguf.py --backend auto`（默认）自动在 CPU/CUDA 间选择。

### 多镜像下载渠道（手动 / 自动脚本失败时排查，按国内可达性排序）

**① 模型文件（二选一下齐）——首选魔搭（国内直连，2026-09-07 实测 ~4MB/s）：**

| 文件 | 大小 | 魔搭（首选，国内直连） | HuggingFace（需代理） | hf-mirror（备选） |
|------|------|------|------|------|
| sensevoice-small-q8.gguf | 254MB | `https://www.modelscope.cn/models/FunAudioLLM/SenseVoiceSmall-GGUF/resolve/master/sensevoice-small-q8.gguf` | `https://huggingface.co/FunAudioLLM/SenseVoiceSmall-GGUF/resolve/main/sensevoice-small-q8.gguf` | `https://hf-mirror.com/FunAudioLLM/SenseVoiceSmall-GGUF/resolve/main/sensevoice-small-q8.gguf` |
| fsmn-vad.gguf | 1.7MB | `https://www.modelscope.cn/models/FunAudioLLM/fsmn-vad-GGUF/resolve/master/fsmn-vad.gguf` | `https://huggingface.co/FunAudioLLM/fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf` | `https://hf-mirror.com/FunAudioLLM/fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf` |

> - 还有 f16 版 `sensevoice-small-f16.gguf`（470MB，精度略高，q8 已够用）。
> - ⚠️ hf-mirror 实测：元数据可达，但 LFS 大文件会 302 到海外 xet CDN，国内直连不稳——**仅作备选**。
> - SHA-256（模型同仓库校验）：魔搭 files API 返回 `Sha256` 字段可直接核对。

**② 运行时 exe（v0.2.6，按后端选一个）：**

| 包 | 大小 | 适用 |
|------|------|------|
| funasr-llamacpp-windows-x64-avx2.zip | ~5MB | **默认 CPU**（近 10 年 x86 通用） |
| funasr-llamacpp-windows-x64-cuda.zip | **412MB** | **NVIDIA GPU 加速**（内置 cuBLAS/cublasLt CUDA 13 DLL + 静态 MSVC 运行时，无需另装 CUDA Toolkit） |
| funasr-llamacpp-windows-x64-cuda-blackwell.zip | ~412MB | RTX 50 系（sm_120）专用 |
| funasr-llamacpp-windows-x64-vulkan.zip | — | AMD/Intel 显卡 |
| linux-x64 / macos-arm64 / linux-arm64 等 | — | 其他平台，见 Release 页 |

下载地址（GitHub Release `runtime-llamacpp-v0.2.6`）：
- 直连：`https://github.com/modelscope/FunASR/releases/download/runtime-llamacpp-v0.2.6/<包名>`
- 国内打不开时用社区加速前缀拼接（按可用性逐个试，非官方、随时失效）：
  `https://ghfast.top/<原地址>`、`https://gh-proxy.com/<原地址>`、`https://gh.llkk.cc/<原地址>`
- 全部失败时到 funasr.com/deploy/llama-cpp.html 找最新镜像说明（官方文档页，国内可达）。

**CUDA 包 SHA-256 校验（2026-09-07 已验证）：** `148657911fb666b7af6ec43af2e23a0984e3259012b4c39f95631b717feb6840`（其余包的 SHA-256 见 funasr.com 部署页表格）。

### GPU 加速（CUDA 版实测，2026-09-07，RTX 4070 Ti SUPER 16GB）

199s 中文会议音频（q8 模型）：

| 指标 | CPU（AVX2） | CUDA | 提速 |
|------|------|------|------|
| 推理算力耗时 | 7.37s | 3.59s | **2.05×** |
| 端到端（含模型加载） | 8.0s | 5.3s | 1.5× |
| 实时倍率 | ~25× | ~38× | — |

- 文本质量等价：两后端输出仅 3 处 1–2 字微差（q8 量化解码固有浮动，非 GPU 引入）。
- **要求**：NVIDIA 驱动需支持 CUDA 13（R580+ 驱动；RTX 40/30/20 系用标准 cuda 包，RTX 50 系用 blackwell 包）。
- **用法**：解压 cuda.zip 为 `runtime-cuda/`，转录命令加 `--runtime-dir <路径>/runtime-cuda --backend cuda`；`transcribe_gguf.py --backend` 已支持 cpu/cuda/vulkan。Vulkan 后端适合 AMD/Intel 显卡（Windows AMD 曾有 0xC0000005 崩溃案例，v0.2.6 已修大部分，异常时回退 CPU）。
- **建议**：CPU 已 ~33 倍实时，日常够用；CUDA 版为**可选提速**，155 分钟长音频 CPU 约 5.5 分钟 → GPU 约 3 分钟。

实测速度：纯 CPU AVX2 约 33 倍实时（199s 音频 6.2s）；精度（中文 184 集基准）CER 7.99%，优于 Paraformer q8（9.78%）。
