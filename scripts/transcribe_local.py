"""
faster-whisper + pyannote.audio 本地转录脚本
逐段处理 4 分钟 MP3 切片：声纹分离 + 语音转文字 + 时间戳对齐。
输出带精确时间码的转录文本。

⚠️ 质量警告：本地 faster-whisper 的中文识别准确率明显低于
   Qwen3-ASR-Flash 云端方案，仅建议在无网络/API不可用时使用。

用法: python transcribe_local.py --config config.json
配置示例见 SKILL.md Step 2

依赖: pip install faster-whisper pyannote.audio
"""

import os
import sys
import json
import argparse

# HuggingFace 模型下载镜像站列表（按优先级排列）
# 脚本会依次尝试，直到成功下载模型
HF_MIRRORS = [
    "https://hf-mirror.com",       # 国内镜像站（推荐，全量镜像）
    "https://huggingface.co",      # 官方源（需 VPN/代理）
]

# 设置默认镜像站（如用户已自行设置 HF_ENDPOINT 则不覆盖）
os.environ.setdefault("HF_ENDPOINT", HF_MIRRORS[0])


def get_hf_endpoint():
    """获取当前使用的 HF 端点"""
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co")


def print_download_help(model_name: str, model_type: str):
    """打印模型下载帮助信息（当自动下载失败时调用）"""
    endpoint = get_hf_endpoint()
    print(f"\n{'='*60}")
    print(f"❌ 模型下载失败: {model_name}")
    print(f"   当前下载源: {endpoint}")
    print(f"{'='*60}")
    print(f"\n请尝试以下方式手动下载模型：\n")

    if model_type == "whisper":
        # faster-whisper 模型对应关系
        model_map = {
            "tiny": "Systran/faster-whisper-tiny",
            "base": "Systran/faster-whisper-base",
            "small": "Systran/faster-whisper-small",
            "medium": "Systran/faster-whisper-medium",
            "large-v3": "Systran/faster-whisper-large-v3",
        }
        repo_id = model_map.get(model_name, f"Systran/faster-whisper-{model_name}")
        print(f"📦 需要下载的模型: {repo_id} (约 {get_model_size(model_name)})\n")
        print("方式 1 — 使用 hf-mirror 镜像站（推荐）:")
        print(f"  pip install -U huggingface_hub")
        print(f"  export HF_ENDPOINT=https://hf-mirror.com")
        print(f"  huggingface-cli download {repo_id} --local-dir ~/.cache/huggingface/hub/{repo_id.replace('/', '--')}\n")
        print("方式 2 — 使用 modelscope（魔搭社区）:")
        print(f"  pip install modelscope")
        print(f"  # 在 https://modelscope.cn 搜索 whisper 模型手动下载\n")
        print("方式 3 — 手动下载后指定本地路径:")
        print(f"  浏览器打开: https://hf-mirror.com/{repo_id}")
        print(f"  下载所有文件到本地目录，然后在配置中设置 model_size 为本地路径\n")
        print("方式 4 — 使用代理直连 HuggingFace:")
        print(f"  export HF_ENDPOINT=https://huggingface.co")
        print(f"  export https_proxy=http://your-proxy:port")
        print(f"  重新运行脚本\n")

    elif model_type == "pyannote":
        print(f"📦 需要下载的模型: pyannote/speaker-diarization-3.1 (约 100MB)\n")
        print("前提: 需要先注册 HuggingFace 账号并接受模型使用条款:")
        print("  1. 注册: https://huggingface.co/join")
        print("  2. 生成 Token: https://huggingface.co/settings/tokens")
        print("  3. 接受条款: https://huggingface.co/pyannote/speaker-diarization-3.1\n")
        print("方式 1 — 使用 hf-mirror 镜像站（推荐）:")
        print(f"  export HF_ENDPOINT=https://hf-mirror.com")
        print(f"  huggingface-cli download pyannote/speaker-diarization-3.1 --token YOUR_HF_TOKEN\n")
        print("方式 2 — 使用代理直连:")
        print(f"  export HF_ENDPOINT=https://huggingface.co")
        print(f"  export https_proxy=http://your-proxy:port\n")

    print(f"{'='*60}\n")


