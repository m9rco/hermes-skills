#!/usr/bin/env python3
"""Synthesize an MP3 with Tencent Cloud TokenHub; Python 3, no dependencies."""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ENDPOINT = "https://tokenhub.tencentmaas.com/v1/wand/minimax-tts/sync_tts"


def parse_args():
    parser = argparse.ArgumentParser(description="腾讯云 TokenHub 文本转 MP3")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="需要朗读的原文")
    source.add_argument("--text-file", type=Path, help="UTF-8 文本文件")
    parser.add_argument("--output", type=Path, help="输出 MP3 路径；默认写入 output/，文件名含时间戳")
    parser.add_argument("--model", default="minimax-speech-2.8-hd", help="默认 minimax-speech-2.8-hd；极速版 minimax-speech-2.8-turbo")
    parser.add_argument("--voice", default="male-qn-qingse")
    parser.add_argument("--speed", type=float, default=1.0, help="语速：0.5–2，默认 1")
    parser.add_argument("--volume", type=float, default=1.0, help="音量：大于 0 且不超过 10")
    parser.add_argument("--pitch", type=int, default=0, help="音调：-12–12，默认 0")
    parser.add_argument("--emotion", choices=("happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"), default=None, help="可选情绪；不传时由模型自动匹配，2.8 模型不支持 whisper")
    args = parser.parse_args()
    if not 0.5 <= args.speed <= 2:
        parser.error("--speed 必须在 0.5–2 之间")
    if not 0 < args.volume <= 10:
        parser.error("--volume 必须大于 0 且不超过 10")
    if not -12 <= args.pitch <= 12:
        parser.error("--pitch 必须在 -12–12 之间")
    if args.emotion == "whisper" and args.model in {"minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"}:
        parser.error("minimax-speech-2.8-hd 和 minimax-speech-2.8-turbo 不支持 --emotion whisper")
    text = args.text if args.text is not None else args.text_file.read_bytes().decode("utf-8-sig")
    if not text.strip():
        parser.error("朗读文本不能为空")
    if len(text) >= 10000:
        parser.error("单次文本必须少于 10000 个字符，请按自然段拆分")
    output = args.output or Path("output") / ("tokenhub-tts-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".mp3")
    if output.suffix.lower() != ".mp3":
        parser.error("--output 必须使用 .mp3 扩展名")
    args.output = output.expanduser().resolve()
    args.metadata = args.output.with_suffix(".json")
    if args.output.exists() or args.metadata.exists():
        parser.error("输出 MP3 或同名 JSON 已存在，请使用新的 --output 路径")
    args.text = text
    return args


def synthesize(args, api_key):
    payload = {
        "model": args.model,
        "text": args.text,
        "voice_setting": {
            "voice_id": args.voice,
            "speed": args.speed,
            "vol": args.volume,
            "pitch": args.pitch,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": False,
        "output_format": "hex",
    }
    if args.emotion is not None:
        payload["voice_setting"]["emotion"] = args.emotion
    args.output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            http_status = response.status
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").replace(api_key, "[REDACTED]")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000]}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败：{exc.reason}；未自动重试") from None
    if not isinstance(result, dict):
        raise RuntimeError("接口返回的 JSON 不是对象")
    status = result.get("base_resp") or {}
    data = result.get("data") or {}
    if not isinstance(status, dict) or result.get("error") or status.get("status_code") != 0:
        raise RuntimeError("语音合成失败：" + json.dumps({
            "base_resp": status, "error": result.get("error"), "trace_id": result.get("trace_id")
        }, ensure_ascii=False))
    if not isinstance(data, dict) or data.get("status") != 2 or not data.get("audio"):
        raise RuntimeError("接口未返回完整音频；trace_id=" + str(result.get("trace_id")))
    try:
        audio = bytes.fromhex(data["audio"])
    except (ValueError, TypeError):
        raise RuntimeError("接口返回的音频不是有效的 hex 数据") from None
    if not audio:
        raise RuntimeError("接口返回了空音频")
    info = result.get("extra_info") or {}
    if not isinstance(info, dict):
        raise RuntimeError("接口返回的 extra_info 不是对象")
    metadata = {
        "http_status": http_status,
        "endpoint": ENDPOINT,
        "model": args.model,
        "voice_id": args.voice,
        "speed": args.speed,
        "volume": args.volume,
        "pitch": args.pitch,
        "text": args.text,
        "audio_file": args.output.name,
        "audio_bytes": len(audio),
        "trace_id": result.get("trace_id"),
        "base_resp": status,
        "extra_info": info,
        "usage": result.get("usage"),
    }
    if args.emotion is not None:
        metadata["emotion"] = args.emotion
    metadata_json = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").replace(api_key, "[REDACTED]")
    with args.output.open("xb") as audio_file:
        audio_file.write(audio)
    with args.metadata.open("x", encoding="utf-8") as metadata_file:
        metadata_file.write(metadata_json)
    summary = {
        "audio_path": str(args.output),
        "metadata_path": str(args.metadata),
        "http_status": http_status,
        "model": args.model,
        "voice_id": args.voice,
        "duration_ms": info.get("audio_length"),
        "audio_bytes": len(audio),
        "trace_id": result.get("trace_id"),
        "usage": result.get("usage"),
    }
    if args.emotion is not None:
        summary["emotion"] = args.emotion
    print(json.dumps(summary, ensure_ascii=False, indent=2).replace(api_key, "[REDACTED]"))


def main():
    api_key = ""
    try:
        args = parse_args()
        api_key = os.environ.get("TOKENHUB_API_KEY", "").strip()
        if not api_key and sys.stdin.isatty():
            api_key = getpass.getpass("TokenHub API key: ").strip()
        if not api_key:
            raise RuntimeError("缺少 TOKENHUB_API_KEY；请在当前进程环境中设置密钥，或从交互终端运行以隐藏输入")
        synthesize(args, api_key)
        return 0
    except (OSError, RuntimeError, ValueError, EOFError) as exc:
        message = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
        print("错误：" + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
