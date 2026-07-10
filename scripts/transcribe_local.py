"""
本地转录脚本 — 多模型支持
支持三种本地转录引擎，按中文识别质量从高到低排列：
  1. SenseVoice (FunASR/阿里达摩院) — 中文最优，魔搭社区下载，无需 HuggingFace
  2. Paraformer (FunASR/阿里达摩院) — 中文优秀，魔搭社区下载，无需 HuggingFace
  3. faster-whisper large-v3 (OpenAI Whisper) — 通用型，HuggingFace 下载

声纹分离统一使用 pyannote.audio (需 HuggingFace Token)。

用法: python transcribe_local.py --config config.json [--model sensevoice|paraformer|whisper]
配置示例见 SKILL.md Step 2
"""

import os
import sys
import json
import argparse

# ─── HuggingFace 镜像站（pyannote.audio 用） ───────────────────
HF_MIRRORS = [
    "https://hf-mirror.com",       # 国内镜像站（推荐，全量镜像）
    "https://huggingface.co",      # 官方源（需 VPN/代理）
]
os.environ.setdefault("HF_ENDPOINT", HF_MIRRORS[0])

# ─── 模型定义 ──────────────────────────────────────────────────
# 每个模型后端的配置信息
MODEL_CONFIGS = {
    "sensevoice": {
        "name": "SenseVoiceSmall",
        "source": "ModelScope 魔搭社区",
        "source_url": "https://modelscope.cn/models/iic/SenseVoiceSmall",
        "size": "~500MB",
        "quality": "⭐⭐⭐⭐ (中文优秀，接近云端)",
        "description": "阿里达摩院 SenseVoice，专为中文优化，支持多语言/情感识别",
        "funasr_model": "iic/SenseVoiceSmall",
        "needs_hf": False,  # 不需要 HuggingFace，从 ModelScope 下载
    },
    "paraformer": {
        "name": "Paraformer-large",
        "source": "ModelScope 魔搭社区",
        "source_url": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "size": "~800MB",
        "quality": "⭐⭐⭐⭐ (中文优秀)",
        "description": "阿里达摩院 Paraformer，中文大规模预训练，自带 VAD + 标点恢复",
        "funasr_model": "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "funasr_vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "funasr_punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
        "needs_hf": False,
    },
    "whisper": {
        "name": "faster-whisper large-v3",
        "source": "HuggingFace",
        "source_url": "https://huggingface.co/Systran/faster-whisper-large-v3",
        "size": "~3GB",
        "quality": "⭐⭐⭐ (中文一般，人名/专有名词错误率较高)",
        "description": "OpenAI Whisper large-v3，通用多语言模型，中文非最优",
        "whisper_model": "large-v3",
        "needs_hf": True,
    },
}


