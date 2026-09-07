"""
结构化文档 JSON → Word (.docx) 生成器

直接读取 interview-transcriber 流程产出的 <标题>_document.json（Agent 完成
说话人识别 / 摘要生成 / 语气词自检后写入的最终结构化数据），生成排版清晰的
Word 文档。**全程不依赖 Markdown 中间文件。**

支持：
  - 文档标题
  - 居中人物静帧（仅视频输入，frame_path 非 null 时）
  - 内容摘要（📝 内容摘要，多段落）
  - 人物信息表格（👤 人物信息，2 列）
  - 文档信息引用块（📋 文档信息）
  - 对话记录（💬 对话记录，加粗说话人标签 + 时间码，每轮首句用色相差异大的彩色圆点标识不同说话人）

可选：
  --export-md <path>  额外导出一份临时 Markdown（供在线平台上传用，上传后即删）

用法:
  python build_docx.py <document.json> <output.docx> [--export-md _upload.md]
"""

import os
import sys
import json
import argparse
import re

# Windows 默认 GBK 控制台打印 emoji 会触发 UnicodeEncodeError：
# stdout 编码不支持时降级为可替换字符，避免脚本崩溃
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass


def _md_escape(text, table_cell=False):
    """对动态内容做 Markdown/HTML 转义，防止链接/HTML/表格/公式注入。

    - & < >：HTML 实体转义（防 `<script>` 等注入）
    - [ ]：转义方括号（防 `[x](javascript:...)` 链接注入）
    - |：转义竖线（防破坏表格结构）
    - 表格单元格：先折叠空白并去除首尾空白，再对以 = + - @ 开头的单元格
      统一前置安全前缀 '（防 Excel 公式注入；前导空白不再能绕过判断）
    """
    if text is None:
        return ""
    s = str(text)
    if table_cell:
        # 折叠所有空白（含制表符/换行/连续空格）并去首尾，避免 ' =SUM(...)'、'\t@x' 绕过前缀判断
        s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("[", "\\[").replace("]", "\\]")
    s = s.replace("|", "\\|")
    if table_cell and s[:1] in ("=", "+", "-", "@"):
        s = "'" + s
    return s


def person_fields(person):
    """将各种 person_info 结构统一成 [(label, value), ...]（过滤空值）。

    兼容三种结构：
      - 新结构：{"name":..., "fields":[{"field":..., "value":...}]}
      - 扁平结构（correct_speakers.py 产出）：{"role","name","school","major","grade"}
      - 旧结构：{"field":..., "value":...}
    """
    if not isinstance(person, dict):
        return []
    if "fields" in person and isinstance(person.get("fields"), list):
        return [(it.get("field", ""), it.get("value", ""))
                for it in person["fields"] if isinstance(it, dict)]
    if any(k in person for k in ("school", "major", "grade", "role")):
        mapping = [
            ("角色", person.get("role", "")),
            ("姓名", person.get("name", "")),
            ("学校", person.get("school", "")),
            ("专业", person.get("major", "")),
            ("年级", person.get("grade", "")),
        ]
        return [(k, v) for k, v in mapping if v]
    if "field" in person:
        return [(person.get("field", ""), person.get("value", ""))]
    return []


try:
    from docx import Document
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    print("错误: python-docx 未安装。请先执行: pip install python-docx")
    sys.exit(1)


def normalize_path(p):
    """将 Git Bash 风格路径 /c/Users/... 归一化为 Windows 路径 C:/Users/...。"""
    if not p:
        return p
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return p


