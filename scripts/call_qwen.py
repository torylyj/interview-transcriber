"""
统一调用通义千问文本大模型（qwen-plus 等）的封装，供 Step 3.5（说话人识别）
与 Step 3.6（摘要生成）的「方式 B（外部 LLM API）」复用，避免在各处重复
dashscope 调用代码、降低版本不一致风险。

设置 API Key（二选一）：
  - 环境变量 DASHSCOPE_API_KEY
  - 命令行 --api-key

用法:
  # 从文件读取 prompt
  python call_qwen.py --prompt-file speaker_prompt.txt --model qwen-plus
  # 从标准输入读取 prompt
  echo "你是一个..." | python call_qwen.py --model qwen-plus
  # 直接传 prompt
  python call_qwen.py --prompt "把下面文本分成采访者和受访人" --model qwen-plus

完整 prompt 模板见 references/prompts.md。
"""

import os
import sys
import argparse
import threading
import functools

print = functools.partial(print, flush=True)


def with_timeout(seconds, func, *args, **kwargs):
    """在子线程中运行阻塞调用并加硬超时；超时直接 os._exit 终止，
    保证 bash 命令一定能返回，不会让上层 Agent 永久卡在等待里。"""
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
        print(f"❌ 调用通义千问超时（>{seconds}s）：可能是网络或服务端卡住，请稍后重试。")
        os._exit(1)
    if "err" in box:
        raise box["err"]
    return box["val"]

try:
    import dashscope
except ImportError:
    print("错误: dashscope 未安装。请先执行: pip install -U dashscope")
    sys.exit(1)


def main():
    p = argparse.ArgumentParser(description="统一调用通义千问文本大模型")
    p.add_argument("--prompt", default=None, help="直接传入 prompt 文本")
    p.add_argument("--prompt-file", default=None, help="prompt 文件路径")
    p.add_argument("--model", default="qwen-plus", help="模型名（默认 qwen-plus）")
    p.add_argument("--api-key", default=None, help="DashScope API Key（也可设环境变量 DASHSCOPE_API_KEY）")
    p.add_argument("--system", default=None, help="可选 system 提示")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("错误: 未提供 API Key。通过 --api-key 或环境变量 DASHSCOPE_API_KEY 传入。")
        sys.exit(1)
    dashscope.api_key = api_key

    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    elif args.prompt:
        prompt = args.prompt
    else:
        prompt = sys.stdin.read()

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = with_timeout(
            180, dashscope.Generation.call,
            model=args.model, messages=messages, result_format="message",
        )
    except Exception as e:
        print(f"调用失败: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 200:
        print(resp.output.choices[0].message.content)
    else:
        print(f"错误: HTTP {resp.status_code} {resp.output}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
