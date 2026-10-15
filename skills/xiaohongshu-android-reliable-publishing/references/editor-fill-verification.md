# 编辑器填字与完整核验（XHS 发布编辑器）

## 中文多行输入 — app_process launcher（避开 uiautomator wrapper 丢参）

### 问题
Android 的 `uiautomator` 包装脚本会把所有参数拼成一个字符串再 `exec app_process … Launcher ${args}`，二次展开时**丢失 caption 的空格/换行边界**，多行正文 + 话题触发 `Unsupported standalone parameter` / RC 157。这是 runner 参数解析失败（在 Java 测试方法之前），不是 UI/反射/审批错误。

### 正确做法（验证有效）
1. 从本篇 actual `rendered_post.json` 由 prepare 脚本生成参数 JSON（含 `adb_argv`/`remote_command`/`parameters`/双 SHA pins）。
2. 显式 `--launcher app-process`（缺省仍是 legacy uiautomator）。新 remote argv 单条命令：
   `env CLASSPATH=/system/framework/android.test.runner.jar:/system/framework/uiautomator.jar:REMOTE_JAR ANDROID_DATA=/data/local/tmp app_process /system/bin com.android.commands.uiautomator.Launcher runtest -c …#testFillTitleAndBody -e jars REMOTE_JAR [-e post_id/title/body/title_sha256/body_sha256]`
3. **消费原 `adb_argv` 列表**：`subprocess.run(adb_argv, shell=False)`（argv 精确 5 元素：ADB、`-s`、serial、`shell`、单条 remote_command）。绝不 `.split()`、不手抄正文、不拼 shell、不 eval、不二次拆散重拼。可执行路径 `adb`→绝对路径属合法替换，其余原样。
4. 不下载 SDK / 不反编译 / 不反复编译 / 不装 IME / 不改权限。用既有编译好的 helper jar 与既有 JDK；每篇绑定本篇实际文字/图片，不复用上篇正文。

### 参数传递坑
- shell 命令替换 `$(cat file)` 会**吃掉末尾换行** → 与预期 SHA 差 1 字符。用 Python `subprocess.run([..., prompt], shell=False)` 直接传字符串保末换行。
- prepare 校验：post_id 必须匹配本篇；title/body SHA pins 与 actual rendered 一致；两字段在空编辑器同时存在。

## 输入准备阶段、字段定位与光标

- 只有当前实际安装并完成相应验收的 prepare 版本支持时，才显式使用 `--input-phase body-before-native-topics`；默认 `full-caption` 保持旧行为。旧版不支持该参数时不能猜测已生效，也不在发布 worker 内开发/替换工具。
- 前缀模式必须先由 `caption_parts` 逐字重建完整 caption：body、question、旧稿非空 disclosure、精确空格连接的末尾 hashtags；空 disclosure 不额外插段。完整 caption 不匹配或标签列表为空就拒绝。只移除精确标签尾串，保留正文、问题、旧稿披露与尾部双换行，不 strip、不改冻结来源。客户端原生选择可能附加终止空格；保留关联，不靠 trim/全文重写强凑旧 hash，须先由正式来源版本显式记录并精确验收。
- 实际 `body_sha256` 是本次前缀输入 hash；`source_final_caption_sha256` 是完整来源 caption hash。标记 `final_caption_ready=false`、`native_topic_binding_verified=false`。前缀读回成功只证明准备阶段，原生选完后另核最终全文与固定版本。
- 填空 helper 的占位 **text** 不等于已有内容字段的 **hint**。标题/正文填入后，即使 hint 仍是“添加标题／添加正文”，旧 `.text(...)` selector 也可能失效；相同 resource-id 也不能区分两个字段。只用当前已验收工具的实际唯一 selector，不靠猜坐标/索引重跑，不为试错反复清空正文。
- “#话题”按钮可能只在正文光标处插入 `#`，没有独立搜索框。先读真实字段的 text/hint/focused；不要把标题当查询框。可在已确认正文位置用正常中文软键盘逐键拼音、选明确汉字候选，再选应用原生话题候选；输入法候选不等于应用话题候选。
- 多行 `MOVE_END` 可能只到行尾。尾部操作须核实际 `selectionStart/selectionEnd`，文档末尾为两端均等于全文 UTF-16 长度；`ACTION_SET_SELECTION` 返回 true 也不能代替读回。位置不明就停止删字，保留原件。
- 写正文与设光标是独立结果：helper 可能已写成功，却在后续 `SET_SELECTION` 返回 false 后整体报 failed。保留真实 marker/stage/mutation-attempted，不当成零修改、不盲重跑。先 fresh 只读核标题身份、全文/hash、实际 selection；正文已是正确前缀且文档末尾实际通过时可继续原生 UI。仍未知就停止，不用再整段输入代替对账；一次局部返回不能推成设备普遍结论。

