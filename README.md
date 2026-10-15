# Hermes Agent Skills by m9rco

个人 Hermes Agent skills 合集。可通过 `hermes skills install <identifier>` 或 ClawHub 兼容方式安装。

## Skills

| Skill | 说明 | 安装标识 |
|---|---|---|
| cos-report-publisher | 上传 HTML 报告到腾讯云 COS 并返回公开 URL | `m9rco/hermes-skills/skills/cos-report-publisher` |
| wechat-formatter | 将 Markdown 渲染为微信风格 HTML | `m9rco/hermes-skills/skills/wechat-formatter` |
| wechat-mp-publisher | 微信公众号远程发布（合规优化版） | `m9rco/hermes-skills/skills/wechat-mp-publisher` |
| wechat-official-account-writer | 微信公众号写作发布助手 | `m9rco/hermes-skills/skills/wechat-official-account-writer` |
| macos-calendar | macOS 日历操作（osascript 直连 Calendar.app） | `m9rco/hermes-skills/skills/macos-calendar` |
| codex-desktop-login | Codex 桌面版 Google OAuth 登录（CDP 驱动） | `m9rco/hermes-skills/skills/codex-desktop-login` |
| tokenhub-hy-image | 腾讯 TokenHub Hy-Image 文生图/图生图（正确端点+脚本） | `m9rco/hermes-skills/skills/tokenhub-hy-image` |
| android-device-automation | macOS↔安卓 adb 控制（小米/HyperOS 已验证，含排查矩阵） | `m9rco/hermes-skills/skills/android-device-automation` |
| android-uiautomator-repair-helper | uiautomator 离线辅助文本修复 | `m9rco/hermes-skills/skills/android-uiautomator-repair-helper` |
| xiaohongshu-android-reliable-publishing | 小红书笔记安卓端可靠发布/核验（ADB） | `m9rco/hermes-skills/skills/xiaohongshu-android-reliable-publishing` |
| mem0 | Mem0 Platform 持久记忆（add/search/list/delete CLI） | `m9rco/hermes-skills/skills/mem0` |
| duckduckgo-search | 免费无 key 的 web/news/image 搜索（ddgs） | `m9rco/hermes-skills/skills/duckduckgo-search` |
| secure-credential-handoff | 一次性加密凭据交接协议（RSA-OAEP，仅内存） | `m9rco/hermes-skills/skills/secure-credential-handoff` |
| kanban-orchestrator | Kanban 编排器分解 playbook + 反诱惑规则 | `m9rco/hermes-skills/skills/kanban-orchestrator` |
| kanban-worker | Hermes Kanban worker 的坑/示例/边界情况 | `m9rco/hermes-skills/skills/kanban-worker` |
| a2a-relay-polling | NAT 后 A2A relay hub 轮询接入（无需入站端口） | `m9rco/hermes-skills/skills/a2a-relay-polling` |

| cos-html-reports | 生成并上传 HTML 报告到腾讯云 COS，支持临时上传票据 | `m9rco/hermes-skills/skills/cos-html-reports` |
| new-api-gateway-deploy | 部署 New-API 网关、nginx 与 HTTPS | `m9rco/hermes-skills/skills/new-api-gateway-deploy` |
| tencent-tokenhub-tts | TokenHub 语音合成与原创音色设计 | `m9rco/hermes-skills/skills/tencent-tokenhub-tts` |
| xiaohongshu-android-publish | 安卓小红书图文准备、核验与发布 | `m9rco/hermes-skills/skills/xiaohongshu-android-publish` |

## 安装方式

```bash
hermes skills install m9rco/hermes-skills/skills/<skill-name>
```

## 注意事项

- `cos-report-publisher` 需要环境变量：`COS_SECRET_ID`、`COS_SECRET_KEY`（值不随技能分发）
- 微信系列技能需要各自的 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 环境变量
- `mem0` 需要 `MEM0_API_KEY` 环境变量

## 目录结构

```
skills/
  <skill-name>/
    SKILL.md        # 技能主文档（YAML frontmatter + markdown）
    references/     # 参考文档（可选）
    scripts/        # 辅助脚本（可选）
    templates/      # 模板（可选）
```

## Codex 与 Hermes 共享

上述 4 个自定义技能同步自 Codex；安装后按各技能目录解析脚本与参考文件。
本机可使用 `hermes config set skills.external_dirs '["/absolute/path/to/.codex/skills"]'` 直接共享 Codex 技能目录，后续修改无需重复复制。Codex 内置技能及插件依赖专用工具，未打包到本仓库。