def get_hf_endpoint():
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co")


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 [MM:SS] 时间码"""
    total = int(seconds)
    mm = total // 60
    ss = total % 60
    return f"[{mm:02d}:{ss:02d}]"


# ─── SenseVoice / Paraformer 后端 (FunASR) ─────────────────────

def load_funasr_model(model_key: str):
    """加载 FunASR 模型（SenseVoice 或 Paraformer），从 ModelScope 自动下载"""
    try:
        from funasr import AutoModel
    except ImportError:
        print("错误: funasr 未安装，请执行: pip install funasr")
        print("  FunASR 是阿里达摩院开源语音识别工具包")
        print("  模型从 ModelScope 魔搭社区自动下载，无需 HuggingFace")
        sys.exit(1)

    cfg = MODEL_CONFIGS[model_key]
    print(f"加载 {cfg['name']} 模型（约 {cfg['size']}，从 {cfg['source']} 自动下载）...")

    kwargs = {
        "model": cfg["funasr_model"],
        "trust_remote_code": True,
    }
    # Paraformer 额外加载 VAD 和标点模型
    if "funasr_vad" in cfg:
        kwargs["vad_model"] = cfg["funasr_vad"]
    if "funasr_punc" in cfg:
        kwargs["punc_model"] = cfg["funasr_punc"]

    try:
        model = AutoModel(**kwargs)
        print(f"  ✅ {cfg['name']} 加载成功")
        return model, model_key
    except Exception as e:
        print(f"\n❌ {cfg['name']} 模型加载失败: {e}")
        print(f"  下载源: {cfg['source']} ({cfg['source_url']})")
        print(f"\n手动下载方式:")
        print(f"  pip install modelscope")
        print(f"  python -c \"from modelscope import snapshot_download; snapshot_download('{cfg['funasr_model']}')\"")
        sys.exit(1)


def transcribe_funasr(model, audio_path: str, model_key: str) -> list:
    """用 FunASR (SenseVoice/Paraformer) 转录单个音频段"""
    cfg = MODEL_CONFIGS[model_key]
    print(f"  转录中 ({cfg['name']}): {audio_path}")

    try:
        if model_key == "sensevoice":
            result = model.generate(
                input=audio_path,
                language="zh",
                use_itn=True,
            )
        else:  # paraformer
            result = model.generate(
                input=audio_path,
                batch_size_s=300,
            )
    except Exception as e:
        print(f"  ❌ 转录失败: {e}")
        return []

    # 解析结果
    segments = []
    if not result:
        return segments

    res = result[0]
    raw_text = res.get("text", "")

    # Paraformer 带 VAD 时返回分段结果
    sentence_info = res.get("sentence_info", [])
    if sentence_info:
        for s in sentence_info:
            text = s.get("text", "").strip()
            if text:
                segments.append({
                    "start": s.get("start", 0) / 1000.0,  # ms → s
                    "end": s.get("end", 0) / 1000.0,
                    "text": text,
                })
    else:
        # SenseVoice 或无 VAD 的 Paraformer：整段文本
        if raw_text:
            # SenseVoice 输出可能含 < |zh| > 等语言标签，清理
            clean = raw_text
            for tag in ["<|zh|>", "<|en|>", "<|ja|>", "<|ko|>", "<|nospeech|>", "<|HAPPY|>", "<|SAD|>", "<|ANGRY|>", "<|NEUTRAL|>", "<|FEARFUL|>", "<|DISGUSTED|>", "<|SURPRISED|>", "<|Speech|>", "<|BGM|>", "<|Laughter|>", "<|Applause|>"]:
                clean = clean.replace(tag, "")
            clean = clean.strip()
            if clean:
                segments.append({
                    "start": 0.0,
                    "end": 0.0,
                    "text": clean,
                })

    print(f"    生成 {len(segments)} 个文本片段")
    return segments


# ─── faster-whisper 后端 ────────────────────────────────────────

def load_whisper_model(model_size: str = "large-v3"):
    """加载 faster-whisper 模型，支持多镜像站自动降级"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("错误: faster-whisper 未安装，请执行: pip install faster-whisper")
        sys.exit(1)

    sizes = {"tiny": "75MB", "base": "145MB", "small": "466MB", "medium": "1.5GB", "large-v3": "3GB"}
    print(f"加载 faster-whisper 模型: {model_size}（约 {sizes.get(model_size, '?')}，首次使用会自动下载）...")
    print(f"  当前下载源: {get_hf_endpoint()}")

    try:
        return WhisperModel(model_size, device="auto", compute_type="auto"), model_size
    except Exception as e:
        current = get_hf_endpoint()
        for mirror in HF_MIRRORS:
            if mirror == current:
                continue
            print(f"\n⚠️ 下载失败({current})，尝试切换镜像站: {mirror}")
            os.environ["HF_ENDPOINT"] = mirror
            try:
                return WhisperModel(model_size, device="auto", compute_type="auto"), model_size
            except Exception:
                continue
        # 全部失败
        print(f"\n❌ faster-whisper {model_size} 下载失败（所有镜像站均不可用）")
        print(f"  手动下载: https://hf-mirror.com/Systran/faster-whisper-{model_size}")
        print(f"  或使用 SenseVoice/Paraformer 模型（从魔搭社区下载，无需 HuggingFace）")
        print(f"原始错误: {e}")
        sys.exit(1)