# 说话人区分：在每轮「首次说话位置」用一个**色相差异大的彩色圆点**作为前缀标识。
# 关键：色相按 (红→蓝→绿→黄→紫→黑→棕→白→橙→灰) 分散排列，确保相邻说话人
# 拿到的颜色色相差距大（如 红+橙、蓝+绿 这种相近配色要避开）。
# 同色相用「色相 + 明度」两种维度做扩展位，可覆盖 10 位说话人。
_SPEAKER_EMOJI = [
    "🔴",  # 1 红
    "🔵",  # 2 蓝
    "🟢",  # 3 绿
    "🟡",  # 4 黄
    "🟣",  # 5 紫
    "⚫",  # 6 黑
    "🟤",  # 7 棕
    "⚪",  # 8 白
    "🟠",  # 9 橙（与红相邻但已被前 8 个拉开色相）
    "🔘",  # 10 灰
]

def _speaker_emoji(speaker, state):
    """按说话人出现顺序返回色相差异大的彩色圆点（state 跨轮次保持同一标识）。"""
    if speaker not in state:
        state[speaker] = _SPEAKER_EMOJI[len(state) % len(_SPEAKER_EMOJI)]
    return state[speaker]


def add_inline_runs(paragraph, text):
    """将含 **加粗** 的文本拆分为带格式 run 添加到段落。"""
    if text is None:
        return
    parts = str(text).split("**")
    for i, part in enumerate(parts):
        if part == "":
            continue
        run = paragraph.add_run(part)
        if i % 2 == 1:  # 奇数段为加粗
            run.bold = True


def parse_px(width_str):
    """解析 '280' 或 '280px' 为 Inches。"""
    try:
        px = float("".join(ch for ch in (width_str or "280") if ch.isdigit() or ch == "."))
    except ValueError:
        px = 280.0
    if px <= 0:
        px = 280.0
    return Inches(px / 96.0)


def add_image(doc, img_path, base_dir, width=Inches(280 / 96.0)):
    """居中插入图片，失败时用 Pillow 重新编码后重试。"""
    img_path = img_path if os.path.isabs(img_path) else os.path.join(base_dir, img_path)
    if not os.path.exists(img_path):
        print(f"  ⚠️ 静帧图片不存在，跳过: {img_path}")
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    try:
        p.add_run().add_picture(img_path, width=width)
        return
    except Exception:
        pass
    # 直接插入失败（扩展名与真实格式不符等），用 Pillow 重新编码为 JPEG 再插入
    try:
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        with Image.open(img_path) as im:
            im.convert("RGB").save(buf, "JPEG")
        buf.seek(0)
        p.add_run().add_picture(buf, width=width)
    except Exception as e2:
        print(f"  ⚠️ 插入图片失败: {e2}")


def _tool_with_size(tool: str) -> str:
    """转录工具名追加档位与模型大小标注（快速/精准/云端）。"""
    t = (tool or "").lower()
    if "moss" in t:
        return f"{tool}（精准档 · 0.9B 模型 ~1.8GB + torch GPU 推理栈 ~2.7GB）"
    if "sensevoice" in t:
        return f"{tool}（快速档 · 轻量模型 ~500MB）"
    if "paraformer" in t or "funasr" in t:
        return f"{tool}（快速档 · Paraformer-large ~900MB + CAM++ ~30MB）"
    if "qwen3-asr" in t or "qwen" in t:
        return f"{tool}（云端 · 无需本地模型）"
    return tool or ""


