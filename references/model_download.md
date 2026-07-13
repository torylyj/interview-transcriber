# 模型下载与依赖说明

## 模型对比

| 模型 | 下载源 | 需要 HF Token | 中文质量 | 大小 | 备注 |
|------|--------|--------------|---------|------|------|
| Paraformer-large（本地默认） | 魔搭社区 modelscope.cn | 否 | ⭐⭐⭐⭐⭐ 中文最高（尤其嘈杂/口音） | ~800MB | 推荐（默认） |
| SenseVoiceSmall（可选轻量） | 魔搭社区 modelscope.cn | 否 | ⭐⭐⭐⭐ 快/轻量/多语言+情感 | ~500MB | 备选（要速度/多语言/情感时选） |
| faster-whisper large-v3 | HuggingFace | 否（需镜像） | ⭐⭐⭐ 一般 | ~3GB | **已移出默认（不推荐，本地 Paraformer 已更准）** |
| pyannote.audio（声纹分离） | HuggingFace | 是 | — | ~100MB | **已废弃（说话人分离改由 CAM++ 嵌入，免 Token）** |

- SenseVoice / Paraformer 从魔搭社区下载，**国内直连、无需 HuggingFace、无需 API Key**，离线可用。
- faster-whisper / pyannote.audio **已移出默认流程**（不推荐、可省）：本地说话人分离改由 **CAM++ 说话人嵌入**（`spk_model`，随 FunASR 自动从魔搭下载、免 Token），无需 pyannote 声纹模型；云端仍走 LLM 语义切分。本地默认 Paraformer-large 中文精度最高（尤其嘈杂/口音场景），SenseVoice 作为更快/多语言/情感的可选轻量项，无需 ~3GB 的 whisper。
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
