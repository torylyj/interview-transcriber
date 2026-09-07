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

用法: python transcribe_local.py --config config.json [--model sensevoice|paraformer|moss]
配置示例见 SKILL.md Step 2
"""

import os
import sys
import json
import argparse
import threading
import functools
import subprocess
from datetime import datetime

# 所有 print 立即刷新，避免长耗时步骤的输出被缓冲，导致调用方（Agent）误以为卡死
print = functools.partial(print, flush=True)

# 视频扩展名：segments 可直接指向视频文件，脚本自动提取音轨（免手动转 MP3）
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm"}


def resolve_seg_path(seg_file: str, output_dir: str) -> str:
    """segments 里的 file 支持绝对路径或相对 output_dir 的相对路径。"""
    if os.path.isabs(seg_file) and os.path.exists(seg_file):
        return seg_file
    cand = os.path.join(output_dir, seg_file)
    return cand if os.path.exists(cand) else seg_file


def ensure_audio(path: str, workdir: str):
    """视频输入 → 自动提取 16k 单声道 WAV（一步隐式完成，无需预先转 MP3）。

    返回 (音频路径, 是否临时文件)。音频输入原样返回。
    WAV(pcm_s16le) 比 MP3 免去有损编码，速度更快且无音质损失。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXT:
        return path, False
    base = os.path.splitext(os.path.basename(path))[0]
    wav = os.path.join(workdir, f"_audio_{base}.wav")
    if not os.path.exists(wav):
        print(f"  🎬 检测到视频输入，自动提取音轨（16k 单声道 WAV）→ {os.path.basename(wav)}")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-vn", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", wav],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not os.path.exists(wav):
            tail = (r.stderr or "").strip().splitlines()[-3:]
            print("  ❌ 音轨提取失败：" + " / ".join(tail))
            sys.exit(1)
    return wav, True


