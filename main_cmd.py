"""Small command-line path for diagnostics and scripted paper Q&A."""
import argparse
import sys
from pathlib import Path

from src.audio_capture import list_devices
from src.context import Paper, build_prompt
from src.llm_client import LLMClient, safe_error
from src.settings import load_settings
from src.transcriber import SpeechTranscriber

if sys.platform == "win32":
    # PowerShell 7 expects UTF-8 from native processes.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def parser():
    result = argparse.ArgumentParser(description="InterPilot command-line helper")
    result.add_argument("--list-devices", action="store_true", help="列出输入与系统回环设备")
    result.add_argument("--audio", help="转写一个音频文件并作为讨论上下文")
    result.add_argument("--image", help="发送一张当前幻灯片截图")
    result.add_argument("--paper", help="导入论文 PDF")
    result.add_argument("--page", type=int, help="优先参考 PDF 物理页码")
    result.add_argument("--question", help="要给助手的任务；省略时使用 UI 设置中的 User prompt")
    result.add_argument("--transcribe-only", action="store_true", help="只输出音频转写，不调用 LLM")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.list_devices:
        for device in list_devices():
            kind = "系统回环" if device.get("isLoopbackDevice") else "输入"
            print(f"[{int(device['index'])}] {kind}: {device['name']}")
        return 0
    settings = load_settings()
    discussion = ""
    if args.audio:
        discussion = SpeechTranscriber(settings=settings).transcribe(args.audio)
        print(f"转写：{discussion}")
    if args.transcribe_only:
        return 0
    if args.question:
        settings.user_prompt = args.question
    paper = Paper.load(args.paper) if args.paper else None
    image = Path(args.image).read_bytes() if args.image else None
    if not any([discussion, paper, image]):
        parser().error("请提供 --audio、--image 或 --paper")
    prompt = build_prompt(settings, discussion, paper, args.page, False,
                          Path(args.image).name if args.image else "")
    client = LLMClient(settings=settings)
    try:
        client.get_response(prompt, image=image, callback=lambda text: print(text, end="", flush=True))
        print()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("失败：" + safe_error(exc), file=sys.stderr)
        raise SystemExit(1)