def transcribe_whisper(model, audio_path: str, model_size: str) -> list:
    """用 faster-whisper 转录单个音频段"""
    print(f"  转录中 (faster-whisper {model_size}): {audio_path}")
    segments_gen, info = model.transcribe(
        audio_path,
        language="zh",
        beam_size=5,
        vad_filter=True,
    )

    results = []
    for seg in segments_gen:
        text = seg.text.strip()
        if text:
            results.append({"start": seg.start, "end": seg.end, "text": text})
    print(f"    生成 {len(results)} 个文本片段")
    return results


# ─── pyannote.audio 声纹分离 ───────────────────────────────────

def load_diarization_pipeline(hf_token: str):
    """加载 pyannote.audio 声纹分离模型，支持多镜像站自动降级"""
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        print("错误: pyannote.audio 未安装，请执行: pip install pyannote.audio")
        sys.exit(1)

    print("加载 pyannote.audio 声纹分离模型（约 100MB，首次使用会自动下载）...")
    print(f"  当前下载源: {get_hf_endpoint()}")

    try:
        return Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
    except Exception as e:
        current = get_hf_endpoint()
        for mirror in HF_MIRRORS:
            if mirror == current:
                continue
            print(f"\n⚠️ 下载失败({current})，尝试切换镜像站: {mirror}")
            os.environ["HF_ENDPOINT"] = mirror
            try:
                return Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=hf_token,
                )
            except Exception:
                continue
        print(f"\n❌ pyannote.audio 模型下载失败（所有镜像站均不可用）")
        print(f"  需要 HuggingFace Token + 接受模型条款:")
        print(f"  1. 注册: https://huggingface.co/join")
        print(f"  2. Token: https://huggingface.co/settings/tokens")
        print(f"  3. 接受条款: https://huggingface.co/pyannote/speaker-diarization-3.1")
        print(f"  手动下载: export HF_ENDPOINT=https://hf-mirror.com && huggingface-cli download pyannote/speaker-diarization-3.1 --token YOUR_TOKEN")
        print(f"原始错误: {e}")
        sys.exit(1)


def diarize_segment(diarization_pipeline, audio_path: str) -> list:
    """用 pyannote.audio 对单个音频段做声纹分离"""
    print(f"  声纹分离中: {audio_path}")
    diarization = diarization_pipeline(audio_path, min_speakers=2, max_speakers=2)

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({"start": turn.start, "end": turn.end, "speaker": speaker})
    print(f"    识别到 {len(set(t['speaker'] for t in turns))} 个说话人, {len(turns)} 个轮次")
    return turns


# ─── 对齐 & 合并 ────────────────────────────────────────────────

def align_speakers(asr_segments: list, diarization_turns: list) -> list:
    """将 ASR 文本片段与 pyannote 说话人标签对齐"""
    aligned = []
    for wseg in asr_segments:
        mid = (wseg["start"] + wseg["end"]) / 2 if wseg["end"] > 0 else wseg["start"]
        best_speaker = "UNKNOWN"

        for turn in diarization_turns:
            if turn["start"] <= mid <= turn["end"]:
                best_speaker = turn["speaker"]
                break

        if best_speaker == "UNKNOWN" and diarization_turns:
            min_dist = float("inf")
            for turn in diarization_turns:
                dist = min(abs(mid - turn["start"]), abs(mid - turn["end"]))
                if dist < min_dist:
                    min_dist = dist
                    best_speaker = turn["speaker"]

        aligned.append({
            "speaker": best_speaker,
            "text": wseg["text"],
            "start": wseg["start"],
            "end": wseg["end"],
        })
    return aligned


