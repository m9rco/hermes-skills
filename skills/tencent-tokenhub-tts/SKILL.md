---
name: tencent-tokenhub-tts
description: 通过腾讯云 TokenHub 将文本合成为 MP3 语音，支持指定音色、语速、音量、音调和情绪，也可按文字描述设计原创音色。用于用户要求朗读、配音、文字转语音、原创角色声音设计或调用 TokenHub 语音接口；不用于语音识别、声音克隆或实时通话。
---

# 腾讯云 TokenHub 语音合成

使用本 skill 的 [scripts/synthesize.py](scripts/synthesize.py) 调用同步语音接口，并交付可播放的 MP3 及调用元数据。脚本仅依赖 Python 3 标准库。

## 合成

保留用户提供的原文，按其要求设置音色和声音参数。只有用户要求改写时才调整文案。没有指定参数时使用已验证的默认值：模型 `minimax-speech-2.8-hd`、音色 `male-qn-qingse`、语速 1、音量 1、音调 0。单次文本必须非空且少于 10000 个字符；超限时按自然段拆分，保持顺序分别生成，并在交付时说明各文件对应的片段。

凭据从 `TOKENHUB_API_KEY` 环境变量读取。若用户已在当前对话授权使用其提供的 token，可仅向调用脚本的子进程临时传入；不要把 token 写入 skill、脚本、命令行参数、输出文件或日志，也不要为此永久保存密钥。缺少凭据时说明所需环境变量；脚本仅在交互终端可隐藏输入密钥，不要在无人值守工具调用中等待输入。

优先将多行文案存为 UTF-8 文件，避免 shell 引号破坏文本：

```bash
python3 <skill-directory>/scripts/synthesize.py \
  --text-file input.txt \
  --output output/narration.mp3
```

简短文本可用 `--text "你好，欢迎收听。"`，与 `--text-file` 二选一。可省略 `--output`，默认输出到当前目录下 `output/tokenhub-tts-时间戳.mp3`。技能迁移后按本 skill 目录解析脚本路径。

按用户需要添加参数：

- `--model`：默认 `minimax-speech-2.8-hd`；用户需要低延迟时可用 `minimax-speech-2.8-turbo`。
- `--voice`：系统音色 ID，默认 `male-qn-qingse`；不要凭空编造音色 ID。
- `--speed`：0.5–2；`--volume`：大于 0 且不超过 10；`--pitch`：-12–12。
- `--emotion`：可选 `happy`（高兴）、`sad`（悲伤）、`angry`（愤怒）、`fearful`（害怕）、`disgusted`（厌恶）、`surprised`（惊讶）、`calm`（中性）、`fluent`（生动）、`whisper`（低语）。不传时不发送此字段，由模型自动匹配；`minimax-speech-2.8-hd` 和 `minimax-speech-2.8-turbo` 不支持 `whisper`，脚本会在请求前拒绝该组合。取值与限制见[腾讯云官方接口文档](https://cloud.tencent.com/document/product/1823/135796)。

本脚本固定输出 MP3、32000 Hz、128 kbps、单声道。

## 按需设计原创音色

用户需要系统音色之外的角色声音时，使用 [scripts/design_voice.py](scripts/design_voice.py) 调用[官方文生音色接口](https://cloud.tencent.com/document/product/1823/135797)。它根据文字描述创建全新原创音色，不会修改已选音色的声纹。将性别、成年年龄、声音特征与口音意图写入描述；例如“四川女孩说普通话”的效果需要实际试听确认，不要伪造 `accent` 参数或仅凭 prompt 宣称口音已实现。

```bash
python3 <skill-directory>/scripts/design_voice.py \
  --prompt-file voice-description.txt \
  --preview-text-file preview.txt \
  --output output/designed-voice.bin
```

两个文本文件与输出路径均必填；试听文本非空且最多 500 字符。模型固定为 `minimax-voice-design`，服务生成并返回 `voice_id`。脚本沿用上述凭据、不重试、不覆盖策略，保存试听音频及含描述、试听文本、模型、返回 ID、时间和用量的相邻 JSON，不保存音频 hex。试听由平台默认 TTS 引擎生成；未说明的引擎型号、时长或编码参数不推断，先用 `ffprobe` 核实实际音频格式，再提供可播放文件与试听判断。选定后将返回的 `voice_id` 传入合成脚本的 `--voice`。

临时音色 7 天内未正式用于语音合成会被删除；首次正式合成收取音色设计费，设计试听本身也按字符计费。根据用户已授权的设计与合成范围执行。

## 核验与交付

脚本校验 HTTP 状态、`base_resp` 和 `data`，保存音频及相邻 `.json` 元数据。默认不覆盖现有文件；发生路径冲突时选用新文件名。只有脚本成功且音频实际落盘后，才报告合成完成，提供音频文件链接，并从返回结果说明实际模型、音频时长；未返回的字段不要猜测。

显式指定情绪时，相邻 JSON 元数据与输出摘要都会记录所用 `emotion`；不传时保持原有请求和记录格式。

脚本不自动重试。请求失败或超时可能已经产生消费，先依据服务返回定位原因，不盲目重试、切换密钥或改用其他区域。不要输出包含凭据的请求头或完整调试转储。

已验证端点：`https://tokenhub.tencentmaas.com/v1/wand/minimax-tts/sync_tts`。需要新增模型、音色或接口能力时，先查阅[腾讯云官方接口文档](https://cloud.tencent.com/document/product/1823/135796)，再决定是否扩展脚本。
