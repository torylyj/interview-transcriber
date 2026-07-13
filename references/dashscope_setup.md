# DashScope（阿里云百炼）配置与统一调用约定

## 获取 API Key

1. 打开 https://bailian.console.aliyun.com/?tab=model#/api-key
2. 用阿里云账号登录（新用户注册有免费额度）
3. 点击"创建 API Key"，复制生成的 `sk-xxxx` 格式密钥

## 安装依赖

```bash
# 务必走国内 PyPI 镜像（直连国外常超时）
PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple
pip install -i $PIP_MIRROR -U dashscope   # 务必用较新版本，旧版本无 qwen3-asr-flash 等模型
pip install -i $PIP_MIRROR pillow         # 静帧清晰度计算（extract_frame.py）用
```

## 统一调用约定（重要 · 版本兼容）

本技能用到 DashScope 两个**不同**的 API 面，请勿混用：

| 用途 | 接口 | 模型 | 说明 |
|------|------|------|------|
| 音频转录 | `dashscope.MultiModalConversation.call` | `qwen3-asr-flash` | **必须**用多模态接口（传入 `audio` 文件 URL），不能用 `Generation` / `Transcription` |
| 文本任务（说话人识别 / 摘要） | `dashscope.Generation.call` | `qwen-plus` | 统一通过 `scripts/call_qwen.py` 调用，结果格式 `message` |

**设置 API Key（两种等价方式，任选其一）：**
```python
dashscope.api_key = "sk-xxxx"          # 代码中直接赋值
# 或
import os
os.environ["DASHSCOPE_API_KEY"] = "sk-xxxx"   # 推荐，call_qwen.py 默认读取此环境变量
```

**版本兼容风险提示：**
- `qwen3-asr-flash` 是较新的 ASR 模型，旧版 dashscope SDK 会报 `model_not_found`，务必 `pip install -U dashscope`。
- **不要用 `dashscope.Transcription.call`**：旧接口签名已变更，调用会失败；音频转录统一用 `MultiModalConversation.call`。
- 文本任务统一走 `scripts/call_qwen.py`（内部用 `Generation.call`），避免在多处重复写调用代码导致的版本不一致。

**示例（文本任务，方式 B）：**
```bash
# 说话人识别 / 摘要生成
python <skill_dir>/scripts/call_qwen.py --prompt-file speaker_prompt.txt --model qwen-plus
echo "..." | python <skill_dir>/scripts/call_qwen.py --model qwen-plus
```
完整 prompt 模板见 references/prompts.md。

## 转录配置文件示例 (config.json)

**云端转录（mode: cloud）：**
```json
{
  "mode": "cloud",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "title": "26-0509 车辆学院直博生",
  "source_file": "输入.mp4",
  "input_type": "video",
  "audio_file": "输出.mp3",
  "frame_path": "人物静帧.jpg",
  "output_dir": "./output"
}
```

**本地转录（mode: local）：**
```json
{
  "mode": "local",
  "title": "26-0509 车辆学院直博生",
  "source_file": "输入.mp4",
  "input_type": "video",
  "audio_file": "输出.mp3",
  "frame_path": "人物静帧.jpg",
  "output_dir": "./output",
  "model": "paraformer"
}
```

> 说明：
> - `source_file`：原始输入文件名（视频或音频均可）
> - `input_type`：`video` 或 `audio`（音频输入时 `frame_path` 设为 `null`，不输出静帧）
> - `audio_file`：Step 1 产出的工作音频（视频转出的 MP3，或音频本身）
> - `segments` **不在本文件预填**，由 Step 2.6 在选定转录方式后根据是否切段写入
>   - 切段时：`[{"file": "_seg1.mp3", "offset": 0}, {"file": "_seg2.mp3", "offset": 240}, ...]`
>   - 不切段时：`[{"file": "输出.mp3", "offset": 0}]`
> - 说话人：本地由 CAM++ 在模型内分离（免 HF Token、无需指定人数）；云端 Qwen3-ASR-Flash 无原生分离，由 Step 3.5 LLM 语义切分（免 HF Token），群访同样支持

## 音频分段要求（Step 2.6 决策）

- 云端（Qwen3-ASR-Flash）单次调用上限 **5 分钟**：超过必须切段（按 4 分钟/段，留余量）
- 本地（SenseVoice / Paraformer）无硬限制：长音频由模型自动切段控制内存，短音频整段直接传（均不询问用户）
- 切段/合并 ffmpeg 命令见 references/segment_commands.md

## 模型说明

- **qwen3-asr-flash**：高准确率中文 ASR，标点断句自然，需联网 + API Key
- **qwen-plus**：通用文本大模型，用于说话人识别 / 摘要（Step 3.5/3.6 方式 B）

## 费用

新用户有免费额度。16 分钟音频（4 段 × 4 分钟）调用的费用极低，通常在免费额度内。