def build(doc, data, base_dir):
    # 标题
    doc.add_heading(data.get("title", "转录文档"), level=0)

    # 居中静帧（仅视频输入）
    frame_path = data.get("frame_path")
    if frame_path:
        add_image(doc, frame_path, base_dir, parse_px("280"))

    doc.add_paragraph("")

    # ── 内容摘要 ──
    summary = data.get("summary")
    summary_sections = data.get("summary_sections") or []
    if summary or summary_sections:
        doc.add_heading("\U0001F4DD 内容摘要", level=1)
        # 先打一句总结性摘要（保留与旧版兼容）
        if summary:
            for para in str(summary).split("\n"):
                if para.strip() == "":
                    doc.add_paragraph("")
                else:
                    p = doc.add_paragraph()
                    add_inline_runs(p, para)
            if summary_sections:
                doc.add_paragraph("")  # 总结与板块之间空一行
        # 再分板块摘要（H2 小标题 + 内容）
        for sec in summary_sections:
            if not isinstance(sec, dict):
                continue
            title = str(sec.get("title", "")).strip()
            content = str(sec.get("content", "")).strip()
            if not content:
                continue
            if title:
                doc.add_heading(title, level=2)
            for para in content.split("\n"):
                if para.strip() == "":
                    doc.add_paragraph("")
                else:
                    p = doc.add_paragraph()
                    add_inline_runs(p, para)
            doc.add_paragraph("")
        if not summary_sections:
            doc.add_paragraph("")

    # ── 人物信息（条件性：无信息整段省略；多人每人一个表格）──
    person_info = data.get("person_info") or []
    if person_info:
        doc.add_heading("\U0001F464 人物信息", level=1)
        for person in person_info:
            fields = person_fields(person)
            if not fields:
                continue
            name = person.get("name", "") if isinstance(person, dict) else ""
            if name:
                pname = doc.add_paragraph()
                pname.add_run(name).bold = True
            table = doc.add_table(rows=1, cols=2)
            try:
                table.style = "Table Grid"
            except Exception:
                pass
            # 表头
            hdr = table.rows[0].cells
            hdr[0].paragraphs[0].add_run("字段").bold = True
            hdr[1].paragraphs[0].add_run("内容").bold = True
            for label, value in fields:
                row = table.add_row().cells
                add_inline_runs(row[0].paragraphs[0], label)
                add_inline_runs(row[1].paragraphs[0], value)
            doc.add_paragraph("")

    # ── 文档信息 ──
    doc.add_heading("\U0001F4CB 文档信息", level=1)
    info_lines = [
        f"源文件：{data.get('source_file', '')}",
        f"输入类型：{data.get('input_type', '')}",
        f"转录工具：{_tool_with_size(data.get('transcription_tool', ''))}",
        f"说话人识别：{data.get('speaker_method', 'CAM++ 说话人嵌入（本地）/ LLM 语义切分（云端）')}",
        f"转录日期：{data.get('date', '')}",
    ]
    q = doc.add_paragraph()
    q.paragraph_format.left_indent = Inches(0.3)
    for j, line in enumerate(info_lines):
        if j > 0:
            q.add_run().add_break()
        q.add_run(line)
    doc.add_paragraph("")

    # ── 对话记录（两行制：角色（时间）一行 + 内容另起一行，轮间空一行）──
    doc.add_heading("\U0001F4AC 对话记录", level=1)
    conversation = data.get("conversation") or []
    if not conversation:
        print("  ⚠️ 警告: conversation 为空，文档将缺少对话记录")
    for turn in conversation:
        speaker = turn.get("speaker", "")
        paras = turn.get("paragraphs") or []
        ts = paras[0]["ts"] if paras else turn.get("timestamp", "")
        ts_disp = ts.strip("[]") if ts else ""
        text = paras[0]["text"] if paras else turn.get("text", "")
        # 第 1 行：角色（时间）——时间码去方括号，符合 角色（MM:SS）样式
        doc.add_paragraph(f"{speaker}（{ts_disp}）")
        # 第 2 行：内容
        doc.add_paragraph(text)
        # 续段（长独白自动分段）：时间码一行 + 内容另起一行
        for para in paras[1:]:
            doc.add_paragraph(para["ts"].strip("[]"))
            doc.add_paragraph(para["text"])
        # 轮间空一行
        doc.add_paragraph("")


