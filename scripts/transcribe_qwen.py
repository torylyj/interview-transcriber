"""
通义千问 Qwen3-ASR-Flash 转录脚本
将分段 MP3 音频转录为带时间码的文本。

时间码基于段偏移 + 段内字符位置估算（中文语速约 6-7 字/秒），
段级精度（4分钟粒度），段内为估算值。

用法: python transcribe_qwen.py --config config.json
配置示例见 references/dashscope_setup.md
"""

import os
import sys
import json
import argparse
import dashscope

# 中文口语语速估算：每个字约 0.15 秒
CHAR_PER_SEC = 0.15


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 [MM:SS] 时间码"""
    total = int(seconds)
    mm = total // 60
    ss = total % 60
    return f"[{mm:02d}:{ss:02d}]"


def transcribe_segments(segments: list, api_key: str) -> list:
    """对每个分段调用 Qwen3-ASR-Flash 进行转录，返回带时间偏移的结果"""
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


def generate_raw_text(all_text_parts: list) -> str:
    """生成带时间码的原始文本，供 LLM 做说话人识别"""
    lines = []
    for part in all_text_parts:
        offset = part["time_offset"]
        text = part["text"]
        ts = format_timestamp(offset)
        lines.append(f"{ts} {text}")
    return "\n".join(lines)


def generate_markdown(all_text_parts: list, title: str, video_file: str) -> str:
    """生成带时间码的 Markdown 文档（不含说话人标签，待 LLM 处理）"""
    lines = [
        f"# {title}",
        "",
        f"![人物静帧](人物静帧.jpg)",
        "",
        f"> 视频文件: {video_file}",
        f"> 转录模型: 通义千问 Qwen3-ASR-Flash (阿里云百炼)",
        f"> 时间码: 段级精度（4分钟粒度），段内为估算值",
        "",
        "---",
        "",
    ]

    for part in all_text_parts:
        offset = part["time_offset"]
        text = part["text"]
        ts = format_timestamp(offset)
        lines.append(f"{ts} {text}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="通义千问 Qwen3-ASR-Flash 转录（带时间码）")
    parser.add_argument("--config", required=True, help="JSON 配置文件路径")

    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    api_key = config["api_key"]
    segments = config["segments"]
    output_dir = config.get("output_dir", ".")
    doc_title = config.get("title", "转录文档")
    video_file = config.get("video_file", "")

    # Step 1: 转录
    print(f"\n{'='*50}")
    print("开始 Qwen3-ASR-Flash 转录（带时间码）...")
    print(f"{'='*50}\n")
    all_text_parts = transcribe_segments(segments, api_key)

    # Step 2: 生成带时间码的原始文本（供 LLM 说话人识别）
    raw_text = generate_raw_text(all_text_parts)
    total_chars = sum(len(p["text"]) for p in all_text_parts)
    print(f"\n合并后文本: {total_chars} 字符")

    raw_path = os.path.join(output_dir, f"{doc_title}_raw.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_text)
    print(f"原始文本（带时间码）保存: {raw_path}")

    # Step 3: 生成 Markdown（带时间码，不含说话人标签）
    md_content = generate_markdown(all_text_parts, doc_title, video_file)

    md_path = os.path.join(output_dir, f"{doc_title}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n✅ Markdown 文档保存: {md_path}")

    # Step 4: 保存 JSON
    json_data = {
        "model": "qwen3-asr-flash",
        "segments": all_text_parts,
    }
    json_path = os.path.join(output_dir, f"{doc_title}_segments.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"JSON 保存: {json_path}")

    print("\n🎉 转录完成！请继续执行 Step 3.5 LLM 说话人识别（保留时间码）。")
    return md_path


if __name__ == "__main__":
    main()
