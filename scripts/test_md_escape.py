#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_md_escape 回归用例（发布审核要求补充）

覆盖：表格单元格公式注入（含前导空白绕过）、HTML/链接/表格分隔符转义、空白折叠。
运行: python scripts/test_md_escape.py   （全部通过退出码 0）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_docx import _md_escape

_CASES = []


def case(name, actual, expected):
    _CASES.append((name, actual, expected))


# ── 公式注入：前导空白绕过（审核指出的缺陷，回归重点）──
case("前导空格 =SUM", _md_escape(" =SUM(A1)", table_cell=True), "'=SUM(A1)")
case("制表符前导 @HYPERLINK", _md_escape('\t@HYPERLINK("x")', table_cell=True), "'@HYPERLINK(\"x\")")
case("多个前导空格 +SUM", _md_escape("   +SUM(A1)", table_cell=True), "'+SUM(A1)")
case("换行前导 =1+1", _md_escape("\n=1+1", table_cell=True), "'=1+1")

# ── 公式注入：无前导空白（原有覆盖）──
case("=HYPERLINK", _md_escape('=HYPERLINK("a")', table_cell=True), "'=HYPERLINK(\"a\")")
case("+SUM", _md_escape("+SUM(A1)", table_cell=True), "'+SUM(A1)")
case("-2+3", _md_escape("-2+3", table_cell=True), "'-2+3")
case("@sum", _md_escape("@sum", table_cell=True), "'@sum")

# ── 普通内容不受影响 ──
case("普通文本", _md_escape("普通文本", table_cell=True), "普通文本")
case("数字开头", _md_escape("123 abc", table_cell=True), "123 abc")
case("已有单引号前缀", _md_escape("'=SUM(A1)", table_cell=True), "'=SUM(A1)")
# 输入含字面 &（如 R&D）→ 实体化为 &amp;，且不会触发公式前缀（以 & 开头非 =+-@）
case("字面 & 实体化且不加前缀", _md_escape("R&D", table_cell=True), "R&amp;D")

# ── 空白折叠与去首尾（表格单元格）──
case("内部多空白折叠", _md_escape("a  b\tc", table_cell=True), "a b c")
case("首尾空白去除", _md_escape("  文本  ", table_cell=True), "文本")
case("空白折叠后再判前缀", _md_escape("  =SUM(A1)  ", table_cell=True), "'=SUM(A1)")

# ── 正文模式（table_cell=False）不折叠换行 ──
case("正文保留换行", _md_escape("第一行\n第二行", table_cell=False), "第一行\n第二行")
case("正文不强制去首尾", _md_escape(" 正文  ", table_cell=False), " 正文  ")

# ── HTML / 链接 / 表格分隔符转义仍生效 ──
case("HTML 转义", _md_escape("<script>", table_cell=True), "&lt;script&gt;")
case("链接转义", _md_escape("[x](y)", table_cell=True), "\\[x\\](y)")
case("竖线转义", _md_escape("a|b", table_cell=True), "a\\|b")


def main():
    print("=== _md_escape 回归用例 ===")
    failed = 0
    for name, actual, expected in _CASES:
        ok = actual == expected
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {name}: 期望 {expected!r}" + ("" if ok else f"，实际 {actual!r}"))
    print(f"\n共 {len(_CASES)} 条，失败 {failed} 条")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
