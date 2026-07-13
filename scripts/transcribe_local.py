"""
本地转录脚本 — 阿里达摩院中文模型（魔搭社区国内直连）

支持两种本地转录引擎（魔搭社区国内直连，无需 HuggingFace）：
  - Paraformer-large（默认）：中文高精度，尤其嘈杂/口音场景更稳；
    由 FunASR 流水线内置 FSMN-VAD（真实句级时间码）、CT-Transformer
    标点恢复、CAM++ 说话人嵌入（spk_model）一气呵成——时间码、标点、
    说话人分离全部在单次 generate() 内产出，无需 LLM 后处理。
  - SenseVoice-small（可选轻量项）：更快、体积小（~500MB）、支持多语言
    与情感/事件标签；中文精度略逊于 Paraformer-large，时间码需插值估算。

说话人分离：Paraformer-large 通过 CAM++ 说话人嵌入（spk_model）在模型内
完成，返回每句 speaker id（按声纹自动聚类，无需预先指定人数）；不再依赖
LLM 逐句语义切分或 pyannote.audio。模型只给「谁在何时说」，说话人中性命名
（说话人1/2/3……）由轻量步骤完成（见 build_document.py）。

用法: python transcribe_local.py --config config.json [--model sensevoice|paraformer]
配置示例见 SKILL.md Step 2
"""

import os
import sys
import json
import argparse
import threading
import functools
from datetime import datetime

# 所有 print 立即刷新，避免长耗时步骤的输出被缓冲，导致调用方（Agent）误以为卡死
print = functools.partial(print, flush=True)