def merge_aligned_segments(all_aligned: list, segment_offsets: list) -> list:
    """合并所有段的对齐结果，加上段偏移量"""
    merged = []
    for aligned, offset in zip(all_aligned, segment_offsets):
        for item in aligned:
            merged.append({
                "speaker": item["speaker"],
                "text": item["text"],
                "start": item["start"] + offset,
                "end": item["end"] + offset,
            })
    return merged


# ─── 输出生成 ──────────────────────────────────────────────────

def generate_raw_text(merged: list) -> str:
    """生成带时间码和 SPEAKER 标签的原始文本"""
    lines = []
    current_speaker = None
    current_texts = []
    current_start = 0.0

    for item in merged:
        speaker = item["speaker"]
        if speaker != current_speaker:
            if current_speaker is not None and current_texts:
                ts = format_timestamp(current_start)
                lines.append(f"{ts} **{current_speaker}**")
                lines.append("".join(current_texts))
                lines.append("")
            current_speaker = speaker
            current_texts = [item["text"]]
            current_start = item["start"]
        else:
            current_texts.append(item["text"])

    if current_speaker is not None and current_texts:
        ts = format_timestamp(current_start)
        lines.append(f"{ts} **{current_speaker}**")
        lines.append("".join(current_texts))
        lines.append("")

    return "\n".join(lines)


def generate_markdown(merged: list, title: str, video_file: str, model_name: str) -> str:
    """生成带时间码和 SPEAKER 标签的 Markdown 文档"""
    lines = [
        f"# \U0001F4CC {title}",
        "",
        '<div align="center">',
        '<img src="人物静帧.jpg" width="280" />',
        "</div>",
        "",
        "---",
        "",
        "> \U0001F4CB **文档信息**",
        ">",
        f"> \U0001F3AC 视频文件：{video_file}",
        f"> \U0001F6E0\uFE0F 转录模型：{model_name}",
        "> \U0001F50D 说话人识别：pyannote.audio 声纹分离（SPEAKER 标签，待 LLM 角色映射）",
        "> \u23F1\uFE0F 时间码：精确到秒",
        "",
        "---",
        "",
        "## \U0001F4AC 采访记录",
        "",
    ]

    current_speaker = None
    current_texts = []
    current_start = 0.0

    for item in merged:
        speaker = item["speaker"]
        if speaker != current_speaker:
            if current_speaker is not None and current_texts:
                ts = format_timestamp(current_start)
                lines.append(f"**{current_speaker}** {ts}")
                lines.append("".join(current_texts))
                lines.append("")
            current_speaker = speaker
            current_texts = [item["text"]]
            current_start = item["start"]
        else:
            current_texts.append(item["text"])

    if current_speaker is not None and current_texts:
        ts = format_timestamp(current_start)
        lines.append(f"**{current_speaker}** {ts}")
        lines.append("".join(current_texts))
        lines.append("")

    return "\n".join(lines)


