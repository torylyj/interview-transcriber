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
  "title": "清华26-0607 街头采访转录文本",
  "video_file": "VID20260607150604.mp4",
  "frame_path": "人物静帧.jpg",
  "output_dir": "./output",
  "segments": [
    {"file": "./_seg1.mp3", "offset": 0},
    {"file": "./_seg2.mp3", "offset": 240},
    {"file": "./_seg3.mp3", "offset": 480},
    {"file": "./_seg4.mp3", "offset": 720}
  ]
}
```

## 音频分段要求

- 每段不超过 5 分钟（Qwen3-ASR-Flash 的限制）
- 使用 ffmpeg 分段：
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