def export_markdown(data, md_path, skip_frame=False):
    """将结构化文档导出为临时 Markdown（供在线平台上传；上传后即删）。

    skip_frame=True 时不写入本地静帧路径（在线平台用），
    改由 `dws doc media insert` 上传，避免在线文档出现打不开的本地图。
    """
    lines = [f"# {_md_escape(data.get('title', '转录文档'))}", ""]

    frame_path = data.get("frame_path")
    if frame_path and not skip_frame:
        lines += [f"![人物静帧]({_md_escape(frame_path)})", ""]

    lines += ["---", "", "## \U0001F4DD 内容摘要", "", _md_escape(data.get("summary", ""))]
    summary_sections = data.get("summary_sections") or []
    for sec in summary_sections:
        if not isinstance(sec, dict):
            continue
        title = _md_escape(str(sec.get("title", "")).strip())
        content = _md_escape(str(sec.get("content", "")).strip())
        if not content:
            continue
        if title:
            lines += ["", f"### {title}", ""]
        lines += [content, ""]
    lines += ["---", ""]
    person_info = data.get("person_info") or []
    if person_info:
        lines.append("## \U0001F464 人物信息")
        for person in person_info:
            fields = person_fields(person)
            if not fields:
                continue
            name = _md_escape(person.get("name", "")) if isinstance(person, dict) else ""
            if name:
                lines.append(f"### {name}")
            lines += ["", "| 字段 | 内容 |", "|------|------|"]
            for label, value in fields:
                lines.append(f"| {_md_escape(label, table_cell=True)} | {_md_escape(value, table_cell=True)} |")
            lines.append("")
    lines += ["", "---", "", "## \U0001F4CB 文档信息", ""]
    lines += [
        f"> 源文件：{_md_escape(data.get('source_file', ''))}",
        f"> 输入类型：{_md_escape(data.get('input_type', ''))}",
        f"> 转录工具：{_md_escape(_tool_with_size(data.get('transcription_tool', '')))}",
        f"> 说话人识别：{_md_escape(data.get('speaker_method', 'CAM++ 说话人嵌入（本地）/ LLM 语义切分（云端）'))}",
        f"> 转录日期：{_md_escape(data.get('date', ''))}",
        "",
        "---",
        "",
        "## \U0001F4AC 对话记录",
        "",
    ]
    for turn in data.get("conversation") or []:
        speaker = _md_escape(turn.get("speaker", ""))
        paras = turn.get("paragraphs") or []
        ts = paras[0]["ts"] if paras else turn.get("timestamp", "")
        ts_disp = ts.strip("[]") if ts else ""
        text = _md_escape(paras[0]["text"] if paras else turn.get("text", ""))
        # 第 1 行：角色（时间）——时间码去方括号；第 2 行：内容
        lines.append(f"{speaker}（{ts_disp}）")
        lines.append(text)
        # 续段：时间码一行 + 内容另起一行
        for para in paras[1:]:
            lines.append(para["ts"].strip("[]"))
            lines.append(_md_escape(para["text"]))
        # 轮间空行：用全角空格占位，避免钉钉在线文档吞掉空段落
        lines.append("\u3000")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 临时 Markdown 已导出（上传后请删除）: {md_path}")


def main():
    parser = argparse.ArgumentParser(description="结构化文档 JSON → Word (.docx) 生成器")
    parser.add_argument("input", help="输入的文档 JSON 文件路径（_document.json）")
    parser.add_argument("output", help="输出 .docx 路径")
    parser.add_argument("--export-md", default=None, help="额外导出临时 Markdown 的路径（可选）")
    parser.add_argument("--no-frame", action="store_true",
                        help="导出 Markdown 时不写入本地静帧路径（在线平台用，图改由 dws doc media insert 上传）")
    args = parser.parse_args()

    # 归一化路径（兼容 Git Bash 的 /c/... 写法，否则 Windows 原生程序找不到文件）
    args.input = normalize_path(args.input)
    args.output = normalize_path(args.output)
    if args.export_md:
        args.export_md = normalize_path(args.export_md)

    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}")
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    base_dir = os.path.dirname(os.path.abspath(args.input))
    doc = Document()
    build(doc, data, base_dir)
    doc.save(args.output)
    print(f"✅ Word 文档已生成: {args.output}")

    if args.export_md:
        export_markdown(data, args.export_md, skip_frame=args.no_frame)


if __name__ == "__main__":
    main()
