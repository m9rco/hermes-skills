# 故障收口与安全交付

## 门禁/审批

- 自动审批拒绝某具体动作 → 不 Allow / 不拆分 / 不编码变形重试 / 不改全局审批策略；保留原命令/原因/归属 UUID。
- 可移除被拒能力的独立正常最小动作（如改用普通文件 read 读 XML）继续；仍记录拒绝与真实剩余阻塞。
- 无官方同 worker 送达/中断入口时不声称已送达/已阻止/已 steer；审批来源保持 unknown。

## vision 超时

- `vision_analyze` 超时/429 是常态，**不循环耗回合**；直接上传已捕获 PNG（MEDIA: + 精确 bytes/SHA/capture 时刻 + 一条 message_id/image_key 关联）由人眼核验；XML 文本读取是可靠程序化路径。

## 只读设备文件

- `adb shell cat /system/bin/uiautomator` 是合法诊断；但**不要在同一命令重定向到 home/task 目录**（触发 "Security scan [HIGH] Dotfile overwrite detected" 审批卡）。
- 通过形式：纯读单调用、无变量/无重定向/无链式命令；stdout 之后再 write_file 落盘。被拒则原样报 reason 并停。

## blocked 收口

- 短检查点 + 实际 handle/工具原件优先于「正在做」承诺；每轮回实际采样时间。
- 不把 JUnit/exit0/RC0/「已连接」文字/进程存在当成功；不把审核中/未知当 published。
- 不用网关 kill/restart 冒充单 worker 恢复；官方无单 worker 中断时只读观察等真实 terminal。

## allowlist 交付

- 固定 allowlist 小 ZIP：只含安全原件（safe JSON、guard state、事实 JSON、PNG/XML、readback）；MANIFEST 列 bytes/SHA；未单独落盘的项如实 `pending`，不手写补造「原 stdout」。
- 绝不含 private/cipher/secret/序列/**认证图案轨迹/认证坐标**/auth callback 函数体/整个临时目录；**普通 app 界面 bounds/按钮定位可作为证据**，不把所有 UI 坐标普遍禁掉；消息正文不输出凭据（出现即 [REDACTED]）。
- 收件器只读 pinned attachment；文件名纯 ASCII、task-base 绝对已存在、拒绝覆盖/软链；HTTPS 重定向全拒、SHA+bytes+0600 核验后才发布文件。