## 完整回读（helper 成功 ≠ 设备通过）

- **若使用当前已验证 helper**：按其真实结果字段及 runtime pins 核验（如既有 `SHENQI_INPUT_RESULT`：`status=filled_and_verified`、post_id 匹配、`title/body_readback_matches=true`、双 `readback_sha256` 与 prepare pins 一致）。该 marker 是**该 helper 既有协议**，不是所有正常输入方式的强制字段/通用内容。**actual UI 完整字节比对始终是验收本体**。
- RC 0 / JUnit OK / TEST OK / `performAction=true` / 仅有截图 均**不能**代替全字读回。
- 填后关 IME（KEYCODE_BACK）再 dump：标题长度/正文长度 + UTF-8 SHA256 与当前输入阶段预期逐字比对；提交前仍须最终完整 caption 与正式原稿逐字一致（XML `&#10;` 需还原为换行再 hash）。原稿与当前 UI 不一致就不能提交。
- helper 每次填后 refresh 节点、`getText` 与原文 `equals`；任何失败可能留下部分文字 → 保留真实证据人工核验，不自行重试/发布。

## AI 声明（平台「笔记内容声明」）

- 软键盘展开时会**盖住声明行**（XML 后台 bounds 仍存在但不可点）→ 先 KEYCODE_BACK 收 IME 再核真实可见 bounds。
- 声明行是整行可点容器（TextView 本身 clickable=false），点整行中心展开面板。
- 面板无「确定」按钮；选项行：内容为自行拍摄 / 转载 / 含虚构演绎 / **含 AI 合成内容** / 营销 / 个人观点 / 无需声明。
- **选中状态由行内图标表达（黑圆白勾），XML 无 `checked` 属性** → 截 PNG 由人眼核验，不猜 checked。已选不再点（再点会取消）。
- 正文里的文字披露**不能替代**本篇需要的平台 AI 声明；是否需要正文披露按当前项目正式稿与已验证来源模式分支，不对所有账号一律要求“两者都要”。

### 正文与来源模式

- legacy/inline_caption 模式：完整保留正式 caption 的既有披露；不擅自删字或加字。
- 当前项目如采用 `platform_label` 合同，必须先由现装受控校验器确认 manifest 与 rendered 的 `origin_disclosure` 字典精确相等、严格布尔 `platform_ai_label_required=true`、原始虚构角色/AI 来源字段及 manifest.character.entity_type 均符合该合同。不得只看到 mode 字样就认为通过。
- 对已通过该合同的新包：caption 逐字保持正式稿，不补 AI/虚拟介绍或尾注；来源披露以真实元数据及当前客户端平台 AI 声明实际勾选为准。元数据不是 UI 勾选证据，必须展开面板实核。
- 新模式缺必要元数据、校验失败或平台勾选无法确认时，保持草稿并按原受控流程报 blocked；不向正文塞词/隐藏文字/零宽字符规避旧校验，不自动降级，不改已发布内容。
- 该模式是某项目可采用的合同，不把它或某种正文风格强制套给其他账号；各项目按真实来源、正式稿与所需平台声明验收。
- 旧草稿/历史输入成功 pins 只作审计，不能证明新版本稿件正确。总是从当前 queue 的本篇 payload_dir/rendered_post 生成动态参数并重核图片、全文、声明及所需原生话题；复用既有已验工具，不在发布临界阶段重编译。

## 原生话题与关联验收

- 项目当前是否已修复看实际回执与对应证据；本技能定义验收，不永久硬编码某次话题 bug 状态。单篇/单版客户端通过也不能外推所有账号和工具版本。
- 缺原生关联证据为 `unverified`；只有用户或页面正面证据才能记 `plain_text_only`，不能从“没读到”反推纯文本或未关联。正文 `#`、helper 成功、文字 hash、着色都不能独立证明绑定。
- 用户指定 Telegram 来源中实际看到且与本篇相关的短常用话题文字可直接借用，不必造长标签；留本轮可读来源/消息链接。它只是候选文字来源，仍须选小红书原生条目。冻结话题变更先形成新版本；短标签借用不自动授权照片或长文复用。
- **提交前**：先完成所用模式的纯文本输入（全文或已验收前缀），通过实际原生候选选择所需条目并返回同一编辑器；随后保存、退出并重开同一草稿，核该版本可靠的原生关联保留信号、最终全文、图片和本篇所需平台声明。缺证据就保持草稿，不进入提交。
- 重开后的可靠信号可为实际已选话题列表、话题管理面板或其他明确关联状态；不强制取得 topic ID。仅文字/颜色仍在且没有其他可靠关联信号时为 `unverified`；未暴露的 ID 记 null。正常 Accessibility 没读到 span/ID 既不能证明不存在关联，也不否定其他原生 UI 已确认的保留状态。只读 public CharSequence span 类/range/标准 URLSpan URL 仅作自然可见观察，不访问 app 私有数据。
- **提交后**：只有正常发布已获授权且门禁全部满足，才可单次提交；之后只读核实际笔记的话题入口是否进入对应关联页。公开关联验收需真实证据；未核实走 `unverified`/verify_only，不重复发布、不为测试而发。
- 原生话题已选后不得再整段 `ACTION_SET_TEXT`，否则此前关联验收作废。正常软键盘查询与原生候选选择产生最终话题；前缀 hash 不能替代最终完整 caption，也不能为强凑文本 hash 重写正文抹掉 span。
- 旧帖原位修改仅在本次确有授权且真实编辑入口/原 note_id 已核对时进行；不改成新帖或重发。保存结果未知先只读对账，不重复保存。草稿关联、旧帖修改、公开关联分别报告，不以其中一项代替其他项。

