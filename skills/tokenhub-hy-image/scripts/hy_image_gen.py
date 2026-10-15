#!/usr/bin/env python3
"""TokenHub Hy-Image 文生图/图生图 CLI。

用法:
  # 文生图
  python3 hy_image_gen.py --prompt "一只猫" --size 1024x1024 --out /tmp/cat.png

  # 图生图（参考图）
  python3 hy_image_gen.py --prompt "换成水彩风" --ref-image /path/to/img.jpg --out /tmp/out.png

  # 4K 输出
  python3 hy_image_gen.py --prompt "..." --size 4096x4096 --out /tmp/out.png

可选: --seed N, --session NAME (多轮同 session 提升 KV 命中), --api-key XXX
默认 key 从 ~/.hermes/config.yaml 的腾讯云 provider 读取。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request

ENDPOINT = "https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v35-generation"
MODEL = "hy-image-v3.5-preview"


def load_api_key():
    """从 Hermes config.yaml 读腾讯云 provider 的 api_key。"""
    p = os.path.expanduser("~/.hermes/config.yaml")
    try:
        with open(p) as f:
            text = f.read()
        m = re.search(r"base_url:\s*https://tokenhub\.tencentmaas\.com/v1.*?api_key:\s*(\S+)",
                      text, re.S)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    key = os.environ.get("TOKENHUB_API_KEY")
    if key:
        return key
    print("ERROR: 未找到 API key（config.yaml 腾讯云 provider 或 TOKENHUB_API_KEY）", file=sys.stderr)
    sys.exit(1)


def build_messages(prompt, ref_image=None):
    content = [{"type": "text", "text": prompt}]
    if ref_image:
        with open(ref_image, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(ref_image)[1].lower().lstrip(".") or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{ext};base64,{b64}"},
        })
    return [{"role": "user", "content": content}]


def main():
    ap = argparse.ArgumentParser(description="TokenHub Hy-Image 生图")
    ap.add_argument("--prompt", required=True, help="生成指令")
    ap.add_argument("--ref-image", default=None, help="参考图路径（图生图）")
    ap.add_argument("--size", default=None, help="如 1280x2293 或 4096x4096（不传则模型自主）")
    ap.add_argument("--seed", type=int, default=None, help="生成种子（0/缺省=随机）")
    ap.add_argument("--session", default=None, help="会话 ID（多轮编辑保持同一值）")
    ap.add_argument("--api-key", default=None, help="临时覆盖 API key")
    ap.add_argument("--out", default="hy_image_out.png", help="输出文件路径")
    ap.add_argument("--timeout", type=int, default=590, help="API 超时秒数")
    args = ap.parse_args()

    key = args.api_key or load_api_key()
    payload = {"model": MODEL, "messages": build_messages(args.prompt, args.ref_image)}
    if args.size:
        payload["size"] = args.size
    if args.seed is not None:
        payload["seed"] = args.seed
    if args.session:
        payload["session"] = args.session

    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    print(f"POST {ENDPOINT} | model={MODEL} size={args.size or 'auto'}")
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"FAIL HTTP {e.code}: {e.read()[:400]}", file=sys.stderr)
        sys.exit(1)

    delta = d.get("choices", [{}])[0].get("delta", {})
    img = delta.get("image", {})
    url = img.get("url", "")
    if not url:
        print("FAIL: 响应无图片 URL:", json.dumps(d)[:400], file=sys.stderr)
        sys.exit(1)
    print(f"生成尺寸: {img.get('width')}x{img.get('height')}")
    print(f"URL: {url[:120]}...")
    subprocess.run(["curl", "-s", "-o", args.out, url], timeout=args.timeout)
    print(f"已保存: {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