def get_model_size(model_size: str) -> str:
    sizes = {
        "tiny": "75MB",
        "base": "145MB",
        "small": "466MB",
        "medium": "1.5GB",
        "large-v3": "3GB",
    }
    return sizes.get(model_size, "未知")


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 [MM:SS] 时间码"""
    total = int(seconds)
    mm = total // 60
    ss = total % 60
    return f"[{mm:02d}:{ss:02d}]"


def load_whisper_model(model_size: str):
    """加载 faster-whisper 模型，支持多镜像站自动降级"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("错误: faster-whisper 未安装，请执行: pip install faster-whisper")
        sys.exit(1)

    print(f"加载 faster-whisper 模型: {model_size}（约 {get_model_size(model_size)}，首次使用会自动下载）...")
    print(f"  当前下载源: {get_hf_endpoint()}")

    try:
        return WhisperModel(model_size, device="auto", compute_type="auto")
    except Exception as e:
        # 尝试切换镜像站重试
        current = get_hf_endpoint()
        for mirror in HF_MIRRORS:
            if mirror == current:
                continue
            print(f"\n⚠️ 下载失败({current})，尝试切换镜像站: {mirror}")
            os.environ["HF_ENDPOINT"] = mirror
            try:
                return WhisperModel(model_size, device="auto", compute_type="auto")
            except Exception:
                continue
        # 所有镜像都失败，打印帮助信息
        print_download_help(model_size, "whisper")
        print(f"原始错误: {e}")
        sys.exit(1)


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
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        return pipeline
    except Exception as e:
        current = get_hf_endpoint()
        for mirror in HF_MIRRORS:
            if mirror == current:
                continue
            print(f"\n⚠️ 下载失败({current})，尝试切换镜像站: {mirror}")
            os.environ["HF_ENDPOINT"] = mirror
            try:
                pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=hf_token,
                )
                return pipeline
            except Exception:
                continue
        print_download_help("pyannote/speaker-diarization-3.1", "pyannote")
        print(f"原始错误: {e}")
        sys.exit(1)


def transcribe_segment(whisper_model, audio_path: str) -> list:
    """用 faster-whisper 转录单个音频段，返回带时间戳的文本片段列表"""
    print(f"  转录中: {audio_path}")
    segments_gen, info = whisper_model.transcribe(
        audio_path,
        language="zh",
        beam_size=5,
        vad_filter=True,
    )

    results = []
    for seg in segments_gen:
        text = seg.text.strip()
        if text:
            results.append({
                "start": seg.start,
                "end": seg.end,
                "text": text,
            })
    print(f"    生成 {len(results)} 个文本片段")
    return results


def diarize_segment(diarization_pipeline, audio_path: str) -> list:
    """用 pyannote.audio 对单个音频段做声纹分离，返回说话人轮次列表"""
    print(f"  声纹分离中: {audio_path}")
    diarization = diarization_pipeline(
        audio_path,
        min_speakers=2,
        max_speakers=2,
    )

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker,
        })
    print(f"    识别到 {len(set(t['speaker'] for t in turns))} 个说话人, {len(turns)} 个轮次")
    return turns


def align_speakers(whisper_segments: list, diarization_turns: list) -> list:
    """将 whisper 文本片段与 pyannote 说话人标签对齐（取片段中点对应的说话人）"""
    aligned = []
    for wseg in whisper_segments:
        mid = (wseg["start"] + wseg["end"]) / 2
        best_speaker = "UNKNOWN"

        # 找到包含中点的说话人轮次
        for turn in diarization_turns:
            if turn["start"] <= mid <= turn["end"]:
                best_speaker = turn["speaker"]
                break

        # 如果中点没命中任何轮次，找最近的
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
    """合并所有段的对齐结果，将时间戳加上段偏移量"""
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


def generate_raw_text(merged: list) -> str:
    """生成带时间码和 SPEAKER 标签的原始文本，供 LLM 做角色映射"""
    lines = []
    current_speaker = None
    current_texts = []
    current_start = 0.0

    for item in merged:
        speaker = item["speaker"]
        if speaker != current_speaker:
            # 输出上一个说话人的内容
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

    # 输出最后一个说话人的内容
    if current_speaker is not None and current_texts:
        ts = format_timestamp(current_start)
        lines.append(f"{ts} **{current_speaker}**")
        lines.append("".join(current_texts))
        lines.append("")

    return "\n".join(lines)