## 编辑器 UI 事实（随版本重核，不当作稳定 API）

- 用**正常系统分享/应用 UI** 打开带图编辑器；必要用既有 MediaStore/FileProvider 的 `content://` URI + 临时 read grant，**不推荐 file:// URI、不猜/不硬编码私有 activity 为通用入口**；不为此安装助手/改权限。
- 已观察过的私有 activity 类名仅供当时版本核对，**随版本重核**，不写为稳定 API。
- 单图编辑器 = 1 照片缩略 + 1 白色添加位，勿把添加位当第二张图。
- 存草稿前，以 fresh 截图/可访问性定位当前真实可见的 label、selector 与 bounds；按钮和确认框随版本核对，不能沿用旧坐标。点击之后仍在编辑器，不等于已经保存。
- 按正常保存/退出流程，实际进入草稿箱，确认本篇 title 与图片对应的新稿存在，再重开核完整标题/正文、图片、本篇所需声明及原生话题关联。保存前后每步读当前 UI；未确认保存前不连按 Back 退出，也不把一次点击或旧卡片当新稿保存证据。
- 实际确认未存稿已丢时，如实记录 `lost_unsaved`，沿本次既有授权重建并重新验收；仅暂未找到或采集失败则保留 unknown。曾经选中过原生话题不等于重建后仍保留，旧选择证据不能沿用。
## 共享节点会话与 UI 续接

- 共享 Feishu 节点会话遇另一合法任务消息显示 `Redirected` 时，上下文可能已经真实切换。每次续 UI 前先核本 task/context 和当前界面；不能把旧会话仍在、旧截图或上一条回报当作本任务控制权仍成立。
- 在可说明的安全检查点收口；若未存就如实保留未存状态，不声称草稿或关联已保留。等待另一任务的实际终态边界或正式交接，不为恢复本任务取消/改动对方任务；对方 stdout、截图或完成回报不能充作本任务成功证据。
- 接续本任务时 fresh 核锁屏、当前账号、唯一 UI 操作者、实际任务归属和本次 guard 状态。旧 unlocked/身份/排他记录不能替代；已解锁且身份正确可沿既有正常入口继续，不因续接而重复认证。
- 正常认证成功后的有限显示窗口优先完成当前必要 UI。文档、审计和附件交付放在自然的非 UI 边界，不为附送材料占用窗口。不得用无业务点击人工保活、延长或换路径续旧 guard；结束立即恢复并读回原值。窗口结束后还有工作，按下一阶段的新鲜正常入口与实际会话办理，不把旧 guard 续成永久会话。


## 中文预编辑与异步节点指令

拼音仍在输入法预编辑栏时，正文可能仍只有已核前缀加单个 `#`，小红书推荐也可能未变；这不证明按键未生效。先看本次真实输入法 composition 与明确汉字候选，提交一次准确词语，再等平台原生候选更新并选择。不要因为正文 hash 暂未变化而重输拼音，造成双重 composition。出现重复预编辑时，依据实时画面正常取消或有界清理，只接受已知查询态或完整原前缀的逐字/hash读回；确认原前缀立即停删，不用旧坐标、行尾或盲退格。预编辑状态与正文文本是两个核验对象，文本 hash 不能替代输入法画面。

节点消息会排队，动作前先核本任务最新有效回执、执行阶段及实时界面；已经完成选择/保存/公开验收后，迟到的输入或清理指令必须标记 superseded，禁止再执行。按已获授权的完整流程由当前唯一操作者用自己的实时截图与工具读回连续完成，原件可在自然边界集中回传审计；不要为逐按键重新索要主控许可，或因附件少了说明而停住已知安全的操作。实际字段、身份、控件或提交结果有疑义时才停止核对；未知提交始终只读验证，不重放保存/发布。