def with_timeout(seconds, func, *args, **kwargs):
    """在子线程中运行阻塞调用并加超时。

    超时或异常**抛出**（TimeoutError / 原异常），不再 os._exit 强制杀进程——
    由调用方决定如何友好失败，避免把正在进行的模型下载一并杀死。
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
        raise TimeoutError(
            f"操作在 {seconds}s 内未完成（可能网络较慢 / 模型较大 / 推理卡住）。"
            f"未强制终止进程；可重试，或先手动下载模型再运行。"
        )
    if "err" in box:
        raise box["err"]
    return box["val"]


def load_model_with_status(model_key: str, kwargs: dict):
    """加载 FunASR 模型，**不设硬超时**——网速慢也允许模型慢慢下载完。

    行为：
    - 模型在后台线程加载；主线程每 30s 打印一次进度（已用秒数）。
    - 每累计满 600s 打印一条「⚠️ 已超 600s」状态横幅，提示调用方
      （Agent）向用户报告现状并让用户选择「继续等待 / 中止」。
    - **绝不主动 kill 进程**：要么加载完成返回模型，要么被外部中断
      （Ctrl+C / Agent 中止后台任务）而退出。
    """
    cfg = MODEL_CONFIGS[model_key]
    box = {}

    def _load():
        try:
            from funasr import AutoModel
            box["model"] = AutoModel(**kwargs)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_load, daemon=True)
    t.start()

    start = datetime.now()
    WARN_EVERY = 600      # 每 600s 向调用方（Agent）提示一次，由其询问用户
    POLL = 30
    next_warn = WARN_EVERY
    print(f"  ⏳ 模型加载中（{cfg['size']}，可能需从 ModelScope 下载）...")
    while t.is_alive():
        t.join(POLL)
        if not t.is_alive():
            break
        elapsed = (datetime.now() - start).total_seconds()
        print(f"  ⏳ 模型仍在加载（已 {int(elapsed)}s）...")
        if elapsed >= next_warn:
            print("")
            print("  " + "=" * 56)
            print(f"  ⚠️ 模型加载已超 {int(elapsed)}s（网络较慢 / 模型较大）。")
            print("  ⚠️ 当前仍在后台继续下载，未做任何强制中断。")
            print("  ⚠️ 若你（Agent）看到这条，请向用户报告现状并询问：")
            print("        「模型下载较慢，已等待约 %d 分钟仍未完成，要继续等还是中止？」"
                  % (int(elapsed) // 60))
            print("        - 用户『继续』：保持进程运行，本脚本会继续直到完成；")
            print("        - 用户『中止』：终止本任务（Ctrl+C / 停止后台进程），")
            print("          已落盘的部分结果（_transcript.partial.json）可保留续跑。")
            print("  " + "=" * 56)
            print("")
            next_warn += WARN_EVERY

    if "err" in box:
        raise box["err"]
    return box["model"], model_key

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
        "name": "Paraformer-large-vad-punc",
        "source": "ModelScope 魔搭社区",
        "source_url": "https://modelscope.cn/models/iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "size": "~900MB",
        "quality": "⭐⭐⭐⭐⭐ (中文最高，尤其嘈杂/口音)",
        "description": "阿里达摩院 Paraformer-large-vad-punc（nat 版）：中文大规模预训练，能输出【词级时间码】——这是句子级说话人分离（punc_segment 模式）的硬前提。配合 FSMN-VAD + CT-Transformer 标点 + CAM++ 说话人嵌入，走 punc_segment 后可【按标点句子】分配说话人（而非按 VAD 段），彻底解决长语音段被合并成单一说话人的问题。⚠️ 普通 speech_paraformer-large_asr_nat（无 vad-punc）不产生词级时间码，会退回 vad_segment 模式导致开头长段合并，切勿使用。",
        "funasr_model": "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "funasr_vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "funasr_punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
        "funasr_spk": "iic/speech_campplus_sv_zh-cn_16k-common",
        "needs_hf": False,
    },
    "moss": {
        "name": "MOSS-Transcribe-Diarize 0.9B",
        "source": "ModelScope 魔搭社区（OpenMOSS / 复旦）",
        "source_url": "https://modelscope.cn/models/OpenMOSS/MOSS-Transcribe-Diarize",
        "size": "~1.8GB",
        "quality": "⭐⭐⭐⭐⭐ (端到端：转录+说话人+时间戳一次生成)",
        "description": "复旦 OpenMOSS 端到端模型（2026-07 开源，INTERSPEECH 2026 多语言转录挑战赛第一）。转录/说话人/时间戳由同一模型一次生成，根除 CAM++ 级联式『短应答贴错人/乱换行』问题；标点自然、中文精度高。不支持 preset_spk_num（人数由模型自判）；同人嗓音变化可能被拆成多个 Sxx，由 moss_assign_roles 按提问密度归并为 采访者/受访者。",
        "backend": "moss",
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
    # Paraformer(nat) 额外加载 VAD、标点、说话人嵌入模型
    if "funasr_vad" in cfg:
        kwargs["vad_model"] = cfg["funasr_vad"]
    # ✅ punc_model 与 spk_model 必须【同载】：
    #   句子级说话人分离（funasr punc_segment 模式）依赖 punc_model 产生的
    #   punc_array 做断句，再把 CAM++ 说话人标签按句子分配。缺 punc_model 则
    #   sentence_info 为空（"生成 0 个文本片段"）。
    #   前提是主模型能产生【词级 timestamp】——即 nat 的 vad-punc 版
    #   (speech_paraformer-large-vad-punc_asr_nat)；普通 paraformer-large 不产生
    #   时间码，会退回 vad_segment 模式导致长段合并成单一说话人。
    if "funasr_punc" in cfg:
        kwargs["punc_model"] = cfg["funasr_punc"]
    if "funasr_spk" in cfg:
        kwargs["spk_model"] = cfg["funasr_spk"]

    try:
        # 模型加载不设硬超时：网速慢时允许慢慢下载完（超 600s 会打印
        # 状态横幅，交由上层 Agent 向用户报告并询问继续/中止）。
        model, model_key = load_model_with_status(model_key, kwargs)
        print(f"  ✅ {cfg['name']} 加载成功")
        return model, model_key
    except Exception as e:
        print(f"\n❌ {cfg['name']} 模型加载失败: {e}")
        print(f"  下载源: {cfg['source']} ({cfg['source_url']})")
        print(f"\n手动下载方式:")
        print(f"  pip install modelscope")
        print(f"  python -c \"from modelscope import snapshot_download; snapshot_download('{cfg['funasr_model']}')\"")
        sys.exit(1)


def load_punc_model(model_key: str):
    """加载独立的 CT-Transformer 标点模型（Paraformer 逐句标点用）。

    Paraformer 不能与 spk_model 同载 punc（见 load_funasr_model 注释），
    故标点单独加载，在 transcribe_funasr 中对每句文本独立恢复标点，
    既保证 CAM++ 说话人分离正确，又得到带标点的输出。
    """
    try:
        from funasr import AutoModel
    except ImportError:
        print("错误: funasr 未安装，请执行: pip install funasr")
        sys.exit(1)

    cfg = MODEL_CONFIGS[model_key]
    punc = cfg.get("funasr_punc")
    if not punc:
        return None
    print(f"加载标点模型（{cfg['name']} 配套 CT-Transformer，逐句标点）...")
    model = AutoModel(model=punc, trust_remote_code=True)
    print(f"  ✅ 标点模型加载成功")
    return model


def punctuate_text(punc_model, text: str) -> str:
    """用独立标点模型恢复单句标点；失败时原样返回。"""
    if punc_model is None or not text:
        return text
    try:
        pr = punc_model.generate(input=text)[0]
        return (pr.get("text") or text).strip()
    except Exception as e:
        print(f"  [warn] 标点失败，保留原文本: {e}")
        return text


def transcribe_funasr(model, audio_path: str, model_key: str, punc_model=None, preset_spk_num=None) -> list:
    """用 FunASR (SenseVoice/Paraformer) 转录单个音频段

    punc_model: 仅 SenseVoice 路径可能用到的独立标点模型；Paraformer(nat) 的标点
        已由主模型同载的 punc_model 在 punc_segment 内完成，无需再逐句处理。
    preset_spk_num: 强制说话人数（如街头采访=2，采访者+受访者）。传入后 CAM++
        聚类固定成该人数，显著提升 2 人对话的分离稳定性；为 None 时自动判定人数。
    """
    cfg = MODEL_CONFIGS[model_key]
    print(f"  转录中 ({cfg['name']}): {audio_path}")

    try:
        if model_key == "sensevoice":
            gen_kwargs = dict(input=audio_path, language="zh", use_itn=True, sentence_timestamp=True)
        else:  # paraformer(nat)
            # nat 模型产生词级 timestamp + 同载 punc_model → 走 punc_segment 模式，
            # 按标点句子分配 CAM++ 说话人标签（句子级，非 VAD 段级）。
            # preset_spk_num 强制说话人数，避免长段/短应答被误聚类。
            gen_kwargs = dict(input=audio_path, batch_size_s=300)
            if preset_spk_num:
                gen_kwargs["preset_spk_num"] = preset_spk_num
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
            # nat + punc_segment：sentence 字段即带标点的句子文本（部分版本为 text）。
            text = (s.get("sentence") or s.get("text") or "").strip()
            if text:
                # 兜底：若该句无标点（极少数情况）且有独立 punc 模型，补一次。
                if punc_model is not None and not any(c in text for c in "，。！？、；："):
                    text = punctuate_text(punc_model, text)
                # sentence_info 每项带 spk 字段（CAM++ 按句子分配的说话人 id）；
                # 无则回退统一 SPEAKER_00（由下游命名）。
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


def generate_transcript_json(merged: list, title: str, source_file: str, model_name: str, frame_path, input_type: str, speaker_method: str = "CAM++ 说话人嵌入（FunASR spk_model，按声纹自动聚类）") -> dict:
    """生成结构化转录数据（不生成 Markdown，供后续 LLM 处理与直接构建 .docx 使用）

    frame_path 为 None 时（音频输入）不输出静帧图。
    raw_text 为带时间码和 SPEAKER 标签的原始转录文本，供 Step 3.5 角色命名使用。
    speaker_method 标明说话人识别方式（MOSS 端到端 / CAM++ 模型内 / 云端 LLM）。
    """
    return {
        "title": title,
        "source_file": source_file,
        "frame_path": frame_path,
        "input_type": input_type,
        "transcription_tool": model_name,
        "model": "local",
        "speaker_method": speaker_method,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "raw_text": generate_raw_text(merged),
        # 结构化句子列表（含绝对时间码，秒），供 build_document.py 直接消费，
        # 免去再次解析 raw_text 造成的切分错位（见 2026-07-13 的 bug 修复）。
        "segments": merged,
    }


# ── MOSS 端到端后端（默认本地模型） ───────────────────────────
# 模型本地目录（已下载缓存，优先）；缺失时按 ModelScope id 自动下载。
MOSS_MODEL_LOCAL = r"H:\models\models\OpenMOSS--MOSS-Transcribe-Diarize\snapshots\master"
MOSS_MODEL_ID = "OpenMOSS/MOSS-Transcribe-Diarize"

def load_moss_model():
    """加载 MOSS-Transcribe-Diarize（transformers + moss_transcribe_diarize 推理包）。"""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        from moss_transcribe_diarize import parse_transcript
        from moss_transcribe_diarize.inference_utils import (
            build_transcription_messages, generate_transcription, resolve_device,
        )
    except ImportError as e:
        print(f"错误: MOSS 依赖未安装（transformers / moss_transcribe_diarize）: {e}")
        print("  请运行: python <skill_dir>/scripts/setup_env.py （已包含 MOSS 依赖）")
        sys.exit(1)
    device = resolve_device("auto")
    dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
    # 优先用本地已下载目录；否则从 ModelScope 下载到缓存
    if os.path.isdir(MOSS_MODEL_LOCAL):
        model_dir = MOSS_MODEL_LOCAL
    else:
        try:
            from modelscope import snapshot_download
            model_dir = snapshot_download(MOSS_MODEL_ID,
                                          cache_dir=os.path.join(os.path.dirname(MOSS_MODEL_LOCAL), ".."))
        except Exception as e:
            print(f"错误: 本地模型不存在且 ModelScope 下载失败: {e}")
            sys.exit(1)
    print(f"加载 MOSS 模型（{model_dir}，device={device}，dtype={dtype}）...")
    t0 = datetime.now()
    model = (AutoModelForCausalLM
             .from_pretrained(model_dir, trust_remote_code=True, dtype="auto")
             .to(dtype).to(device).eval())
    processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
    print(f"  ✅ MOSS 模型加载成功（{int((datetime.now()-t0).total_seconds())}s）")
    return model, processor, device, dtype


def transcribe_moss(model, processor, device, dtype, audio_path, max_new_tokens=32768):
    """MOSS 端到端推理单段音频，返回 (raw_text, segments)。"""
    from moss_transcribe_diarize import parse_transcript
    from moss_transcribe_diarize.inference_utils import (
        build_transcription_messages, generate_transcription,
    )
    messages = build_transcription_messages(audio_path)
    result = generate_transcription(
        model, processor, messages,
        max_new_tokens=max_new_tokens, do_sample=False,
        device=device, dtype=dtype,
    )
    raw = result.get("text", "")
    segments = []
    try:
        for seg in parse_transcript(raw):
            if hasattr(seg, "start"):
                segments.append({"start": seg.start, "end": seg.end,
                                 "speaker": seg.speaker, "text": seg.text})
            else:
                segments.append(dict(seg))
    except Exception as e:
        print(f"  [warn] MOSS parse_transcript 失败，保留原始文本: {e}")
    print(f"    生成 {len(segments)} 个文本片段")
    return raw, segments


def moss_assign_roles(segments):
    """MOSS 可能把同一说话人拆成多个 Sxx（嗓音状态变化）。

    按『采访者特征』把说话人归并为 采访者/受访者 两角：采访者提问更多、
    且单轮通常更短。双重信号避免『模型漏标问号』导致无法归并。
    仅当能清晰区分出一组采访者、一组受访者时才归并，否则保留原始 Sxx
    （交由 build_document 中性命名 / corrections 处理）。
    """
    from collections import defaultdict
    q = defaultdict(int)
    n = defaultdict(int)
    tot = defaultdict(int)
    for s in segments:
        sp = s["speaker"]
        t = s.get("text", "") or ""
        q[sp] += t.count("？") + t.count("?")
        n[sp] += 1
        tot[sp] += len(t)
    speakers = list(q.keys())
    if len(speakers) < 2:
        return segments
    avg = {sp: (tot[sp] / n[sp]) if n[sp] else 0.0 for sp in speakers}
    maxq = max(q.values())
    if maxq > 0:
        # 有提问标记：提问量达最高者一半以上者视为采访者
        interviewer_candidates = {sp for sp in speakers if q[sp] >= 0.5 * maxq}
    else:
        # 无提问标记（模型漏标问号）：取平均轮长最短者及与之接近者为采访者
        minavg = min(avg.values())
        interviewer_candidates = {sp for sp in speakers if avg[sp] <= 1.5 * minavg}
    if 0 < len(interviewer_candidates) < len(speakers):
        for s in segments:
            s["speaker"] = "SPEAKER_00" if s["speaker"] in interviewer_candidates else "SPEAKER_01"
    return segments


# ── 主流程 ────────────────────────────────────────────────────

def merge_short_segments(segs, min_dur=0.6):
    """时长兜底合并：<min_dur 秒的片段并入前一句，消除 CAM++ 转场亚秒碎片。

    与 build_document.merge_speaker_jitter（按文本长度 ≤10 字）互补：
    此处按【时长】合并，专治 0.3-0.6s 的短碎片（如"我觉得""嗯嗯"抢话尾），
    文本长度法对此类无效。首句过短则并入后一句。
    """
    if not segs:
        return segs
    out = []
    for s in segs:
        seg = dict(s)
        dur = seg.get("end", 0) - seg.get("start", 0)
        if out and dur < min_dur:
            prev = out[-1]
            prev["end"] = max(prev["end"], seg.get("end", prev["end"]))
            prev["text"] = prev["text"] + seg["text"]
            continue
        out.append(seg)
    # 首句过短：并入后一句（时间起点取更早者）
    if len(out) >= 2 and (out[0].get("end", 0) - out[0].get("start", 0)) < min_dur:
        nxt = out[1]
        nxt["start"] = min(nxt["start"], out[0].get("start", nxt["start"]))
        nxt["text"] = out[0]["text"] + nxt["text"]
        out.pop(0)
    return out


def main():
    parser = argparse.ArgumentParser(description="本地转录（MOSS 端到端 / Paraformer+CAM++ / SenseVoice）")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")
    parser.add_argument(
        "--model",
        default=None,
        choices=["paraformer", "sensevoice", "moss"],
        help="转录模型: paraformer=快速档(默认) | moss=精准档端到端 | sensevoice=轻量更快",
    )
    parser.add_argument("--max-new-tokens", type=int, default=32768,
                        help="MOSS 推理最大新 token 数（长音频可加大）")

    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    output_dir = config.get("output_dir", ".")
    doc_title = config.get("title", "转录文档")
    source_file = config.get("source_file", config.get("video_file", ""))
    frame_path = config.get("frame_path")
    segments = config.get("segments", [])

    # 确定模型（paraformer=快速档默认；moss=精准档端到端，见 SKILL.md Step 2.5）
    model_key = args.model or config.get("model", "paraformer")
    if model_key not in MODEL_CONFIGS:
        print(f"错误: 未知模型 '{model_key}'，可选: {', '.join(MODEL_CONFIGS.keys())}")
        sys.exit(1)

    model_cfg = MODEL_CONFIGS[model_key]
    backend = model_cfg.get("backend", "funasr")

    if not segments:
        print("错误: 配置中缺少 segments（音频切段列表）")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"开始本地转录")
    print(f"  模型: {model_cfg['name']} ({model_cfg['quality']})")
    print(f"  下载源: {model_cfg['source']}")
    print(f"  大小: {model_cfg['size']}")
    if backend == "moss":
        print(f"  说话人: MOSS 端到端（转录+说话人+时间戳一次生成，按提问密度归并角色）")
    else:
        print(f"  说话人: CAM++ 说话人嵌入（模型内自动聚类，无需 LLM 切分）")
    print(f"  共 {len(segments)} 个音频段")
    print(f"{'='*60}\n")

    # 首次运行提示（模型需联网下载，耗时较久）
    print(f"\n⏳ 首次转录提示：将加载本地模型「{model_cfg['name']}」（{model_cfg['size']}），")
    print(f"   若本地尚未缓存，需联网下载，耗时约 1–5 分钟，请耐心等待；")
    print(f"   下载完成后会自动缓存，后续转录秒级启动。\n")

    all_aligned = []
    segment_offsets = []

    def _save_partial():
        try:
            partial = merge_aligned_segments(all_aligned, segment_offsets)
            if backend == "moss":
                partial = moss_assign_roles(partial)
            sp_method = ("MOSS-Transcribe-Diarize 端到端（转录+说话人+时间戳一次生成）"
                         if backend == "moss"
                         else "CAM++ 说话人嵌入（FunASR spk_model，按声纹自动聚类）")
            partial_path = os.path.join(output_dir, f"{doc_title}_transcript.partial.json")
            with open(partial_path, "w", encoding="utf-8") as pf:
                json.dump(
                    generate_transcript_json(
                        partial, doc_title, source_file, model_cfg["name"],
                        frame_path, config.get("input_type", "video"),
                        speaker_method=sp_method,
                    ),
                    pf, ensure_ascii=False, indent=2,
                )
        except Exception:
            pass  # 检查点写入失败不影响主流程

    if backend == "moss":
        model, processor, device, dtype = load_moss_model()
        for i, seg in enumerate(segments):
            seg_file = resolve_seg_path(seg["file"], output_dir)
            seg_offset = seg.get("offset", 0)
            segment_offsets.append(seg_offset)
            print(f"\n--- 段 {i+1}/{len(segments)}: {os.path.basename(seg_file)} (偏移 {seg_offset}s) ---")
            audio_file, is_temp = ensure_audio(seg_file, output_dir)
            try:
                raw, asr_segments = transcribe_moss(model, processor, device, dtype, audio_file, args.max_new_tokens)
            finally:
                if is_temp:
                    try:
                        os.remove(audio_file)
                    except OSError:
                        pass
            if not asr_segments:
                print("  ⚠️ 本段无转录结果，跳过")
                all_aligned.append([])
                continue
            # MOSS 返回的 start/end 为该段内相对时间，由 merge_aligned_segments 加段偏移
            aligned = [{"speaker": s.get("speaker", "SPEAKER_00"), "text": s["text"],
                        "start": s["start"], "end": s["end"]} for s in asr_segments]
            all_aligned.append(aligned)
            for item in aligned[:5]:
                print(f"  [{item['start']:.1f}-{item['end']:.1f}] {item['speaker']}: {item['text']}")
            if len(aligned) > 5:
                print(f"  ... 共 {len(aligned)} 个片段")
            _save_partial()
        merged = merge_aligned_segments(all_aligned, segment_offsets)
        merged = moss_assign_roles(merged)
        speaker_method = "MOSS-Transcribe-Diarize 端到端（转录+说话人+时间戳一次生成）"
    else:
        asr_model, asr_key = load_funasr_model(model_key)
        punc_model = None
        if "preset_spk_num" in config:
            preset_spk_num = config.get("preset_spk_num")
            if preset_spk_num:
                print(f"  强制说话人数（config 指定）: preset_spk_num={preset_spk_num}")
            else:
                print("  说话人数由 CAM++ 自动判定（config 设为空）")
        else:
            preset_spk_num = 2
            print("  未指定，默认强制说话人数 preset_spk_num=2（街头采访/双人对话）")
        for i, seg in enumerate(segments):
            seg_file = resolve_seg_path(seg["file"], output_dir)
            seg_offset = seg.get("offset", 0)
            segment_offsets.append(seg_offset)
            print(f"\n--- 段 {i+1}/{len(segments)}: {os.path.basename(seg_file)} (偏移 {seg_offset}s) ---")
            audio_file, is_temp = ensure_audio(seg_file, output_dir)
            try:
                asr_segments = transcribe_funasr(asr_model, audio_file, asr_key, punc_model=punc_model, preset_spk_num=preset_spk_num)
            finally:
                if is_temp:
                    try:
                        os.remove(audio_file)
                    except OSError:
                        pass
            if not asr_segments:
                print("  ⚠️ 本段无转录结果，跳过")
                all_aligned.append([])
                continue
            aligned = [{"speaker": s.get("speaker", "SPEAKER_00"), "text": s["text"], "start": s["start"], "end": s["end"]} for s in asr_segments]
            # 时长兜底合并亚秒碎片（补 merge_speaker_jitter 的文本阈值盲区）
            aligned = merge_short_segments(aligned)
            all_aligned.append(aligned)
            for item in aligned[:5]:
                print(f"  [{item['start']:.1f}-{item['end']:.1f}] {item['speaker']}: {item['text']}")
            if len(aligned) > 5:
                print(f"  ... 共 {len(aligned)} 个片段")
            _save_partial()
        merged = merge_aligned_segments(all_aligned, segment_offsets)
        speaker_method = "CAM++ 说话人嵌入（FunASR spk_model，按声纹自动聚类）"

    print(f"\n合并完成: 共 {len(merged)} 个片段")

    data = generate_transcript_json(
        merged, doc_title, source_file, model_cfg["name"],
        frame_path, config.get("input_type", "video"),
        speaker_method=speaker_method,
    )
    json_path = os.path.join(output_dir, f"{doc_title}_transcript.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结构化转录数据保存（无 Markdown，将直接转为 .docx）: {json_path}")

    speaker_counts = {}
    for item in merged:
        speaker_counts[item["speaker"]] = speaker_counts.get(item["speaker"], 0) + 1
    print(f"\n说话人片段分布: {speaker_counts}")

    print(f"\n🎉 本地转录完成！（模型: {model_cfg['name']}）")
    print("请继续执行 Step 3.5 说话人角色命名 / Step 3.6 摘要（MOSS 已自动归并采访者/受访者）。")
    return json_path


if __name__ == "__main__":
    main()
