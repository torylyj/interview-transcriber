"""
通义千问 Qwen3-ASR-Flash 转录脚本
将分段 MP3 音频转录为文本，并进行启发式说话人识别。

用法: python transcribe_qwen.py --config config.json
配置示例见 references/dashscope_setup.md
"""

import os
import sys
import json
import argparse
import dashscope
import re

# ========== 采访者关键词（用于启发式说话人识别） ==========
QUESTION_KEYWORDS = [
    "什么", "为什么", "怎么", "如何", "哪", "谁", "多少",
    "吗", "呢", "吧", "能不能", "是不是", "有没有",
    "您", "你", "请问", "可以", "觉得", "认为",
    "建议", "推荐", "选择", "考", "学",
]

QUESTION_THRESHOLD_LEN = 25   # 短于25字且含关键词 → 可能是提问
ANSWER_MIN_LEN = 15           # 长于15字的回答


def is_question(text: str) -> bool:
    """判断是否是提问"""
    if len(text) < QUESTION_THRESHOLD_LEN:
        for kw in QUESTION_KEYWORDS:
            if kw in text:
                return True
    if text.endswith("?") or text.endswith("？"):
        return True
    for kw in ["什么", "为什么", "怎么", "如何", "哪", "谁", "多少", "几"]:
        if text.startswith(kw):
            return True
    return False


def transcribe_segments(segments: list, api_key: str) -> list:
    """对每个分段调用 Qwen3-ASR-Flash 进行转录"""
    dashscope.api_key = api_key
    results = []

    for i, seg in enumerate(segments):
        seg_file = seg["file"]
        time_offset = seg.get("offset", 0)
        file_url = "file://" + os.path.abspath(seg_file).replace("\\", "/")

        print(f"[{i+1}/{len(segments)}] 转录: {os.path.basename(seg_file)} (偏移 {time_offset}s)")

        try:
            response = dashscope.MultiModalConversation.call(
                model="qwen3-asr-flash",
                messages=[{"role": "user", "content": [{"audio": file_url}]}],
                result_format="message",
                asr_options={"enable_itn": False},
            )

            if response.status_code == 200:
                content = response.output.choices[0].message.content
                for item in content:
                    if "text" in item:
                        results.append({
                            "segment": i + 1,
                            "time_offset": time_offset,
                            "text": item["text"],
                        })
                        print(f"  ✅ 完成, {len(item['text'])} 字符")
                        break
            else:
                print(f"  ❌ 错误: {response.output}")
                raise RuntimeError(f"API error on segment {i+1}: {response.output}")

        except Exception as e:
            print(f"  ❌ 异常: {e}")
            raise

    return results


def classify_speakers(sentences: list) -> list:
    """启发式说话人识别，返回 [(speaker_label, text), ...]"""
    speaker_segments = []
    current_speaker = None
    current_text_buffer = []

    for sent in sentences:
        if is_question(sent):
            if current_speaker == "受访人" and current_text_buffer:
                speaker_segments.append(("受访人", " ".join(current_text_buffer)))
                current_text_buffer = []
            current_speaker = "采访者"
            current_text_buffer.append(sent)
        elif len(sent) > ANSWER_MIN_LEN:
            if current_speaker == "采访者" and current_text_buffer:
                speaker_segments.append(("采访者", " ".join(current_text_buffer)))
                current_text_buffer = []
            current_speaker = "受访人"
            current_text_buffer.append(sent)
        else:
            if current_speaker is None:
                current_speaker = "采访者"
            current_text_buffer.append(sent)

    if current_text_buffer:
        speaker_segments.append((current_speaker, " ".join(current_text_buffer)))

    return speaker_segments


def format_markdown(speaker_segments: list, title: str, frame_path: str, video_file: str) -> str:
    """生成 Markdown 格式的转录文档"""
    char_per_sec = 0.15
    elapsed_time = 0.0

    lines = [
        f"# {title}",
        "",
        f"![人物静帧](人物静帧.jpg)",
        "",
        f"> 视频文件: {video_file}",
        f"> 转录模型: 通义千问 Qwen3-ASR-Flash (阿里云百炼)",
        f"> 说话人识别: 基于语义特征（提问关键词+段落长度）的启发式识别",
        "",
        "---",
        "",
    ]

    for speaker, text in speaker_segments:
        timestamp_min = int(elapsed_time) // 60
        timestamp_sec = int(elapsed_time) % 60
        timestamp = f"[{timestamp_min:02d}:{timestamp_sec:02d}]"

        lines.append(f"**{speaker}** {timestamp}")
        lines.append("")
        lines.append(text)
        lines.append("")

        elapsed_time += len(text) * char_per_sec

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="通义千问 Qwen3-ASR-Flash 转录 + 说话人识别")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")

    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    api_key = config["api_key"]
    segments = config["segments"]
    output_dir = config.get("output_dir", ".")
    doc_title = config.get("title", "转录文档")
    frame_path = config.get("frame_path", "")
    video_file = config.get("video_file", "")

    # Step 1: 转录
    print(f"\n{'='*50}")
    print("开始 Qwen3-ASR-Flash 转录...")
    print(f"{'='*50}\n")
    all_text_parts = transcribe_segments(segments, api_key)

    # Step 2: 合并文本
    full_text = ""
    for part in all_text_parts:
        full_text += part["text"]

    print(f"\n合并后文本: {len(full_text)} 字符")

    # 保存原始文本
    raw_path = os.path.join(output_dir, f"{doc_title}_raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    print(f"原始文本保存: {raw_path}")

    # Step 3: 句子分割 + 说话人识别
    sentences = re.split(r"[。！？；\n]", full_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    print(f"分割为 {len(sentences)} 个句子")

    speaker_segments = classify_speakers(sentences)
    print(f"说话人段落: {len(speaker_segments)}")
    interview_count = sum(1 for s, _ in speaker_segments if s == "采访者")
    interviewee_count = sum(1 for s, _ in speaker_segments if s == "受访人")
    print(f"  采访者: {interview_count} 段")
    print(f"  受访人: {interviewee_count} 段")

    # Step 4: 生成 Markdown
    md_content = format_markdown(speaker_segments, doc_title, frame_path, video_file)

    md_path = os.path.join(output_dir, f"{doc_title}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n✅ Markdown 文档保存: {md_path}")

    # Step 5: 保存 JSON
    json_data = {
        "model": "qwen3-asr-flash",
        "segments": all_text_parts,
        "speaker_segments": [{"speaker": s, "text": t} for s, t in speaker_segments],
    }
    json_path = os.path.join(output_dir, f"{doc_title}_segments.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"JSON 保存: {json_path}")

    print("\n🎉 转录完成！")
    return md_path


if __name__ == "__main__":
    main()
