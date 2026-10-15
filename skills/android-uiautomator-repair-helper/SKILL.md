---
name: android-uiautomator-repair-helper
description: Use for offline uiautomator helper text repair on Android.
---

# Android uiautomator 精确修复 helper（离线编译 + 受控执行）

场景：非空编辑器需精确修复正文/标题、只读检查 UI 状态、或需要 IME 中文输入（原生话题搜索等）。主控交付 JVM 候选 jar → **离线 D8 编译** → push → `app_process Launcher runtest` 单次受控执行，全程 shell=False。

## 核心原则

1. **marker ≠ 实际状态**：helper 报 `failed`（如 `BODY_SET_SELECTION_FALSE`）时正文可能已正确写入——SET_TEXT 落地、仅 selection 动作返回 false。判定以**实际回读**为准：XML 逐字 + 只读 inspect 方法（`body_sha256`/`selection_start/end`/`spans`）。
2. **负例先行**：correct 前先跑 negative probe（错 before pin），必须 `BODY_BEFORE_PIN_MISMATCH` + 全部 `*_attempted=false` + body 不变，才允许 correct 一次。
3. **完整流落盘**：每次执行把完整 stdout/stderr/RC 原样存 0600 JSON（不 print 截断/不内存捕获）；未落盘即 `not_preserved`，不重跑、不手写替代 marker。
4. **失败即停**：marker failed / body 可能已变 → 不自动 rollback/retry/补字，回原 marker + 实际 XML 原件等主控。
5. **marker 名按实际源码**：新 helper 的 marker 可能不同于旧 helper（如 `SHENQI_NOTE_REPAIR_RESULT` ≠ `SHENQI_INPUT_RESULT`）；preflight 失败是 `AssertionError: NOTE_REPAIR_NOT_VERIFIED:<stage>`，marker 不打印。

## 关键经验（细节见 references）

- **fill helper 只定位空字段**：按 `UiSelector.text(添加标题/添加正文)` 定位（不用 hint），已填编辑器重跑必定位失败；禁止用它恢复/准备，不重编译修改。
- **中文输入三禁**：`adb input text` 中文 NPE、`KEYCODE_V` 不是粘贴（IME 下会输入字符 'v' 污染正文）、`cmd clipboard set-text` 不可靠。真实方法 = 主控从 PNG 目视给 26 键坐标逐键 tap + 点 IME 汉字候选。软键盘不进 uiautomator dump（IME 独立窗口）。
- **IME composition 误判陷阱**：正文未变 / XHS 推荐列表未变 **≠ 输入失败**——拼音 composition 在 IME 层未提交，XHS 推荐要选汉字后才变。看到首蓝候选即说明 7 键成功；**不要**以"正文仍旧长度/列表未变"判失败再输第二轮（会变 chuan'da'chuan'da 重复、首候选变「穿搭穿搭」）。每轮后截真实 PNG 核 composition；uiautomator dump 不暴露 IME 窗口。
- **保存控件（小红书）**：顶部右上灰圆「存草稿」~(780,192) 与底部大按钮「存草稿/发布笔记」[42,2182] 都是真实控件；点空白不保存；存草稿会弹「确认保存笔记至草稿箱吗?」需点「确定」。保存后回个人页→草稿箱核新稿在场（计数 +1）再退出重开。
- **同 note 编辑**：从已发布 note 菜单「编辑」进入 CapaPostNotePlatformActivity = 更新原 note（非新投稿）；底部「发布笔记」= 更新原篇（toast「发布成功！」+ 公开页显示「编辑于 刚刚」+ 同 note_id）。原 note 的 topic 修复需先只读 before（title/caption 双 SHA 匹配正式记录）才动。
- **原生话题插入格式**：平台选中后自动插 `#话题` + **1 个 ASCII 尾空格**（如 `#穿搭 `）；正确结果以 body 全文 SHA 精确匹配预期为准，不 trim、不整段 setText。
- **公开页 tag 点击验收**：修复后打开原 share URL → 滚动使 tag 可见 → 精确点击（tag 在正文单节点内，需 PNG 目视坐标）→ 进入 XhsReactActivity 话题聚合页 → Back 返回同 note = `public_clickability_verified`。
- **out-of-band 指示可能基于旧状态**：消息排队时 PNG/证据可能过期；执行前先核当前实际 UI（body 全文/hash/focus），不执行针对已消失状态的步骤（如清已提交的 composition）。
- **MOVE_END 批量 DEL 危险**：MOVE_END 不保证全文末尾，31×DEL 会删**中间**段（173→142 中段丢失）。长多行正文禁盲批量退格；先只读 inspect 核 selection。
- **caret 定位**：点真实字形 bounds（主控从 PNG 给坐标），不是上方空行；点后只读 inspect 核 `selection==length`。
- **带图打开编辑器**：系统分享路线（MediaStore content:// + SEND intent），不用 file://、不猜私有 activity。

## References

- `references/d8-build-and-run.md` — 离线 D8 编译 argv、dexdump 类核验（exact 4 项、定义 vs 引用）、app_process 启动器、marker/负例协议、话题修复流程编排。
