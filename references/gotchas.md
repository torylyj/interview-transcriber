# 踩坑与硬性规则（references/gotchas.md）

> 本文件汇总 `interview-transcriber` 在真实环境跑通全流程时踩过的所有坑与对应硬性规则。
> 实测环境：**Windows + 托管 Python 3.13（无 C++ 编译器）+ RTX 4070 GPU + 钉钉 dws**。
> 改技能或首次跑长任务前，建议通读本文件，避免重复踩坑。

---

## 1. 本地转录环境（setup_env.py）

### 坑 1.1：Python 3.13 + 无编译器的 Windows 上 funasr 装不上
- **现象**：`funasr` 依赖 `editdistance`，后者需本地 C++ 编译器源码编译；Python 3.13 太新、官方无预编译 wheel → 整批 `pip install` 卡在 `editdistance` 编译失败，**连带 torch 都装不上**，自检一直缺包。
- **对策（已固化进 setup_env.py）**：
  - `funasr` 的 wheel 本身是纯 Python，**不需要 editdistance 即可安装** → 用 `--no-deps` 单独装 funasr；
  - 跳过 `editdistance`（SenseVoice 推理不碰它，实测 `from funasr import AutoModel` 可导入）；
  - 随后补齐 `torch` + `numpy/scipy/soundfile/librosa/torchaudio/oss2` 等；
  - 逐包安装 + `verify_environment()` 真实 import 自检，单个失败不影响其他。
- **根因教训**：本技能默认**本地转录**，在 Python 3.13 托管版上首次跑必踩编译坑；若要彻底规避，可锁 **Python 3.11**（官方有预编译 wheel）。

### 坑 1.2：先装 CPU torch 再切 GPU 走了大弯路
- **现象**：先装了 `+cpu` 版 torch，用户要求 GPU 后才卸载重装 cu128（2.75GB，pytorch.org 国内源偏慢，约 15 分钟）。
- **对策（已固化）**：`setup_env.py` 启动时**检测 NVIDIA GPU**（`nvidia-smi` 可用即认为有 GPU），有则装 CUDA 版 torch，无则 CPU 版。**默认仍是本地模型推理**，不切云端。
- **注意**：换国内 CUDA 镜像不一定有 3.13 的 wheel，若 pytorch.org 太慢，宁可告知用户等待，不要贸然换源导致装不上。

### 坑 1.3：setup_env.py 必须保持幂等（已装则跳过，勿改回无条件安装）
- **现象（早期版本踩过）**：`install_python_deps` 对每个包无条件 `pip install`、`install_torch` 永远重装，导致已装环境（尤其 2.7GB CUDA torch）每次运行都重复下载，浪费十余分钟还可能再踩编译坑。
- **对策（已固化）**：安装前用 `is_importable(mod)` 真实 import 探测；Python 依赖已装即跳过（`--force` 可强制重装）；`install_torch` 已装且版本匹配（要 GPU 且有 CUDA / 要 CPU 有 torch 即可）也跳过。今后新增/调整安装逻辑，**务必保持此幂等行为**，不要改回「无条件 pip install」。

---

## 2. SenseVoice 转录本身

### 坑 2.1：sentence_timestamp 仅对 SenseVoice 不生效（Paraformer-VAD 不受限）
- **现象**：传 `sentence_timestamp=True`，SenseVoice 每段仍只产出 1 个整块文本（`<|withitn|>` 只是语言/itn 标签，不是句分隔），`segments` 字段只有 3 个大块、时间码全 0。
- **对策（已固化进 build_document.py）**：按中文标点把每段切成句子，再依「各段 offset + 时长（来自 transcribe_config.json 的 segments 与音频文件）线性插值」得到逐句时间码。
- ⚠️ **硬性规则**：**仅 SenseVoice** 的逐句时间码是**插值估算**（Paraformer-VAD 返回真实句级 sentence_info，无需插值）；无论哪种，**段落级边界精确，段内为估算值**。文档已如实标注，SenseVoice 路径**不得标「精确到秒」**。（SKILL.md / build_docx.py 均已修正，勿回退。）

### 坑 2.2：`<|withitn|>` 当段间分隔切分 → 段丢失
- **现象**：临时脚本把 `<|withitn|>` 当「段之间分隔」去 split，导致段 1 整段丢失、段 3 丢失、时间码错乱。
- **对策**：`build_document.py` 标准脚本直接消费结构化 `segments`（而非解析 raw_text），彻底绕开脆弱的文本正则切分。