# ─── 主流程 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="本地转录（多模型支持 + 声纹分离 + 时间码）")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")
    parser.add_argument(
        "--model",
        default=None,
        choices=["sensevoice", "paraformer", "whisper"],
        help="转录模型: sensevoice (推荐) | paraformer | whisper",
    )

    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    output_dir = config.get("output_dir", ".")
    doc_title = config.get("title", "转录文档")
    video_file = config.get("video_file", "")
    hf_token = config.get("hf_token", "")
    segments = config.get("segments", [])

    # 确定模型
    model_key = args.model or config.get("model", "sensevoice")
    if model_key not in MODEL_CONFIGS:
        print(f"错误: 未知模型 '{model_key}'，可选: {', '.join(MODEL_CONFIGS.keys())}")
        sys.exit(1)

    model_cfg = MODEL_CONFIGS[model_key]

    if not segments:
        print("错误: 配置中缺少 segments（音频切段列表）")
        sys.exit(1)

    if not hf_token:
        print("⚠️ 未配置 hf_token，将跳过声纹分离（仅转录，不区分说话人）")
        print("  pyannote.audio 需要 HuggingFace Token:")
        print("  1. 注册: https://huggingface.co/join")
        print("  2. Token: https://huggingface.co/settings/tokens")
        print("  3. 接受条款: https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("  无 Token 时可直接用云端模式（LLM 语义切分说话人），或转录后手动处理\n")

    print(f"\n{'='*60}")
    print(f"开始本地转录")
    print(f"  模型: {model_cfg['name']} ({model_cfg['quality']})")
    print(f"  下载源: {model_cfg['source']}")
    print(f"  大小: {model_cfg['size']}")
    print(f"  声纹分离: {'pyannote.audio' if hf_token else '跳过（无 Token）'}")
    print(f"  共 {len(segments)} 个音频段")
    print(f"{'='*60}\n")

    # 加载 ASR 模型
    if model_key in ("sensevoice", "paraformer"):
        asr_model, asr_key = load_funasr_model(model_key)
    else:
        whisper_size = model_cfg.get("whisper_model", "large-v3")
        asr_model, asr_key = load_whisper_model(whisper_size)

    # 加载声纹分离模型
    diarization_pipeline = load_diarization_pipeline(hf_token) if hf_token else None

    # 逐段处理
    all_aligned = []
    segment_offsets = []

    for i, seg in enumerate(segments):
        seg_file = seg["file"]
        seg_offset = seg.get("offset", 0)
        segment_offsets.append(seg_offset)

        print(f"\n--- 段 {i+1}/{len(segments)}: {seg_file} (偏移 {seg_offset}s) ---")

        # a. ASR 转录
        if model_key in ("sensevoice", "paraformer"):
            asr_segments = transcribe_funasr(asr_model, seg_file, model_key)
        else:
            asr_segments = transcribe_whisper(asr_model, seg_file, asr_key)

        if not asr_segments:
            print("  ⚠️ 本段无转录结果，跳过")
            all_aligned.append([])
            continue

        # b. 声纹分离 + 对齐
        if diarization_pipeline:
            diarization_turns = diarize_segment(diarization_pipeline, seg_file)
            aligned = align_speakers(asr_segments, diarization_turns)
        else:
            # 无声纹分离，全部标记为 SPEAKER_00
            aligned = [{"speaker": "SPEAKER_00", "text": s["text"], "start": s["start"], "end": s["end"]} for s in asr_segments]

        all_aligned.append(aligned)

        # 预览
        for item in aligned[:5]:
            print(f"  [{item['start']:.1f}-{item['end']:.1f}] {item['speaker']}: {item['text']}")
        if len(aligned) > 5:
            print(f"  ... 共 {len(aligned)} 个片段")

    # 合并
    merged = merge_aligned_segments(all_aligned, segment_offsets)
    print(f"\n合并完成: 共 {len(merged)} 个片段")

    # 保存原始文本
    raw_text = generate_raw_text(merged)
    raw_path = os.path.join(output_dir, f"{doc_title}_raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_text)
    print(f"原始文本（带时间码）保存: {raw_path}")

    # 生成 Markdown
    md_content = generate_markdown(merged, doc_title, video_file, model_cfg["name"])
    md_path = os.path.join(output_dir, f"{doc_title}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n✅ Markdown 文档保存: {md_path}")

    # 统计
    speaker_counts = {}
    for item in merged:
        speaker_counts[item["speaker"]] = speaker_counts.get(item["speaker"], 0) + 1
    print(f"\n说话人片段分布: {speaker_counts}")

    print(f"\n🎉 本地转录完成！（模型: {model_cfg['name']}）")
    if not hf_token:
        print("⚠️ 未做声纹分离，请在 Step 3.5 中使用 LLM 语义切分说话人（同云端模式）")
    else:
        print("请继续执行 Step 3.5 LLM 角色映射（保留时间码）。")
    return md_path


if __name__ == "__main__":
    main()
