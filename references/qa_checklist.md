# QA 冒烟自检清单（更新 skill / 上架前跑一遍）

> 目标：10 分钟内验证 skill 核心链路可用，避免「改了文档/脚本，下次真实转录才暴雷」。
> 全程用**快速档（SenseVoice q8 GGUF）**，最短路径覆盖最多环节。

## 0. 静态自检（30 秒）

- [ ] `python -m py_compile scripts/*.py` 全部通过（无语法错误）
- [ ] SKILL.md frontmatter 含 `name` / `description` / `version`
- [ ] `python scripts/pack_release.py <skill_dir> --check` 文件数 ≤ 200

## 1. 环境自检（1 分钟）

- [ ] `python scripts/setup_env.py --verify` 全 ✅（快速档仅需 ffmpeg）

## 2. 端到端冒烟（约 5 分钟）

用一段 **1–3 分钟**的测试音频（采访/对话类，两位说话人，中英夹杂更佳）：

- [ ] `prepare.py 测试音频 --model sensevoice` 生成 config（音频输入 `frame_path=null`）
- [ ] `transcribe_gguf.py --config ...` 产出 `<标题>_transcript.json`：
  - [ ] 文本**无日文假名**（KANA 过滤生效）
  - [ ] 带 VAD 段级 start/end 时间码
- [ ] `resegment_speakers.py`（3.5C）产出 `.sem.json`，说话人 ≥ 2 且无自造非法编号
- [ ] `build_document.py --auto` → 说话人1/2 中性命名，摘要/person_info 留空不报错
- [ ] `refine_paragraphs.py --in-place`（3.56）段落自然、备份 .bak 已生成
- [ ] `build_docx.py` 产出 .docx：每轮「角色（时间）」一行 + 内容另起一行；续段时间码独立成行

## 3. 回归检查点（改脚本后必看）

| 改动 | 必测 |
|------|------|
| `transcribe_gguf.py` | 假名过滤 + VAD 时间码 + 占位 SPEAKER_00 |
| `build_document.py` | `--review` / `--auto` / `--apply` 三模式 + 长轮次 ~160 字分段 |
| `build_docx.py` | 两行制格式 + `_md_escape`（跑 `test_md_escape.py`）+ 模型大小标注 |
| `resegment_speakers.py` | 编号白名单（非法编号回退）+ 12 句重叠上下文 |
| `setup_env.py` | `--verify` 幂等（重复跑不重复下载） |

## 4. 上架前（SkillHub）

- [ ] `pack_release.py` 打包 + 文件数校验通过
- [ ] README 更新日志已加新版本行；SKILL.md version 已 bump
- [ ] git 已 commit（含版本号），GitHub 已 push
