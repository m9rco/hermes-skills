# Encrypted pattern-handoff unlock (verified 2026-10, Xiaomi / HyperOS)

When a remote coordinator must hand an unlock pattern without the pattern ever
touching chat logs, plaintext files, or the model's context.

**Protocol version note:** early handoffs used a structured payload
`{"kind":"android_pattern","numbering":"row_major_1_to_9","sequence":[...]}`.
Current controllers (2026-10-15+, "unified envelope") encrypt the **original
human message string** — the payload's `s` field is natural language
(e.g. `"我的手机密码…划线…5位数字"`), NOT a JSON object. Trust the envelope's
inner fields `{t, n, s}` literally: `t`=task id, `n`=nonce, `s`=raw human
text. **Never `json.loads(s)`; never `.get("s")`/`.get("sequence")` on the
decrypted string.** Sequence extraction happens by regex on the natural
language (see below).

## Coordinator side (sends only ciphertext)

1. Node generates RSA-2048: private key 0600 in a temp dir (0700); sends
   **public PEM + its SHA256 + private-key temp path** — never the private key.
   Also generate a one-time public `nonce` (hex) and send it — it is a
   public anti-replay handoff tag, NOT a secret, and the decoder only
   compares it; it is not a one-time consumption counter.
2. Coordinator encrypts compact JSON `{"t":task,"n":nonce,"s":human_msg}`
   with RSA-OAEP-SHA256 / MGF1-SHA256, label=None, sends a cipher JSON file.
   Envelope public fields are EXACTLY:
   ```json
   {"ciphertext_hex": "<512 hex chars for RSA-2048>",
    "algorithm": "RSA-OAEP-SHA256",   // NOT "RSA-OAEP"
    "mgf1": "SHA256",
    "label": null,
    "key_sha256": "<sha256 of the PUBLIC PEM file>",
    "nonce": "<the same public nonce>"}
   ```
   File is typically 742 B; `ciphertext_hex` = 256 B = 512 hex chars.

## Phone-host side — unified transaction contract

Use ONE Python process, ONE `decrypt_envelope` call (public decoder module),
then hand the recovered string to an input callback once. **No child
subprocess decrypt, no stdout/JSON adapters, no second decrypt call, no
"pre-decrypt probe".** Dummy self-tests may decrypt repeatedly; the real run
decrypts exactly once.

Callbacks (defined by the node, existing verified gesture code):
- `normal_input_callback(sequence: str)` — receives a STRING of digit
  positions (e.g. `"15973"`), converts chars to ints locally against the
  real fresh grid bounds. One `motionevent DOWN → MOVE… → UP` gesture.
- `verify_callback() -> bool` — fresh keyguard read (`showing=true` in
  `dumpsys window policy`), literal bool; never guess.
- `restore_callback()` — restore original `screen_off_timeout` (or delete if
  it was null); no-op if nothing changed; never claim restored when not.

Sequence extraction from natural-language `s`: text must contain 划线, must
NOT start with `{`/`[`/`"` (reject structured wrappers), and must contain
EXACTLY ONE digit run of length 4–9 with no `0` and no repeated digits.

Safe result JSON (what gets persisted/reported — never exception
messages/args/locals):
```json
{"stage": "verified|unverified|...", "error_class": null|"ClassName",
 "input_attempted": true, "keyguard_cleared": true|false,
 "cleanup": {"private_deleted": true, "cipher_deleted": true, "error_classes": []},
 "restored": true}
```
`stage=verified` + `input_attempted=true` + `keyguard_cleared=true` +
`restored/cleanup true` is required to claim auth success. Account identity
and app foreground require separate real UI evidence — auth alone is not
publication proof.

## Real observed failures (2026-10-15) — do not repeat

- **ALGO_MISMATCH**: script asserted `algorithm == "RSA-OAEP"` but the real
  envelope field is `"RSA-OAEP-SHA256"`. Read the envelope's own public
  fields instead of hardcoding your guess; the mismatch aborted before any
  input, and `finally` still deleted the private key → key unrecoverable,
  full re-handshake needed.
- **NO_SEQ_OUT**: caller did `json.loads(s)` on the recovered human string
  then `obj.get("s")` — `s` is the message itself, not a dict. The child
  parse died; parent saw no `SEQ=` line. One decrypt + regex extraction in
  the same process avoids the whole class.
- **Nonce is a comparison, not a consumption counter.** Root verified the
  same decoder/key/envelope decrypts twice fine; do not explain failures
  with "nonce used up".
- **Metadata assertion failure is not a password failure** — it happens
  before any input. Report it as such; never call it a wrong pattern.
- Deleting the private key on ANY failure path (parse bugs included) forces
  a new key + new nonce + fresh encryption. That is the security rule
  ("执行后立即删除临时私钥和密文(无论成功/失败)") — budget for it.

## Device-side recipe (unchanged, verified)

Wake → slow bottom-swipe to bouncer (`input swipe 540 2300 540 1100 500`) →
fresh `uiautomator dump` → `lockPatternView` bounds `[L,T,R,B]` → grid
centers by thirds (`n(row,col) = (L+(R-L)*(col+0.5)/3, T+(B-T)*(row+0.5)/3)`)
→ one `motionevent DOWN…MOVE…UP` → verify → `finally` restore + delete.

Decrypt (if not using the unified module): openssl pkeyutl
`-pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256`.

## Verification & hygiene

- Success = keyguard released (`showing=false`) AND target app foreground
  AND its UI dump has real content. Exit code 0 of the input command is NOT
  success. Never retry after one failed draw (wrong-pattern lockout risk).
- MIUI blackens screencap while keyguard shows — uiautomator dump is the
  trustworthy layout source.
- `screen_off_timeout`: `settings get system screen_off_timeout` may return
  `null` → set 120000 for the op, restore-or-delete in `finally`.
- macOS: no `timeout` binary (exit 127); use the script's own bound + the
  terminal tool timeout. System python may hit the Xcode license prompt →
  use `~/.hermes/hermes-agent/venv/bin/python3`.
- Natural sleep re-lock after auth is NOT a password failure — record it as
  natural sleep; do not re-input with deleted material.
