# 辅助工具与适用边界

`scripts/` 是先前实际验证实现的无凭据副本；没有当前账号、素材、任务状态、解锁 callback 或设备配置。优先使用当前环境已安装的同版本工具。只在需要对应能力时加载或执行，不能为了读技能启动 UI。

## 纯文本输入

- `android/prepare_note_input.py`：读取现有 `rendered_post.json` 或带 manifest 的素材 ZIP；仅生成完整 `adb_argv`，不执行 ADB。旧包装器兼容时明确 `--launcher app-process`，默认仍为 `uiautomator`。
  - 原生话题准备模式只有在当前安装版本实际支持并已完成对应验收时使用：显式 `--input-phase body-before-native-topics`；默认 `full-caption` 保持原行为。旧版本不接受该参数时，不猜测其已生效。
  - 该模式先验证 `caption_parts` 与完整 caption 逐字一致，再只移除精确标签尾部及明确记录的单个 ASCII 终止空格，保留正文、问题、旧稿非空 disclosure 与尾部双换行；不得改写冻结来源。实际输入的 `body_sha256` 指前缀，`source_final_caption_sha256` 指完整来源 caption，且必须标记 `final_caption_ready=false`、`native_topic_binding_verified=false`。它用于空编辑器首次填入，不是原位草稿修复；原生选择后仍需最终全文和保存重开的关联验收。
- `android/com/shenqi/input/XhsNoteInput.java`：原版 fill-only Java helper。`com.shenqi` / `SHENQI_INPUT_RESULT` 是兼容类/结果名，不要求账号采用该人设。选择器仅覆盖当时验证的小红书普通图文编辑字段；界面不匹配时失败，勿宽化到未知字段。
- `android/build_note_input.py`：用当前已有 JDK、android.jar、D8 编译，不自动下载、不安装/推送设备。使用前以 `--android-jar`、`--d8-jar`、`--javac`、`--java` 明确传入实际工具路径，不能依赖历史 /tmp 默认值。编译期兼容 stub 必须被排除于运行 DEX；JAR 只有 classes.dex。脚本保留历史 build-record 标签，这些字符串不代表本次草稿或设备验收。

`prepare_note_input.py --help` 和 `build_note_input.py --help` 可安全查看参数。远端 JAR 要核 hash，只有编译成功不算真机验收。准备阶段构建/验证，正式发布 worker 使用已验收版本；不要边发布边改 SDK/JAR。

## 正常认证与有限显示设置

- `normal_auth_envelope.py`：解密经任务/nonce/key SHA 绑定的原始人类字符串，需要已安装 `cryptography`。
- `normal_auth_transaction.py`：`transact(envelope_path, private_path, *, expected_key_sha256, expected_nonce, expected_task, normal_input_callback, verify_callback, restore_callback)`。
- `normal_auth_screen_session.py`：`transact_with_screen_guard(adb_path, serial, guard_state_path, duration_seconds=1800, **transact_kwargs)`；已解锁可 `start_screen_guard(...)`；结束调用 `restore_now(guard_state_path)`。

真实认证只通过进程内 API 与既有已授权 callback。CLI 仅有 dummy tests 与无凭据 watchdog/restore：

```text
python scripts/normal_auth_envelope.py --self-test
python scripts/normal_auth_transaction.py --self-test
python scripts/normal_auth_screen_session.py --self-test
python scripts/normal_auth_screen_session.py --restore-now <current-guard-state.json>
python -m unittest discover -s scripts/android/tests -p 'test_*.py'
```

前三项及最后一项使用明确的 synthetic/dummy fixture，不连接真实设备；恢复命令会操作指定 guard 的实际设备，仅在当前会话有恢复需要时执行。guard self-test 的恢复原值也是 synthetic，不能写回真实手机。

代码原版副本与来源 hash 记录在 `references/helper-provenance.json`。本地 dummy 回归覆盖认证单次消费/清理、bounded guard、中文与 shell 双跳参数保真；本次输入准备版本的 13 项测试还核验精确话题尾串与显式终止空格、旧披露保留、来源不变。它们不验证当前 UI、原生话题、平台声明或公开发布。技能结构与行为推演也不等于上线修复成功。
