# DashScope (阿里云百炼) API 配置指南

## 获取 API Key

1. 打开 https://bailian.console.aliyun.com/?tab=model#/api-key
2. 用阿里云账号登录（新用户注册有免费额度）
3. 点击"创建 API Key"，复制生成的 `sk-xxxx` 格式密钥

## 安装依赖

```bash
pip install dashscope
```

## 转录配置文件示例 (config.json)

```json
{
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "title": "清华26-0607 采访转录文本",
  "source_file": "VID20260607150604.mp4",
  "input_type": "video",
  "audio_file": "输出.mp3",
  "frame_path": "人物静帧.jpg",
  "output_dir": "./output"
}
```

> 说明：
> - `source_file`：原始输入文件名（视频或音频均可）
> - `input_type`：`video` 或 `audio`（音频输入时 `frame_path` 设为 `null`，不输出静帧）
> - `audio_file`：Step 1 产出的工作音频（视频转出的 MP3，或音频本身）
> - `segments` **不在本文件预填**，由 Step 2.6 在选定转录方式后根据是否切段写入
>   - 切段时：`[{"file": "_seg1.mp3", "offset": 0}, {"file": "_seg2.mp3", "offset": 240}, ...]`
>   - 不切段时：`[{"file": "输出.mp3", "offset": 0}]`

## 音频分段要求（Step 2.6 决策）

- 云端（Qwen3-ASR-Flash）单次调用上限 **5 分钟**：超过 5 分钟必须切段（按 4 分钟/段，留余量）
- 本地（SenseVoice / Paraformer / whisper）无硬限制：长音频由模型自动切段控制内存，短音频整段直接传（均不询问用户）
- 使用 ffmpeg 分段（4 分钟/段）：
  ```bash
  ffmpeg -i input.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0 -t 240 _seg1.mp3 -y
  ffmpeg -i input.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 240 -t 240 _seg2.mp3 -y
  ```
- 每个分段的 `offset` 为该段在原始音频中的起始时间（秒）

## 模型说明

- **qwen3-asr-flash**: 快速版，适合一般转录，速度快、成本低
- **fun-asr**: 专业版，支持说话人分离（diarization），但需要 OSS 文件上传，处理时间更长

## 费用

新用户有免费额度。16 分钟音频（4 段 × 4 分钟）调用的费用极低，通常在免费额度内。
