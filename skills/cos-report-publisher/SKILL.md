---
name: cos-report-publisher
description: 将 HTML 报告上传到腾讯云 COS，返回公开访问 URL。当我需要给你报告时，直接上传并告诉你 URL。
---

# COS Report Publisher

将 HTML 或其他文件上传到腾讯云对象存储，返回公开可访问的 URL。

## COS 配置

| 参数 | 值 |
|---|---|
| SecretId | `$COS_SECRET_ID`（环境变量） |
| SecretKey | `$COS_SECRET_KEY`（环境变量） |
| Region | `ap-guangzhou` |
| Bucket | `t-gz-1252130512` |
| Base Path | `mlab-work-1` |
| Public URL Prefix | `https://s.0x06.cn` |

## 使用方式

### CLI（推荐）

```bash
~/.hermes/scripts/cos_upload.sh <本地文件路径>
```

示例：
```bash
# 自动生成 key
~/.hermes/scripts/cos_upload.sh report.html
# → https://s.0x06.cn/mlab-work-1/report-20260619-172351-xxxxxxxx.html

# 指定 key
~/.hermes/scripts/cos_upload.sh report.html --key my-reports/demo.html
# → https://s.0x06.cn/mlab-work-1/my-reports/demo.html

# 禁止缓存（实时报告）
~/.hermes/scripts/cos_upload.sh report.html --no-cache
```

### Python（在 Hermes 工具中）

```python
from hermes_tools import terminal

# 生成 HTML 并写入临时文件
html = "<h1>报告标题</h1><p>内容...</p>"
with open("/tmp/report.html", "w") as f:
    f.write(html)

# 上传到 COS
result = terminal(f"uv run python3 ~/.hermes/scripts/cos_upload.py /tmp/report.html")
url = result["output"].strip()
# → url = "https://s.0x06.cn/mlab-work-1/report-..."
```

## 工作流

1. 生成 HTML 内容（报告、图表、仪表盘等）  
   可使用模板 `templates/report.html`（深色主题，支持卡片、表格、徽章）
2. 写入临时文件到 `/tmp/` 或 `~/.hermes/`
3. 调用 `cos_upload.sh` 上传
4. 输出 URL 直接发给用户

## 前置条件

- `cos-python-sdk-v5` 已安装（在 Hermes uv venv 中）
- 脚本路径：`~/.hermes/scripts/cos_upload.py` + `cos_upload.sh`

## 注意事项

- 文件路径必须在允许的目录下（`~/.hermes`, `~/.claude`, `~`, `/tmp`）
- 自动生成的 key 包含时间戳和文件 hash，不会冲突
- 默认 Cache-Control: `public, max-age=3600`（1小时缓存）
- `--no-cache` 设置 `no-cache, no-store, must-revalidate`
- MIME 类型根据文件扩展名自动识别
