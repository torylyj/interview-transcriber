#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack_release.py — SkillHub 发布打包工具（v1.13.1 新增）

背景：SkillHub 上传要求目录内文件数 ≤ 200。本 skill 的开发目录含 .git/（~135 文件）
与 scripts/__pycache__/（缓存），直接上传会超限；真实内容仅 30 余个文件。

功能：
  1. 把 skill 目录复制到干净的 staging 目录（排除 .git / __pycache__ / *.pyc / tools/ 等）
  2. 统计 staging 内文件数并校验 ≤ MAX_FILES（默认 200）
  3. 可选 --zip 生成上传用 zip 包
  4. --check 仅做排除规则预演与计数校验，不落盘

用法（在任意目录执行）：
  python <skill_dir>/scripts/pack_release.py <skill_dir>              # 打包到 staging 目录
  python <skill_dir>/scripts/pack_release.py <skill_dir> --zip        # 额外生成 zip
  python <skill_dir>/scripts/pack_release.py <skill_dir> --out DIR    # 指定输出目录
  python <skill_dir>/scripts/pack_release.py <skill_dir> --check      # 只校验不复制
"""

import argparse
import fnmatch
import shutil
import sys
import zipfile
from pathlib import Path

MAX_FILES = 200  # SkillHub 上传硬限制

# 排除的目录名 / 文件模式（相对路径匹配）
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "tools", "node_modules", ".pytest_cache"}
EXCLUDE_PATTERNS = ["*.pyc", "*.pyo", "*.log", ".DS_Store", "Thumbs.db", "*.bak",
                    ".gitignore", ".gitattributes",  # SkillHub 拒绝 git 相关文件类型
                    "LICENSE", "LICENSE*", "COPYING"]  # SkillHub 拒绝 LICENSE 文件类型


def is_excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    name = rel.name
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_PATTERNS)


def collect_files(root: Path):
    files, excluded = [], 0
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            if is_excluded(rel):
                excluded += 1
            else:
                files.append(p)
    return files, excluded


def main():
    ap = argparse.ArgumentParser(description="SkillHub 发布打包（≤200 文件校验）")
    ap.add_argument("skill_dir", help="skill 目录（含 SKILL.md）")
    ap.add_argument("--out", default=None, help="输出目录（默认 <skill_dir>_release）")
    ap.add_argument("--zip", action="store_true", help="额外生成 zip 包")
    ap.add_argument("--check", action="store_true", help="仅预演计数校验，不落盘")
    args = ap.parse_args()

    root = Path(args.skill_dir).resolve()
    if not (root / "SKILL.md").is_file():
        print(f"❌ {root} 下没有 SKILL.md，不是有效的 skill 目录"); sys.exit(2)

    files, excluded = collect_files(root)
    total_on_disk = len(files) + excluded
    print(f"📦 目录: {root}")
    print(f"   磁盘总文件数: {total_on_disk}（排除规则滤掉 {excluded} 个）")
    print(f"   打包文件数  : {len(files)}")
    for f in sorted(files):
        print(f"     + {f.relative_to(root)}")

    if len(files) > MAX_FILES:
        print(f"❌ 超限：打包文件数 {len(files)} > SkillHub 上限 {MAX_FILES}，请精简内容")
        sys.exit(1)
    print(f"✅ 文件数校验通过（{len(files)} ≤ {MAX_FILES}）")

    if args.check:
        return

    out_dir = Path(args.out).resolve() if args.out else root.parent / (root.name + "_release")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for f in files:
        dst = out_dir / f.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    print(f"✅ 已复制 {len(files)} 个文件 → {out_dir}")

    if args.zip:
        zip_path = out_dir.parent / (root.name + "_release.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(out_dir.rglob("*")):
                if f.is_file():
                    # 关键：SKILL.md 必须在 zip 根目录（SkillHub 校验要求），不能包一层目录
                    zf.write(f, f.relative_to(out_dir))
        print(f"✅ zip 包（SKILL.md 位于根目录）→ {zip_path}")


if __name__ == "__main__":
    main()