### 坑 2.3：说话人分离交还模型（Paraformer + CAM++），本地不再靠 LLM
- **现象（早期版本踩过）**：SenseVoice 全部标 `SPEAKER_00`，无说话人分离；曾用关键词/段落长度启发式初分，把受访人长独白里的「好/哪里/补充」等误判为采访者（实测 20+ 处），严重失真。也曾让 LLM 逐句语义切分，慢且不可控。
- **对策（v1.7.0 起固化）**：**本地说话人分离交给模型**——Paraformer-large 在 `generate()` 时加载 `spk_model="cam++"`（CAM++ 说话人嵌入，魔搭社区开源、约 20MB、无需 HF Token），单次推理即返回每句 `spk` id，**按声纹自动聚类、无需指定人数**。CAM++ 同为阿里开源、与 Paraformer 同属 FunASR 生态，离线可用。
- ⚠️ **硬性规则**：
  - **本地**：`transcribe_local.py` 已内置 CAM++，说话人 id 由模型产出，**不再需要 LLM 做说话人切分**；`build_document.py` 统一按「首次出现顺序」中性命名为 说话人1/2/3……（`--auto`），如需真名/角色用 `--apply` 的 `{speaker_roles}` 覆盖（键为 说话人1/2/3），**绝不可再用逐句启发式判定说话人**。
  - **云端**：Qwen3-ASR-Flash 仍不直接分离说话人，需 LLM 做语义分段（方式 A）；这与本地路径不同，勿混淆。
  - **SenseVoice 本地路径**：本身无说话人分离，如需说话人也应加载 CAM++（`funasr_spk` 参数已支持），或走 Paraformer 默认路径。
- ⚠️ **已知边界（务必诚实告知用户）**：CAM++ 声纹聚类在极嘈杂街头/重叠说话场景下，偶发把同一人误判为两人、或把两人并成一人。出现时用 `build_document.py --apply corrections.json`（`{"speaker_roles": {"说话人1": "张三"}}`）一键纠正即可；**不可**为「追求 100% 准确」回退到旧的 LLM 逐句切分（旧法 20+ 误判、且慢）——CAM++ 已是本地最优解，个别误差靠 `--apply` 兜底。

### 坑 2.4：长轮次整块输出难读
- **现象**：每个说话人是一整大块（某说话人首段 1275 字挤一团），无段落换行。
- **对策（已固化）**：`build_document.py` 的 `split_paragraphs` 把长独白按 ~160 字或 4 句切成多段，每段带首句时间码；`build_docx.py` 的 .docx 与 Markdown 均逐段输出。

---

## 3. 钉钉分发（dws）

### 坑 3.1：在线文档无法渲染本地图片路径
- **现象**：`.docx` 里的静帧图是本地路径 `H:/.../人物静帧.jpg`，写进在线文档 Markdown 后**不显示**（在线文档不认本地路径）。
- ⚠️ **硬性规则**：要往在线文档放图，必须用 `dws doc media insert --node <nodeId> --file <本地图> --index 0`（三步：取上传凭证 → 传 OSS → 插块）。导出上传用 Markdown 时，给 `build_docx.py` 加 `--no-frame` 参数（脚本不再写入本地图片行）；原 .docx 才保留本地图。

### 坑 3.2：`dws auth status` 会卡 2 分钟
- **现象**：该命令卡 2 分钟无返回（疑似到钉钉服务网络慢）；但 `doc search/create/send` 等**业务命令正常**。
- **对策**：别依赖 `auth status` 判断登录态，直接试探业务命令（`doc search/create/send` 正常即已登录）；或给 dws 统一加 `--timeout`。

### 坑 3.3：同主题重复建文档
- **现象**：同一采访二改三改，若每次 `doc create` 会多出冗余文件。
- ⚠️ **修订同一采访请复用同一文档**：用 `dws doc update --mode overwrite`（配合 `--content-file`）覆盖，**勿再 `doc create`** 新建，避免冗余；新采访才 create。

### 坑 3.4：未经授权发钉钉消息
- **现象**：覆盖文档（overwrite）用户无异议，但 `chat message send` 发消息需明确同意。
- ⚠️ **硬性规则**：`dws doc update/overwrite` 无需每次问；但 `dws chat message send` **必须用户明确授权**才执行。用户明确说不要发给某人时，本次及后续都不再发。

---

## 4. 工程执行纪律（Agent 自身）

### 坑 4.1：长任务后台被回收，误判完成
- **现象**：GPU 转录任务在段 2 启动后进程被回收（ps 看不到进程），但段 1 跑完、段 2/3 没跑完，易误以为「完成了」。
- **对策**：长命令放后台 + 轮询；**声明完成前必须核对产出文件存在且非空**（transcript.json / document.json / docx / 在线文档均查）。脚本已有 `with_timeout` 看门狗 + 分段落盘（`_transcript.partial.json`）兜底。

### 坑 4.2：Windows 路径 / 工具差异
- `ffmpeg/ffprobe` 是原生 Windows 程序，**不认 Git Bash 的 `/h/` 虚拟路径**，要给 `H:/...` 这种 Windows 风格路径。
- `bc` 不可用（用 Python 算）；bash heredoc 不吃 `\s`（正则写进 .py 文件）。

### 坑 4.3：改技能代码必须同步更新日志与结构文档
- **现象**：曾漏更 README 更新日志、曾出现 SKILL.md 描述与渲染脚本不一致。
- **对策**：改动落地后，同步更新 README「📝 更新日志」+ SKILL.md 描述 + references（如改了输出结构，必须同步 output_schema.md / build_docx.py / prompts.md 三处，否则「文档说了、实际不执行」）。
