# 模型下载与依赖说明

## 模型对比

| 模型 | 下载源 | 需要 HF Token | 中文质量 | 大小 |
|------|--------|--------------|---------|------|
| SenseVoiceSmall（本地默认） | 魔搭社区 modelscope.cn | 否 | ⭐⭐⭐⭐ 优秀 | ~500MB |
| Paraformer-large | 魔搭社区 modelscope.cn | 否 | ⭐⭐⭐⭐ 优秀 | ~800MB |
| faster-whisper large-v3 | HuggingFace | 否（需镜像） | ⭐⭐⭐ 一般 | ~3GB |
| pyannote.audio（声纹分离） | HuggingFace | 是 | — | ~100MB |

- SenseVoice / Paraformer 从魔搭社区下载，**国内直连、无需 HuggingFace、无需 API Key**，离线可用。
- faster-whisper 从 HuggingFace 下载（脚本内置镜像站自动降级）；pyannote.audio 需要 HuggingFace Token + 接受模型条款。

## 依赖安装

```bash
# 本地 ASR（推荐）
pip install funasr            # SenseVoice / Paraformer
pip install faster-whisper    # 备选（通用多语言）
pip install pyannote.audio   # 声纹分离（可选，需 HF Token）

# 自动下载依赖（模型文件）
pip install modelscope       # 如需手动触发魔搭下载
```

## HuggingFace 镜像（仅 faster-whisper / pyannote 需要）

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
pip install -U huggingface_hub
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

- 无 HuggingFace Token 也能用：SenseVoice/Paraformer 从魔搭下载，无需 HF；仅 pyannote 声纹分离需要 Token。无 Token 时可跳过声纹分离，转录后使用 LLM 语义切分说话人（同云端模式，支持多说话人）。
- 如对中文转录质量要求高，优先本地 SenseVoice，或在流程末尾提示用户切换云端 Qwen3-ASR-Flash。
