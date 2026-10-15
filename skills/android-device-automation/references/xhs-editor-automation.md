# XHS (Xiaohongshu) publish-editor automation via ADB

Validated 2026-10-15 on device e2d3f1c1 (Xiaomi/MIUI, XHS com.xingin.xhs)
for the superstar publish task. Reuse for any XHS note-editor fill/publish
verification on an ADB-connected device.

## Chinese text input into the editor (the working path)

On this device the plain routes fail: `input text` NPEs on Chinese,
`cmd clipboard` is unavailable, ADBKeyboard install is blocked by MIUI
(do NOT try to bypass). The verified working input is a uiautomator
`runtest` jar that performs accessibility ACTION_SET_TEXT:

1. Java source (single class extending
   `com.android.uiautomator.testrunner.UiAutomatorTestCase`):
   - `new UiSelector().text("添加标题")` / `("添加正文")` → `UiObject.exists()`
     → `click()` → `getQueryController().findAccessibilityNodeInfo(sel)`
   - `node.performAction(0x200000 /*ACTION_SET_TEXT*/,
     Bundle{ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE: text})`
   - `ACTION_SET_TEXT = 0x200000`; arg key
     `"ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE"`. Reflection avoids compile-time
     deps; the jar contains ONLY the one class.
2. Build: `javac -encoding UTF-8 -d injc8 <src>` then `D8 --lib <android.jar>
   --release --output dex8 ...` then zip `classes.dex` into the jar.
3. Run: `adb push xhsinput.jar /data/local/tmp/` then
   `adb shell uiautomator runtest /data/local/tmp/xhsinput.jar
   -c com.shenqi.input.XhsNoteInput`.
4. Success signal: `RESULT TITLE_OK=true BODY_OK=true` (jar set text) —
   but this alone is NOT publish proof.

**TITLE_OK/BODY_OK=true is not enough.** Always verify the EDITOR's own XML
dump afterwards: `text="衬衫不扣好也可以"` (8 chars, sha
9f9711ff…) and full 210-char caption node (sha 87a729df…) must equal the
canonical staging files (24B title / 573B caption). A jar that runs clean but
finds no field prints `FIELD_NOT_FOUND` — that is a FAILURE even with exit 0
(observed: ran after the device relocked, fields gone).

## Critical UI facts (learned the hard way)

- **Soft keyboard covers the bottom rows.** XML bounds behind the IME are
  real but NOT visible/clickable — a tap at those coords lands on keyboard
  keys (observed: a tap at y≈1965 hit the V key area while the 声明 row was
  under the keyboard). Before tapping bottom rows (笔记内容声明 / 存草稿 /
  发布), close the IME first with `adb shell input keyevent KEYCODE_BACK`,
  then re-dump to get the TRUE visible bounds.
- **「笔记内容声明」row**: the TextView label itself is clickable=false; the
  whole row is a clickable LinearLayout (e.g. [0,1926][1080,2005]). Tap the
  row center (mid-y of the row), not the label.
- **声明 panel has NO confirm button.** Options: 内容为自行拍摄 / 内容为
  转载 / 含虚构演绎内容 / 含 AI 合成内容 / 内容含营销信息 / 个人观点，仅供参考
  / 无需声明. Pick the needed one, then close with KEYCODE_BACK or tap
  outside — the choice persists without an explicit 确定.
- **Selection state is an ImageView icon, not an XML attribute.** The panel
  options do NOT expose `checked="true"` in the dump (all checked=false).
  The selected row shows a black-bg white-check icon on the right. XML can
  NOT verify selection — capture a PNG and have the controller/vision
  confirm visually. Tapping the chosen option again can DESELECT it — verify
  once, then stop tapping.
- **存草稿 flow**: tap 存草稿 → dialog「确认保存笔记至草稿箱吗?」→ tap 确定
  (NOT 取消). This keeps the verified draft for the next run.
- **Editor is fullscreen — no bottom nav.** After closing/saving you land on
  the search page (GlobalSearchActivity); BACK may stay there. To reach
  home/我的: `adb shell am start -n
  com.xingin.xhs/com.xingin.xhs.index.v2.IndexActivityV2`, then the bottom
  tab (我的 ≈ tap 972,2299 on 1080-wide device). 我的 page shows
  `content-desc="头像,是萌萌"` and `小红书号：42151948653` — the account
  identity evidence.
- Opening the editor with an image attached: XHS accepts
  `ACTION_SEND type=image/png` (content:// with read grant) — creates the
  publish editor with the image mounted (title/body fields present).

## uiautomator wrapper drops spaces/newlines → use app-process launcher (CRITICAL)

`adb shell uiautomator runtest ...` is NOT a direct runner: device
`/system/bin/uiautomator` is a shell script that rebuilds all args into ONE
string (`args="${args} ${1}"`) and unquoted-expands them into
`exec app_process ... Launcher ${args}`. Any caption containing spaces,
newlines, or `#` (XHS captions with 换行 + 话题 tags always do) gets its
argument boundaries destroyed → `Unsupported standalone parameter.` /
RC 157 / `ARG_FAIL_UNSUPPORTED` (observed 2026-10-15). This is a PARSE
error before the test method — not a UI/reflection/approval failure.

Verified fix — bypass the wrapper entirely, invoke the Launcher directly:

```
env CLASSPATH=/system/framework/android.test.runner.jar:/system/framework/uiautomator.jar:<REMOTE_JAR> \
    ANDROID_DATA=/data/local/tmp \
    app_process /system/bin com.android.commands.uiautomator.Launcher \
    runtest -c com.shenqi.input.XhsNoteInput#testFillTitleAndBody \
    -e jars <REMOTE_JAR> -e post_id <id> -e title <T> -e body <B> \
    -e title_sha256 <H> -e body_sha256 <H>
```

Transport discipline (from the prepare-argv pattern):
- Generate the argv programmatically (prepare_note_input.py with
  `--launcher app-process`); the output `adb_argv` is exactly 5 elements
  `[adb, -s, SERIAL, shell, ONE_remote_command_string]`. Consume it with
  `subprocess.run(argv, shell=False)` — NEVER `.split()`, re-quote, rebuild
  from caption text, or eval. Only the executable path may be absolutized.
- Full caption + both plaintext SHA256 pins must be passed; `validate_params`
  failure = the hash gate rejecting a truncated/retyped body — stop, don't
  hand-transcribe the caption again.
- Success is ONLY the helper's real
  `SHENQI_INPUT_RESULT {"status":"filled_and_verified", ...,
  title_readback_matches:true, body_readback_matches:true, ...}` with the
  exact readback SHAs. JUnit OK / exit 0 / Tests run OK are NOT success.

## Evidence discipline

Save each real UI state as evidence/<name>-<ts>.png + .xml (bytes+SHA) and
reference them in current_ui_entry_check JSON `evidence_paths`. Never reuse
an old PNG/XML as "fresh"; capture at the decision moment.
