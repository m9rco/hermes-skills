# UiAutomator helper JAR: offline D8 build + DEX class verification (verified)

Build a uiautomator `runtest` helper JAR without downloading anything, then
verify the DEX contains exactly the intended classes. Used to ship a repair
helper (pin-verified body repair) next to an existing fill helper.

## D8 offline argv (exact, verified working)

```python
argv = [
  "/usr/bin/java", "-cp", "/tmp/bt34/android-14/lib/d8.jar",
  "com.android.tools.r8.D8", "--release", "--min-api", "21",
  "--lib", "/tmp/android-4.1.1.4.jar",
  "--classpath", "<dir>/framework-signature-stubs.jar",
  "--output", "<NEW_EMPTY_DEX_DIR>", "<dir>/candidate-jvm.jar",
]
subprocess.run(argv, shell=False)
```

- **cached tools on this machine**: `java`/`javac` = OpenJDK 17 at
  `/usr/bin`; D8 = `/tmp/bt34/android-14/lib/d8.jar`; android.jar =
  `/tmp/android-4.1.1.4.jar`; dexdump = `/tmp/bt34/android-14/dexdump`.
- **framework-signature-stubs.jar is `--classpath` ONLY** — never a program
  input. The ONLY program input is the candidate JVM jar (compiled with the
  stubs on javac classpath so `android.*` symbols resolve at build time).
- Output goes into a NEW empty dex dir; RC=0. A desugaring *warning* (e.g.
  "Type java.lang.Exception was not found...") is NOT an error — still success.

## Verify DEX class DEFINITIONS (not references)

`strings`/regex over classes.dex finds **references** too (parent class
`com/android/uiautomator/testrunner/UiAutomatorTestCase`, `android/os/Bundle`
appear as constants from base-class/stub usage) — references are FINE. Only
class **definitions** matter. Use dexdump:

```python
out = subprocess.run(["/tmp/bt34/android-14/dexdump", "classes.dex"],
                     capture_output=True, text=True).stdout
import re
defs = re.findall(r"Class descriptor\s*:\s*'([^']+)'", out)
```

Expect an EXACT set (e.g. `Lcom/shenqi/input/XhsNoteRepair;`,
`…$Field;`, `…$Reject;`, `Landroid/test/RepetitiveTest;`) and zero forbidden
definitions (`android/os/Bundle`, any `com/android/uiautomator` class).

## Pack + push

- Pack ONLY `classes.dex` into a NEW jar (zipfile, `classes.dex` entry); never
  overwrite the source JVM jar. New jar ≈ 7 KB for one small helper.
- `adb push <new>.jar /data/local/tmp/<unique-name>.jar`, then `adb shell ls
  -la` the remote path to confirm size landed.

## Repair-helper contract (validated recovery pattern)

When a filled editor is corrupted (see SKILL.md Pitfalls — MOVE_END/DEL mid-body
delete), the fix is a purpose-built helper, NOT manual text patching:

1. Locate title/body by unique **hint** (`添加标题`/`添加正文`) + editable /
   visible / enabled / non-password — NOT `UiSelector.text(...)` which only
   matches EMPTY fields (a filled editor re-run fails
   `FILL_NOT_VERIFIED:locate_fields`).
2. Check expected_title_sha256 + expected_before_sha256 (fresh XML body) BEFORE
   any focus and again before the single SET_TEXT. Mismatch → marker
   `BODY_BEFORE_PIN_MISMATCH`, all mutation flags false, body untouched.
3. One SET_TEXT of the prepared body, then SET_SELECTION(length, length),
   full actual text + selection readback. Success is a *preparation* state,
   NOT final caption acceptance.
4. No automatic retry/rollback after a text action attempt — body may have
   changed; stop and return the marker + actual XML.

## Native topic-entry reality (XHS editor)

No separate search-panel EditText exists — the editor has only title/body
EditTexts and `#话题` is a toolbar button that renders recommended topics
inside the body EditText area. Chinese topic search = soft-IME pinyin key taps
(e.g. chuanda → 穿搭) + IME candidate tap + watch for XHS's own candidate
list. No search helper to build; adb input text / clipboard / KEYCODE_V are
all dead ends that corrupt fields.
