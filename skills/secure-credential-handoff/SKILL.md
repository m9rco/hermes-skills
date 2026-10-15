---
name: secure-credential-handoff
description: "Use when a one-time secret arrives encrypted over chat."
version: 1.0.0
metadata:
  hermes:
    tags: [security, handoff, rsa-oaep, unlock, adb, nonce, credential, screen-guard, in-memory]
---

# Secure One-Time Credential Handoff

Pattern for delivering a user-authorized one-time secret (typically an
Android unlock pattern/password) from a controller to a node over chat,
using it exactly once, in memory only, then destroying every trace. Recurred
4+ times in 2026-10 (xhs-opportunities unlock, superstar auth1–auth4) and
burned several attempts — the failure modes below are the paid-for lessons.

## When to use

- A controller says "user-authorized one-time secret, RSA-OAEP encrypted,
  decrypt in memory, never print/write/shell-arg/env/chat it".
- Device unlock for a scheduled/ADB-operated account where the unlock
  material must not enter logs, transcripts, or reports.
- Any "key handoff" where the node holds the PRIVATE half and the
  controller encrypts with the PUBLIC half.

## Protocol overview

1. **Node generates a fresh temporary RSA-2048 pair** (`openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048`). Private in a 0700 dir, 0600 file, local-only, never copied. Keep it the WHOLE session — it is the only way to decrypt.
2. **Node sends ONLY the public PEM** as a real file attachment (not just metadata/path), with its full SHA256, byte count, a fresh random `nonce` (public anti-replay tag, NOT secret), and the device serial confirmation. Save these in a key-metadata JSON.
3. **Controller encrypts** the original human message with RSA-OAEP (SHA-256, MGF1-SHA256, label=None) and sends a ciphertext JSON envelope (see references/envelope-and-caller-details.md for the exact six fields and inner t/n/s contract).
4. **Node verifies** envelope SHA + outer metadata (algorithm/mgf1/label/key_sha256=public PEM SHA/nonce) BEFORE any decrypt. Any mismatch → stop, record the exact assertion, never retry.
5. **Node decrypts ONCE, in ONE process, in memory**, feeds the recovered instruction to the already-verified input logic, verifies the real result (keyguard gone + foreground app), then finally-deletes private key + cipher + all dumps. Never prints the plaintext.

## Non-negotiable decoder discipline (learned the hard way)

- **Exact algorithm string is `RSA-OAEP-SHA256`** — not `RSA-OAEP`. A
  caller that asserted `algorithm == "RSA-OAEP"` failed its own metadata
  check before any decrypt, then its `finally` deleted the only private key.
  Verify metadata against the CONTROLLER-DECLARED values, never assumed ones.
- **The decrypted payload `s` is a human natural-language string, NOT JSON.**
  Do not `json.loads(s)`; do not look up `obj["s"]`/`obj["sequence"]`.
  A caller that re-parsed `s` as JSON died in a subprocess with no captured
  stderr and left only `NO_SEQ_OUT` — misdiagnosed as a parse branch.
  If the payload contract is ambiguous, ASK/WAIT for the unified decoder
  instead of guessing the inner structure.
- **Call `decrypt_envelope` exactly once, in one Python process.** No
  subprocess-with-stdout-adapter, no second decrypt to "re-extract" the
  sequence, no pre-decrypt probes with the real key. Two subprocess calls =
  second failure mode. A unified public module (controller-supplied) is the
  only decoder; do not hand-roll metadata assertions alongside it.
- **Do not auto-generate a replacement key pair after a cleanup.** If the
  private key was already deleted, a new handshake must be requested; a
  freshly minted key4/public that was never used just creates confusion.

## Bounded screen-guard session (keep the device awake across the work)

After auth succeeds, the device may natural-sleep and relock within minutes.
Use a finite screen-guard (controller-supplied `transact_with_screen_guard`
or equivalent): record the original `screen_off_timeout`, set a bounded
override (e.g. 1800s), spawn a credential-free detached watchdog that
restores the original value by deadline, and verify with a real readback.
Rules:

- Only `guard.active=true, restore_pending=true, restored=false` counts as
  protection in effect. `restored` must be a REAL readback after
  `--restore-now <state_path>`, never inferred from activeness.
  **CLI form trap:** the module takes the state path as a POSITIONAL
  argument to `--restore-now` — `python normal_auth_screen_session.py
  --restore-now /path/guard-state.json`. Passing `--restore-now
  --state-path X` (or a bare `--restore-now` with a separate
  `--state-path`) errors with `expected one argument` and does nothing.
- Do NOT restore early while the publisher/worker still needs the screen;
  restore only after the terminal state, then read back the original value.
- Natural sleep/relock is NOT a password failure — record it as natural
  sleep, do not guess, do not reuse deleted materials.

## ADB pattern unlock (verified caller shape)

Order inside one short script (no model round-trips between steps):
wake (`input keyevent KEYCODE_WAKEUP`) → slow swipe up → FRESH
`uiautomator dump` → find `lockPatternView` bounds → derive 3×3 grid by
thirds of the region (row-major 1–9) → single `input motionevent`
DOWN → MOVE each point → UP (one attempt, never split swipes — each
`input` call has an independent downTime) → verify keyguard false + app
foreground. No guessing, no permission changes, no retries.

Fresh-UI evidence must be collected in the SAME script batch that consumes
it (`reset-item` needs ≤120s-old evidence; a model round-trip in between
can expire it). Never reuse old screenshots/XML or fabricate
`identity_confirmed`/timestamps.

## Cleanup contract (every path, success AND failure)

- `finally` deletes private key + cipher + dump files + `/sdcard/view.xml`;
  report each deletion result explicitly.
- Restore the original temporary settings value (screen timeout) and read it
  back — never claim restored without evidence.
- Public key metadata (SHA/nonce/bytes) may stay for audit; private key,
  cipher, plaintext, sequence, coordinates NEVER enter packages/logs.
- Report auth result only as the module's safe JSON
  (`stage/error_class/input_attempted/keyguard_cleared/cleanup/restored`),
  never a handwritten substitute checkpoint.

## Pitfalls checklist

- Don't print plaintext, sequence, trajectory, coordinates, seed.
- Don't put private/cipher/temp dirs in evidence ZIPS.
- `finally` cleanup runs even on early metadata failures — a guard that
  deletes the key before decrypt loses the handshake. Check metadata BEFORE
  any decrypt, and if a subprocess failed, preserve its stderr.
- Verify by real UI state (keyguard + foreground), not command exit 0.
- After failed auth, say "materials deleted, need secure re-handoff" — do
  not pretend no authorization ever existed.

## Support files

- `references/envelope-and-caller-details.md` — exact envelope fields,
  inner t/n/s contract, self-test commands, and the two failure postmortems.
