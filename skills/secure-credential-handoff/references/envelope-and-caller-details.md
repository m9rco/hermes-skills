# Envelope contract, self-tests, and failure postmortems

## Exact outer envelope (six fields, verified against controller-declared values)

```json
{
  "ciphertext_hex": "512 hex chars (256 bytes for RSA-2048)",
  "algorithm": "RSA-OAEP-SHA256",     // EXACT — not "RSA-OAEP"
  "mgf1": "SHA256",
  "label": null,
  "key_sha256": "<sha256 of the PUBLIC PEM file bytes>",
  "nonce": "<32 hex chars, public anti-replay tag, not secret>"
}
```

Inner plaintext (only visible in memory after decrypt) is a compact JSON
with EXACTLY three keys:

```json
{"t": "<task_id>", "n": "<the same nonce>", "s": "<original human message, a natural-language STRING>"}
```

- `t` must equal the fixed task id; `n` must equal the outer nonce; `s` is
  the human instruction — verify t/n, NEVER parse s as JSON (see postmortem 2).
- Compact JSON (`separators=(",",":")`, `ensure_ascii=False`) makes byte
  size vary with the message; do NOT infer protocol from byte count.
- `ciphertext_hex` length must equal `key.key_size // 4` hex chars (512 for
  RSA-2048).

## Unified decoder signature (controller-supplied module, use as-is)

```python
def decrypt_envelope(envelope, private_key_pem_bytes, *,
                     expected_key_sha256, expected_nonce, expected_task):
    # returns the original human message string in memory
    # raises EnvelopeError with fixed labels on any mismatch
```

It checks: outer is exactly the six keys; algorithm/mgf1/label exact;
key_sha256 == sha256(private.public_key PEM) == expected; nonce matches;
hex length valid; decrypts OAEP(SHA256, MGF1-SHA256, label=None); inner is
exactly {t,n,s}; t/n match expected; s is a non-empty UTF-8 str ≤256 bytes.

## Self-test discipline (before any real use)

- Run the module's `--self-test` (dummy envelope + dummy key, no device,
  no real credentials). E.g. `python3 -B normal_auth_transaction.py --self-test`.
- Never use the real key/cipher as a "decrypt probe" — dummy only.
- Save the raw stdout + exit code; report the exact pass count.

## Postmortem 1 — wrong algorithm literal destroyed the handshake

Caller asserted `algorithm == "RSA-OAEP"`; the real envelope field is
`"RSA-OAEP-SHA256"`. The metadata check failed BEFORE any decrypt, the
script's `finally` deleted the only private key + cipher, and the
handshake could not be retried — a fresh key pair + new cipher were needed.
Lessons: assert against the controller's DECLARED metadata, not an assumed
literal; do not let `finally` cleanup of credentials run on pre-decrypt
validation failures if recovery is still possible; record expected vs actual
field values for audit.

## Postmortem 2 — treating the decrypted message as JSON

Caller called `decrypt_envelope` twice (two separate subprocesses):
subprocess #1 printed DEC_OK (decrypt succeeded); subprocess #2 tried
`json.loads(s)` on the human natural-language string, which raised (stderr
not captured), so the parent saw no `SEQ=` line and printed `NO_SEQ_OUT`.
The failure was initially misdiagnosed as a parse-branch (`obj.get("s")
-> None`) via a DUMMY whose s was deliberately JSON — the dummy matched the
caller bug, not reality. Root later confirmed s is an 18-char natural
language string (e.g. "我的手机密码…划线…"). Lessons: never `json.loads(s)`;
never re-decrypt in a second subprocess; capture child stderr; when the
payload contract is unverified, wait for the controller's unified decoder
rather than guessing.

## Authenticated unlock call sequence (single short script, no round-trips)

1. `input keyevent KEYCODE_WAKEUP`; sleep ~1.2s
2. slow swipe up `input swipe 540 2300 540 1100 500` (bouncer)
3. FRESH `uiautomator dump /sdcard/view.xml` + pull
4. regex `lockPatternView[^>]*bounds="\[\d+,\d+\]\[\d+,\d+\]"`
5. grid cells = region divided into thirds (row-major 1..9), centers
6. ONE `input motionevent DOWN x y`, MOVE each subsequent cell, UP at last
   (single attempt; independent downTime per input call — never split swipes)
7. verify: `dumpsys window policy` shows `showing=true` ABSENT and
   foreground is the target app; unlock = keyguard false + app visible
8. finally: delete private key + cipher + dump + /sdcard/view.xml; restore
   original screen_off_timeout and read it back

MIUI screenshots may be blacked out on the lock screen (99.9% pure black) —
use the UI dump bounds, not pixels, as the trusted layout.

## Bounded screen-guard (transact_with_screen_guard pattern)

Signature: `transact_with_screen_guard(adb_path, serial, guard_state_path,
duration_seconds=1800, **transact_kwargs)` -> `{"auth": ..., "guard": ...}`.
- auth verified AND cleanup+restored true → guard starts before returning.
- guard.active=true + restore_pending=true + restored=false = in effect.
- restore: `python ops/normal_auth_screen_session.py --restore-now <abs state path>`,
  then read back the actual original value — activeness is not restored.
- Background watchdog restores by the finite deadline independently; it only
  receives screen metadata, never key/cipher/callbacks.
- Pending existing guard returns `auth:null, guard:GuardAlreadyActive` and
  consumes no credential.
