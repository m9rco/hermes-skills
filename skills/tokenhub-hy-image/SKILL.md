---
name: tokenhub-hy-image
description: "Use when generating/editing images via TokenHub Hy-Image."
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [tencent, tokenhub, hy-image, image-generation, img2img, 文生图, 图生图]
    category: creative
---

# TokenHub Hy-Image 生图（文生图 / 图生图）

通过腾讯云 TokenHub 调用 **hy-image-v3.5-preview** 生成/编辑图片。已验证可用（2026-10，用用户 API key）。

## 核心事实（踩坑总结）

| 项 | 值 |
|---|---|---|
| 端点 | `POST https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v35-generation` |
| 认证 | `Authorization: Bearer <API_KEY>`（从 config.yaml 腾讯云 provider 的 api_key 或环境变量 `TOKENHUB_API_KEY` 读取，见脚本 `load_api_key()`） |
| 模型 ID | `hy-image-v3.5-preview`（图生图/文生图/多轮编辑均可，最高 4K） |
| 输出 | `choices[0].delta.image.url`（临时签名 URL，**12 小时过期**，及时下载） |
| 尺寸 | `size` 参数 `${宽}x${高}`，宽高 ∈ [256, 8192]，面积 ≤ 16777216（4K）；不传则模型自主 |
| 参考图 | `messages[].content[]` 里 `{"type":"image_url", "image_url":{"url":"data:image/jpeg;base64,..."}}`，单图 ≤ 20MB，最多 20 张 |

**⚠️ 三个错误端点（勿用）**：
- `/v1/chat/completions` → 400004 模型不存在
- `/v1/images/generations` → 400004 模型不存在（Hy 生图不走 OpenAI 标准生图端点）
- thcli `+chat --model hy-image-v3.5-preview` → 400004（thcli 走在线推理服务 ID 体系，需 deploy endpoint；直接 API 更简单）

**付费前提**：hy-image 模型需在 [控制台-在线推理-视觉模型](https://console.cloud.tencent.com/tokenhub/inference?regionId=1&serviceType=VISION) 开启后付费，否则 401007/402。

## 请求体结构（图生图）

```json
{
  "model": "hy-image-v3.5-preview",
  "size": "1280x2293",
  "messages": [{"role": "user", "content": [
    {"type": "text", "text": "<指令：描述目标效果 + 必须保留的文字清单>"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<base64>"}}
  ]}]
}
```

文生图去掉 `image_url` 元素即可。

## 使用脚本

```bash
# 文生图
python3 scripts/hy_image_gen.py --prompt "..." --size 1280x2293 --out /tmp/out.png

# 图生图（带参考图）
python3 scripts/hy_image_gen.py --prompt "..." --size 1280x2293 --ref-image /path/to/img.jpg --out /tmp/out.png

# 4K
python3 scripts/hy_image_gen.py --prompt "..." --size 4096x4096 --out /tmp/out.png
```

## 设计哲学提示词（用户偏好，重要）

用户强烈反对"土味电竞风"（巨型霓虹发光、斜切、花哨描边）。偏好：
- **苹果发布会/保时捷官方海报哲学**：深空黑渐变、大片留白、单一主体、克制排版、细字体、黑白银灰主色（可加一点品牌色点缀）
- 无霓虹、无发光描边、无斜切、无多余装饰
- 核心信息点必须保留：赞助商、圈速/数据、赛车手、姓名、车辆型号
- 车要**真实比例不变形**；车手要**半身照清晰入镜**（不要只放文字、不要丢失人物）

## 输出验证

1. 下载 URL 后用 `sips -Z 1200` 压缩 + macOS 本地 OCR（`swift /tmp/ocr.swift <img>`，Vision framework）检查关键文字是否保留
2. 核对尺寸：`sips -g pixelWidth -g pixelHeight`
3. 若文字微变（如 G87-M2→G87-MB）：重跑，prompt 强调"逐字精确保留"；或告知用户可接受度

## 快速路径

用户常见请求"优化这张图""换风格"：图生图 + 设计哲学 prompt + 多版本并行（同一脚本不同 seed 或不同风格描述，后台跑 + wait）。输出到 /tmp 并 MEDIA: 发送。
