# 错误处理与失败恢复（详细）

核心原则：**失败要可见、可恢复、有兜底**。任何环节出错都要给用户一个明确的"下一步"，而不是卡死或静默产出残缺文档。

## 各环节失败信号与回退动作

- **Step 1 预处理（ffmpeg）失败**：文件损坏 / 格式不支持 / 无 ffmpeg。
  → 提示用户检查源文件，列出 `ffmpeg -version` 验证；无法处理则终止该文件并说明，不要反复重试。
  → `extract_frame.py` 抽帧失败时会兜底抽第 5 秒；仍失败则报错退出。

- **Step 2.6 获取时长（ffprobe）失败**：无法判断时长。
  → 保守按"长音频"处理（自动切段），并在日志标注"时长未知，已按切段处理"。

- **Step 3 本地模型下载/加载失败**：
  - SenseVoice/Paraformer（魔搭社区）失败 → 提示网络/磁盘，给出 `pip install funasr modelscope` + `snapshot_download` 手动命令；可建议改用 Paraformer 或云端。
  - （faster-whisper / pyannote 已移出默认流程，默认不装；如手动安装后失败 → 打印手动下载指南，并提示"可改用 SenseVoice（魔搭直连）或云端 Qwen3-ASR-Flash"）。
  - 依赖缺失（funasr 未装）→ 直接打印 `pip install funasr modelscope` 命令后退出。

- **Step 3 云端 API 失败/超时/配额耗尽**：
  - 偶发超时 → 自动重试（最多 2 次，指数退避）。
  - 持续失败（Key 无效 / 配额用尽 / 无网络）→ 若本地模型可用则**自动降级本地转录**并告知用户；否则明确报错并给出申请/配置 DashScope Key 的指引。

- **Step 3.5 LLM 说话人识别异常**：
  - 仅识别出 1 个说话人标签、或轮次数远少于音频时长预期 → 告警"说话人切分可能异常"，建议回看原始文本或在 Step 3.9 由用户纠正（本地无需 HF Token）。
  - 说话人命名明显颠倒（如把说话人1/2 标反）→ 在 Step 3.9 预览环节由用户发现并纠正。

- **Step 3.8 生成 .docx 依赖缺失**：python-docx 未装 → 打印 `pip install python-docx pillow` 后退出，不破坏已生成的 `_document.json`（用户可稍后重跑生成）。

- **Step 4 上传平台失败**（如钉钉 API 报错）→ 保留本地 `.docx`，告知用户上传失败原因，提供本地文件路径作为兜底。