def with_timeout(seconds, func, *args, **kwargs):
    """在子线程中运行阻塞调用并加硬超时。

    超时或异常都让它**快速失败**、绝不无限挂起。超时直接 os._exit
    终止进程，保证 bash 命令一定能返回（不会让上层 Agent 永久卡在等待里）。
    """
    box = {}

    def _run():
        try:
            box["val"] = func(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        print(
            f"❌ 操作超时（>{seconds}s）：很可能是模型下载 / 网络 / CUDA 卡住。"
            f"请检查网络后重试，或先手动下载模型再运行。"
        )
        os._exit(1)
    if "err" in box:
        raise box["err"]
    return box["val"]

# ── 模型定义 ──────────────────────────────────────────────────
# 仅保留阿里达摩院中文模型（魔搭社区国内直连，无需 HuggingFace）。
MODEL_CONFIGS = {
    "sensevoice": {
        "name": "SenseVoiceSmall",
        "source": "ModelScope 魔搭社区",
        "source_url": "https://modelscope.cn/models/iic/SenseVoiceSmall",
        "size": "~500MB",
        "quality": "⭐⭐⭐⭐ (快/轻量/多语言+情感)",
        "description": "阿里达摩院 SenseVoice-small：更快、体积小、支持中/英/日/韩/粤与情感/事件标签；中文精度略逊 Paraformer-large，时间码需插值；可加 CAM++ 做说话人分离",
        "funasr_model": "iic/SenseVoiceSmall",
        "funasr_spk": "iic/speech_campplus_sv_zh-cn_16k-common",
        "needs_hf": False,
    },
    "paraformer": {
        "name": "Paraformer-large",
        "source": "ModelScope 魔搭社区",
        "source_url": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "size": "~800MB",
        "quality": "⭐⭐⭐⭐⭐ (中文最高，尤其嘈杂/口音)",
        "description": "阿里达摩院 Paraformer-large：中文大规模预训练，FunASR 流水线内置 FSMN-VAD（真实句级时间码）+ CT-Transformer 标点恢复 + CAM++ 说话人嵌入（spk_model），时间码/标点/说话人分离一次 generate() 全产出",
        "funasr_model": "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "funasr_vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "funasr_punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
        "funasr_spk": "iic/speech_campplus_sv_zh-cn_16k-common",
        "needs_hf": False,
    },
}


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 [MM:SS] 时间码"""
    total = int(seconds)
    mm = total // 60
    ss = total % 60
    return f"[{mm:02d}:{ss:02d}]"


# ── FunASR 后端 (SenseVoice / Paraformer) ────────────────────

def load_funasr_model(model_key: str):
    """加载 FunASR 模型（SenseVoice 或 Paraformer），从 ModelScope 自动下载"""
    try:
        from funasr import AutoModel
    except ImportError:
        print("错误: funasr 未安装，请执行: pip install funasr")
        print("  FunASR 是阿里达摩院开源语音识别工具包")
        print("  模型从 ModelScope 魔搭社区自动下载（国内直连，无需 HuggingFace）")
        sys.exit(1)

    cfg = MODEL_CONFIGS[model_key]
    print(f"加载 {cfg['name']} 模型（约 {cfg['size']}，从 {cfg['source']} 自动下载）...")
    print(f"  ⏳ 首次运行需下载模型（{cfg['size']}），耗时约 1–5 分钟（取决于网速），下载进度由 modelscope 输出，请耐心等待")

    kwargs = {
        "model": cfg["funasr_model"],
        "trust_remote_code": True,
    }
    # Paraformer 额外加载 VAD、标点、说话人嵌入模型
    if "funasr_vad" in cfg:
        kwargs["vad_model"] = cfg["funasr_vad"]
    if "funasr_punc" in cfg:
        kwargs["punc_model"] = cfg["funasr_punc"]
    if "funasr_spk" in cfg:
        kwargs["spk_model"] = cfg["funasr_spk"]

    try:
        model = with_timeout(600, AutoModel, **kwargs)
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
            gen_kwargs = dict(input=audio_path, language="zh", use_itn=True, sentence_timestamp=True)
        else:  # paraformer
            gen_kwargs = dict(input=audio_path, batch_size_s=300)
        result = with_timeout(900, model.generate, **gen_kwargs)
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
                # 若加载了 spk_model（CAM++），sentence_info 每项带 spk 字段，
                # 即模型内说话人聚类结果；无则回退统一 SPEAKER_00（由下游命名）。
                spk = s.get("spk", 0)
                segments.append({
                    "start": s.get("start", 0) / 1000.0,  # ms → s
                    "end": s.get("end", 0) / 1000.0,
                    "speaker": f"SPEAKER_{int(spk):02d}" if "spk" in s else "SPEAKER_00",
                    "text": text,
                })
    else:
        # SenseVoice 或无 VAD 的 Paraformer：整段文本
        if raw_text:
            # SenseVoice 输出可能含 <|zh|> 等语言标签，清理
            clean = raw_text
            for tag in ["<|zh|>", "<|en|>", "<|ja|>", "<|ko|>", "<|nospeech|>",
                        "<|HAPPY|>", "<|SAD|>", "<|ANGRY|>", "<|NEUTRAL|>",
                        "<|FEARFUL|>", "<|DISGUSTED|>", "<|SURPRISED|>",
                        "<|Speech|>", "<|BGM|>", "<|Laughter|>", "<|Applause|>"]:
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


# ── 对齐 & 合并 ──────────────────────────────────────────────

def merge_aligned_segments(all_aligned: list, segment_offsets: list) -> list:
    """合并所有段的结果，加上段偏移量"""
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


# ── 输出生成 ──────────────────────────────────────────────────

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


def generate_transcript_json(merged: list, title: str, source_file: str, model_name: str, frame_path, input_type: str) -> dict:
    """生成结构化转录数据（不生成 Markdown，供后续 LLM 处理与直接构建 .docx 使用）

    frame_path 为 None 时（音频输入）不输出静帧图。
    raw_text 为带时间码和 SPEAKER 标签的原始转录文本，供 Step 3.5 角色命名使用。
    说话人分离由 CAM++ 说话人嵌入在模型内完成（speaker_method 字段标明）。
    """
    return {
        "title": title,
        "source_file": source_file,
        "frame_path": frame_path,
        "input_type": input_type,
        "transcription_tool": model_name,
        "model": "local",
        "speaker_method": "CAM++ 说话人嵌入（FunASR spk_model，按声纹自动聚类）",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "raw_text": generate_raw_text(merged),
        # 结构化句子列表（含绝对时间码，秒），供 build_document.py 直接消费，
        # 免去再次解析 raw_text 造成的切分错位（见 2026-07-13 的 bug 修复）。
        "segments": merged,
    }


# ── 主流程 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="本地转录（阿里达摩院中文模型 + CAM++ 说话人分离）")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")
    parser.add_argument(
        "--model",
        default=None,
        choices=["sensevoice", "paraformer"],
        help="转录模型: paraformer (默认,高精度) | sensevoice (轻量可选)",
    )

    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    output_dir = config.get("output_dir", ".")
    doc_title = config.get("title", "转录文档")
    source_file = config.get("source_file", config.get("video_file", ""))
    frame_path = config.get("frame_path")
    segments = config.get("segments", [])

    # 确定模型
    model_key = args.model or config.get("model", "paraformer")
    if model_key not in MODEL_CONFIGS:
        print(f"错误: 未知模型 '{model_key}'，可选: {', '.join(MODEL_CONFIGS.keys())}")
        sys.exit(1)

    model_cfg = MODEL_CONFIGS[model_key]

    if not segments:
        print("错误: 配置中缺少 segments（音频切段列表）")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"开始本地转录")
    print(f"  模型: {model_cfg['name']} ({model_cfg['quality']})")
    print(f"  下载源: {model_cfg['source']}")
    print(f"  大小: {model_cfg['size']}")
    print(f"  说话人: CAM++ 说话人嵌入（模型内自动聚类，无需 LLM 切分）")
    print(f"  共 {len(segments)} 个音频段")
    print(f"{'='*60}\n")

    # 首次运行提示（模型需联网下载，耗时较久）
    print(f"\n⏳ 首次转录提示：将加载本地模型「{model_cfg['name']}」（{model_cfg['size']}），")
    print(f"   若本地尚未缓存，需联网下载，耗时约 1–5 分钟，请耐心等待；")
    print(f"   下载完成后会自动缓存，后续转录秒级启动。\n")

    # 加载 ASR 模型
    asr_model, asr_key = load_funasr_model(model_key)

    # 逐段处理
    all_aligned = []
    segment_offsets = []

    for i, seg in enumerate(segments):
        seg_file = seg["file"]
        seg_offset = seg.get("offset", 0)
        segment_offsets.append(seg_offset)

        print(f"\n--- 段 {i+1}/{len(segments)}: {seg_file} (偏移 {seg_offset}s) ---")

        # a. ASR 转录
        asr_segments = transcribe_funasr(asr_model, seg_file, asr_key)

        if not asr_segments:
            print("  ⚠️ 本段无转录结果，跳过")
            all_aligned.append([])
            continue

        # b. 说话人已由 CAM++ 在模型内分离（transcribe_funasr 返回的 speaker
        #    字段即声纹聚类 id）；SenseVoice 路径未返回 speaker 时回退 SPEAKER_00。
        aligned = [{"speaker": s.get("speaker", "SPEAKER_00"), "text": s["text"], "start": s["start"], "end": s["end"]} for s in asr_segments]
        all_aligned.append(aligned)

        # 预览
        for item in aligned[:5]:
            print(f"  [{item['start']:.1f}-{item['end']:.1f}] {item['speaker']}: {item['text']}")
        if len(aligned) > 5:
            print(f"  ... 共 {len(aligned)} 个片段")

        # 每处理完一段就落盘一次部分结果，避免被超时 / 异常中断时前功尽弃
        try:
            partial = merge_aligned_segments(all_aligned, segment_offsets)
            partial_path = os.path.join(output_dir, f"{doc_title}_transcript.partial.json")
            with open(partial_path, "w", encoding="utf-8") as pf:
                json.dump(
                    generate_transcript_json(
                        partial, doc_title, source_file, model_cfg["name"],
                        frame_path, config.get("input_type", "video"),
                    ),
                    pf, ensure_ascii=False, indent=2,
                )
        except Exception:
            pass  # 检查点写入失败不影响主流程

    # 合并
    merged = merge_aligned_segments(all_aligned, segment_offsets)
    print(f"\n合并完成: 共 {len(merged)} 个片段")

    # 生成结构化转录数据（JSON，无 Markdown；供 Step 3.5 处理与 build_docx 直接生成 .docx）
    data = generate_transcript_json(
        merged,
        doc_title,
        source_file,
        model_cfg["name"],
        frame_path,
        config.get("input_type", "video"),
    )
    json_path = os.path.join(output_dir, f"{doc_title}_transcript.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结构化转录数据保存（无 Markdown，将直接转为 .docx）: {json_path}")

    # 统计
    speaker_counts = {}
    for item in merged:
        speaker_counts[item["speaker"]] = speaker_counts.get(item["speaker"], 0) + 1
    print(f"\n说话人片段分布: {speaker_counts}")

    print(f"\n🎉 本地转录完成！（模型: {model_cfg['name']}）")
    print("请继续执行 Step 3.5 LLM 说话人识别（读取 raw_text，保留时间码）。")
    return json_path


if __name__ == "__main__":
    main()
