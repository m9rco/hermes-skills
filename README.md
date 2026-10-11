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

## 安装方式

```bash
hermes skills install m9rco/hermes-skills/skills/<skill-name>
```

## 注意事项

- `cos-report-publisher` 需要环境变量：`COS_SECRET_ID`、`COS_SECRET_KEY`（值不随技能分发）
- 微信系列技能需要各自的 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 环境变量

## 目录结构

```
skills/
  <skill-name>/
    SKILL.md        # 技能主文档（YAML frontmatter + markdown）
    references/     # 参考文档（可选）
    scripts/        # 辅助脚本（可选）
    templates/      # 模板（可选）
```