def generate_markdown(merged: list, title: str, video_file: str, model_size: str) -> str:
    """生成带时间码和 SPEAKER 标签的 Markdown 文档"""
    lines = [
        f"# {title}",
        "",
        f"![人物静帧](人物静帧.jpg)",
        "",
        f"> 视频文件: {video_file}",
        f"> 转录模型: faster-whisper ({model_size}) + pyannote.audio 声纹分离",
        f"> 说话人识别: pyannote.audio 声纹分离（SPEAKER 标签，待 LLM 角色映射）",
        f"> 时间码: 精确到秒（基于 whisper 时间戳）",
        "",
        "---",
        "",
    ]

    # 合并同一说话人的连续片段，并添加时间码
    current_speaker = None
    current_texts = []
    current_start = 0.0

    for item in merged:
        speaker = item["speaker"]
        if speaker != current_speaker:
            # 输出上一个说话人的内容
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

    # 输出最后一个说话人的内容
    if current_speaker is not None and current_texts:
        ts = format_timestamp(current_start)
        lines.append(f"**{current_speaker}** {ts}")
        lines.append("".join(current_texts))
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="faster-whisper + pyannote.audio 本地转录（带时间码）")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")
    parser.add_argument("--model", default=None, help="覆盖配置中的模型大小 (tiny/base/small/medium/large-v3)")

    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    output_dir = config.get("output_dir", ".")
    doc_title = config.get("title", "转录文档")
    video_file = config.get("video_file", "")
    model_size = args.model or config.get("model_size", "medium")
    hf_token = config.get("hf_token", "")
    segments = config.get("segments", [])

    if not segments:
        print("错误: 配置中缺少 segments（音频切段列表）")
        sys.exit(1)

    if not hf_token:
        print("错误: 配置中缺少 hf_token（HuggingFace Access Token，pyannote.audio 需要）")
        print("获取方式: https://huggingface.co/settings/tokens")
        print("并接受模型条款: https://huggingface.co/pyannote/speaker-diarization-3.1")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"开始本地转录 (faster-whisper {model_size} + pyannote.audio)")
    print(f"⚠️ 注意: 本地转录中文质量明显差于云端 Qwen3-ASR-Flash")
    print(f"共 {len(segments)} 个音频段")
    print(f"{'='*60}\n")

    # 加载模型
    whisper_model = load_whisper_model(model_size)
    diarization_pipeline = load_diarization_pipeline(hf_token)

    # 逐段处理
    all_aligned = []
    segment_offsets = []

    for i, seg in enumerate(segments):
        seg_file = seg["file"]
        seg_offset = seg.get("offset", 0)
        segment_offsets.append(seg_offset)

        print(f"\n--- 段 {i+1}/{len(segments)}: {seg_file} (偏移 {seg_offset}s) ---")

        # a. pyannote.audio 声纹分离
        diarization_turns = diarize_segment(diarization_pipeline, seg_file)

        # b. faster-whisper 转录
        whisper_segments = transcribe_segment(whisper_model, seg_file)

        # c. 时间戳对齐
        aligned = align_speakers(whisper_segments, diarization_turns)
        all_aligned.append(aligned)

        # 打印该段结果预览
        for item in aligned[:5]:
            print(f"  [{item['start']:.1f}-{item['end']:.1f}] {item['speaker']}: {item['text']}")
        if len(aligned) > 5:
            print(f"  ... 共 {len(aligned)} 个片段")

    # 合并所有段
    merged = merge_aligned_segments(all_aligned, segment_offsets)
    print(f"\n合并完成: 共 {len(merged)} 个片段")

    # 保存原始文本（带时间码 + SPEAKER 标签）
    raw_text = generate_raw_text(merged)
    raw_path = os.path.join(output_dir, f"{doc_title}_raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_text)
    print(f"原始文本（带时间码）保存: {raw_path}")

    # 生成 Markdown（带时间码 + SPEAKER 标签）
    md_content = generate_markdown(merged, doc_title, video_file, model_size)
    md_path = os.path.join(output_dir, f"{doc_title}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n✅ Markdown 文档保存: {md_path}")

    # 统计说话人分布
    speaker_counts = {}
    for item in merged:
        speaker_counts[item["speaker"]] = speaker_counts.get(item["speaker"], 0) + 1
    print(f"\n说话人片段分布: {speaker_counts}")

    print("\n🎉 本地转录完成！请继续执行 Step 3.5 LLM 角色映射（保留时间码）。")
    return md_path


if __name__ == "__main__":
    main()
