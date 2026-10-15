# 官方运行上下文、单次提交与公开核验

## 真正运行上下文（归属纪律）

- 每个 cron run 是**独立 execution UUID + 独立 session id**。用 actual executions.db 行（id/job_id/source/status/claimed_at）与 `hermes sessions list --source cron` 返回的真实 session_id 做归属。
- 节点名、固定 jobID、gateway PID、deleg 启动器、Feishu 部署会话**都不能**冒充真实 worker handle。
- claim 绑定：`attach --claim-id CLAIM --kind job_run --handle-id ACTUAL_EXECUTION_UUID`；v2 会只读核 executions.db 同 UUID/原 job/实际状态/时间。
- 全局活动核查：查 executions 表 `status IN ('running','unknown')`；active 核查按**实际共享 UI 资源冲突**判断——无 UI heartbeat 的作业不构成 UI 冲突，不泛化阻塞。

## checkpoint / intent / 单次提交

- fresh capture → 事实 JSON（checked_at 真实时刻、同账号、unlocked、normal_entrypoint）→ refresh-checkpoint：**同一短脚本顺序完成**，避免模型回合往返超过 freshness 阈值过期。freshness 阈值**按当前项目真实 gate 配置**（`≤120s` 只是本项目示例值，非全球固定）；不得改时间复用旧图。
- 完整 preview（标题/正文逐字、正确图、AI 声明选中）后才 intent；intent 要求当前 claim 的 UI 证据在 freshness 阈值内。
- intent 成功后才允许**一次**正常发布点击；点击后不确定/中断/错误 → 只提交 publish_unknown/真实错误证据，**永不盲点第二次**。
- 未知结果 → `verify_only`：只核查主页/创作中心既有结果，不新建/不点击发布/不自动重发。

## 公开核验与时间锚点

- published 必须：实际 note_id、真实分享 URL、真实 published_at、原始公开证据（详情页「公开可见」徽标、主页卡片「xx分钟前」）。
- 平台无秒级 server 时间时：锚点用**第一次实际公开可见的观察时刻**，receipt 标 `source=first_public_visibility_observed`、`server_published_at=null` 并说明精度；不猜服务器秒数。
- 已有公开卡/详情页/分享链接**优先核既有结果**；cached 首页计数（如公开 2/草稿 0）**不能证明未发布**，不能据此重发。
- 短链分享 URL（如 xhslink.cn）解析出 note_id 属真实核验路径；canonical explore URL 用于验证字段；`commit-result` 需引用真实证据文件。

## commit / release

- 按真实结果 commit 并释放全局 claim；不把日期改 done、不把素材送达当首发完成。
- 尝试上限/退避/账号频率/每日时段一律**遵守当前任务实际 ledger 的规定**，不硬套本项目数值到其他任务；不能自行 reset 规避；真实 blocked 保存证据并提交 blocked。
- 同一账号发文频率与每日时段按当前任务实际 ledger 执行，不硬套本项目时段到其他任务。

## 观察与收口

- active/unknown worker 存在时协调侧只读、不并发 UI、不重复 run、不 trigger。
- 官方无单 worker interrupt 接口时（sessions/cron 均无 interrupt/stop/cancel）：不冒用 run_<uuid>、不杀 gateway/其他任务/手机进程、不以 pause schedule 冒充停止当前 run。
- 每轮回实际采样时间 + 真实 handle/状态；terminal 后先回最小 receipt 再补小件。
