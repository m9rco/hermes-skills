#!/usr/bin/env python3
"""Design an original voice with Tencent Cloud TokenHub; Python 3 standard library."""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ENDPOINT = "https://tokenhub.tencentmaas.com/v1/wand/minimax-tts/sync_design"
MODEL = "minimax-voice-design"


def parse_args():
    parser = argparse.ArgumentParser(description="腾讯云 TokenHub 文生原创音色与试听")
    parser.add_argument("--prompt-file", type=Path, required=True, help="UTF-8 音色描述文件")
    parser.add_argument("--preview-text-file", type=Path, required=True, help="UTF-8 试听文本文件，最多 500 字符")
    parser.add_argument("--output", type=Path, required=True, help="试听音频保存路径；实际格式需另行核实")
    args = parser.parse_args()
    args.prompt = args.prompt_file.read_bytes().decode("utf-8-sig")
    args.preview_text = args.preview_text_file.read_bytes().decode("utf-8-sig")
    if not args.prompt.strip():
        parser.error("音色描述不能为空")
    if not args.preview_text.strip() or len(args.preview_text) > 500:
        parser.error("试听文本必须非空且不超过 500 个字符")
    args.output = args.output.expanduser().resolve()
    args.metadata = args.output.with_suffix(".json")
    if args.output == args.metadata:
        parser.error("--output 不能使用 .json 扩展名")
    if args.output.exists() or args.metadata.exists():
        parser.error("输出音频或同名 JSON 已存在，请使用新的 --output 路径")
    return args


def design_voice(args, api_key):
    payload = {
        "model": MODEL,
        "prompt": args.prompt,
        "preview_text": args.preview_text,
        "output_format": "hex",
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            http_status = response.status
            if not 200 <= http_status < 300:
                raise RuntimeError(f"HTTP {http_status}；未自动重试")
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4800).decode("utf-8", errors="replace").replace(api_key, "[REDACTED]")
        try:
            error = json.loads(detail)
            if isinstance(error, dict):
                detail = json.dumps({
                    key: error[key] for key in ("error", "message", "base_resp", "trace_id") if key in error
                }, ensure_ascii=False)
        except ValueError:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail[:1200]}；未自动重试") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败：{exc.reason}；未自动重试") from None
    if not isinstance(result, dict):
        raise RuntimeError("接口返回的 JSON 不是对象")
    status = result.get("base_resp")
    if not isinstance(status, dict) or result.get("error") or status.get("status_code") != 0:
        detail = json.dumps({
            "status_code": status.get("status_code") if isinstance(status, dict) else None,
            "status_msg": status.get("status_msg") if isinstance(status, dict) else None,
            "trace_id": result.get("trace_id"),
            "error": result.get("error"),
        }, ensure_ascii=False).replace(api_key, "[REDACTED]")
        raise RuntimeError(f"音色设计失败：{detail[:1200]}；未自动重试")
    voice_id = result.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise RuntimeError("接口未返回有效 voice_id")
    trial_audio = result.get("trial_audio")
    if not isinstance(trial_audio, str):
        raise RuntimeError("接口未返回 hex 试听音频")
    try:
        audio = bytes.fromhex(trial_audio)
    except ValueError:
        raise RuntimeError("接口返回的试听音频不是有效的 hex 数据") from None
    if not audio:
        raise RuntimeError("接口返回了空试听音频")
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "http_status": http_status,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "prompt": args.prompt,
        "preview_text": args.preview_text,
        "voice_id": voice_id,
        "audio_file": args.output.name,
        "audio_bytes": len(audio),
        "trace_id": result.get("trace_id"),
        "base_resp": status,
        "usage": result.get("usage"),
    }
    metadata_json = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").replace(api_key, "[REDACTED]")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as audio_file:
        audio_file.write(audio)
    with args.metadata.open("x", encoding="utf-8") as metadata_file:
        metadata_file.write(metadata_json)
    summary = {
        "audio_path": str(args.output),
        "metadata_path": str(args.metadata),
        "http_status": http_status,
        "model": MODEL,
        "voice_id": voice_id,
        "audio_bytes": len(audio),
        "created_at": metadata["created_at"],
        "trace_id": result.get("trace_id"),
        "usage": result.get("usage"),
    }
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
        design_voice(args, api_key)
        return 0
    except (OSError, RuntimeError, ValueError, EOFError) as exc:
        message = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
        print("错误：" + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
