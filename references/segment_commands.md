# 切段与多段合并命令（ffmpeg）

## 获取音频时长（Step 2.6）

```bash
DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "输出.mp3")
# 获取失败（时长未知）时，保守按"长音频"处理：自动切段并在日志标注"时长未知，已按切段处理"
```

## 切段（单一文件，4 分钟/段，留 1 分钟余量）

```bash
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 0   -t 240 _seg1.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 240 -t 240 _seg2.mp3 -y
ffmpeg -i 输出.mp3 -f mp3 -acodec libmp3lame -ab 192k -ar 16000 -ac 1 -ss 480 -t 240 _seg3.mp3 -y
# ... 依此类推，每段 240 秒，offset 递增
```

写入 config 的 `segments`（切段时）：
```json
"segments": [
  {"file": "_seg1.mp3", "offset": 0},
  {"file": "_seg2.mp3", "offset": 240},
  {"file": "_seg3.mp3", "offset": 480}
]
```
不切段（整段）时：
```json
"segments": [{"file": "输出.mp3", "offset": 0}]
```

## 多段输入合并（同一采访被拆成多个文件，Step 1d）

> 仅当用户**明确说明**这几个文件属于同一段采访时才合并；否则每个文件各成一篇文档。

**视频**：每个文件分别抽取静帧（`extract_frame.py` 将视频五等分、各抽 1 帧并跨片段比选最清晰帧，输入定位不软解整段视频）+ 各自转 MP3，再把所有 MP3 合并为 `输出.mp3`：
```bash
# 每个文件先转成统一格式的 16k 单声道 mp3
ffmpeg -i "v1.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "v1.mp3" -y
ffmpeg -i "v2.mp4" -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "v2.mp3" -y
# 用 concat demuxer 合并（写文件列表，统一重采样）
( echo "file 'v1.mp3'"; echo "file 'v2.mp3'" ) > _merge_list.txt
ffmpeg -f concat -safe 0 -i _merge_list.txt -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y
# 静帧跨片段比选（取全局最清晰帧）
python <skill_dir>/scripts/extract_frame.py "v1.mp4" "v2.mp4" "人物静帧.jpg"
```

**音频**：每个文件重采样（如需）后合并：
```bash
ffmpeg -i "a1.m4a" -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "a1.mp3" -y
ffmpeg -i "a2.m4a" -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "a2.mp3" -y
( echo "file 'a1.mp3'"; echo "file 'a2.mp3'" ) > _merge_list.txt
ffmpeg -f concat -safe 0 -i _merge_list.txt -vn -acodec libmp3lame -ab 192k -ar 16000 -ac 1 "输出.mp3" -y
```

合并后，Step 2.6 的切段决策作用在合并后的 `输出.mp3` 总时长上；文档标题取第一个文件的命名/时间信息。
