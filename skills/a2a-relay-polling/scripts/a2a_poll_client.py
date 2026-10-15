#!/usr/bin/env python3
"""Relay-hub polling client template (stdlib only, NAT-safe, outbound-only).

Covers the three calls a relay A2A hub needs:
  1. GET  /hub/inbox?agent_id=<ID>   -> {"messages":[{"id":2,"from":..,"text":..}]}
  2. POST /hub/reply                 -> {"id":2,"text":"..."}  (404 if answered)
  3. POST /a2a/v1  (A2A JSON-RPC)    -> send a message to another agent

Token comes from env A2A_HUB_TOKEN - never hardcode it. All traffic is
outbound, so this works behind NAT with no inbound ports.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# ---- config from env ------------------------------------------------------
HUB = os.environ.get("A2A_HUB_URL", "https://example-hub.example.com")
AGENT_ID = os.environ.get("A2A_AGENT_ID", "my-agent")
TOKEN = os.environ.get("A2A_HUB_TOKEN", "")
UA = f"relay-poll-client/1.0 ({AGENT_ID})"


def _auth() -> dict[str, str]:
    if not TOKEN:
        raise SystemExit("A2A_HUB_TOKEN is not set - export it (or load .env) first.")
    return {"Authorization": f"Bearer {TOKEN}", "User-Agent": UA}


def _request(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    for k, v in {**_auth(), **(headers or {})}.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


# ---- 1. inbox -------------------------------------------------------------
def inbox():
    code, body = _request(f"{HUB}/hub/inbox?agent_id={AGENT_ID}")
    if code != 200:
        # 404 here usually means: not registered yet, not broken
        return [{"_error": f"HTTP {code}: {body[:200]}"}]
    try:
        return json.loads(body).get("messages", [])
    except Exception as e:
        return [{"_error": f"bad json: {e}"}]


# ---- 2. reply -------------------------------------------------------------
def reply(msg_id, text):
    payload = json.dumps({"id": msg_id, "text": text}).encode()
    return _request(f"{HUB}/hub/reply", data=payload,
                    headers={"Content-Type": "application/json"})


# ---- 3. outbound send to another agent -----------------------------------
def send(target, text, msg_id="m1"):
    body = {
        "jsonrpc": "2.0", "id": "1", "method": "SendMessage",
        "params": {"message": {
            "role": "ROLE_USER", "messageId": msg_id,
            "parts": [{"text": f"@{target} {text}"}],
            "metadata": {"from": AGENT_ID},
        }},
    }
    code, raw = _request(f"{HUB}/a2a/v1", data=json.dumps(body).encode(),
                         headers={"Content-Type": "application/json",
                                  "A2A-Version": "1.0"})
    if code == 200:
        try:
            parts = json.loads(raw).get("result", {}).get("message", {}).get("parts", [])
            if parts:
                return code, parts[0].get("text", "")
        except Exception:
            pass
    return code, raw


# ---- message handler -----------------------------------------------------
def handle(text, sender):
    """Deterministic responder. Replace with an LLM call if the task needs it."""
    t = text.strip()
    low = t.lower()
    if low in ("ping", "hello", "hi"):
        return f"[{AGENT_ID}] pong - online, polling mode (no inbound ports)."
    if low in ("who are you", "identity", "id"):
        return f"[{AGENT_ID}] agent_id={AGENT_ID}"
    if low.startswith("echo "):
        return t[5:]
    if low in ("help", "?"):
        return "[commands] ping | who are you | echo <text> | time | help"
    if low in ("time", "date"):
        return f"[{AGENT_ID}] local time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    return (f"[{AGENT_ID}] received from '{sender}': {t!r} ({len(t)} chars). "
            "Plain relay mode - no LLM attached to this loop.")


def poll(interval=5.0, once=False, verbose=True):
    def log(*a):
        if verbose:
            print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

    log(f"polling as {AGENT_ID} every {interval}s - ctrl-C to stop")
    while True:
        for m in inbox():
            if "_error" in m:
                log("inbox error:", m["_error"])
                continue
            mid, sender, text = m.get("id"), m.get("from", "?"), m.get("text", "")
            log(f"<- #{mid} from {sender}: {str(text)[:80]}")
            ans = handle(text, sender)
            code, body = reply(mid, ans)
            log(f"-> #{mid} [{code}] {ans[:80]}")
            if code != 200:
                log("   reply body:", body[:200])
        if once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    if cmd == "poll":
        poll(once="--once" in sys.argv)
    elif cmd == "send":
        print(send(sys.argv[2], " ".join(sys.argv[3:])))
    elif cmd == "reply":
        print(reply(int(sys.argv[2]), " ".join(sys.argv[3:])))
    elif cmd == "inbox":
        print(json.dumps(inbox(), ensure_ascii=False, indent=2))
