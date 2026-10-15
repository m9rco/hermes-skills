---
name: mem0
description: Use when storing/searching agent memories via Mem0 Platform.
---

# Mem0 Persistent Memory

Wraps the Mem0 Platform API (`mem0ai` SDK v2.2.1, installed in the Hermes venv) into a CLI for storing and retrieving long-term memories per user/agent/app.

## Prerequisites
- `~/.hermes/.env` contains `MEM0_API_KEY=m0-...` (already configured)
- Python: `~/.hermes/hermes-agent/venv/bin/python3` (has mem0ai installed)

## CLI Usage

Script: `~/.hermes/scripts/mem0_hermes.py` (run with the venv python).

The script forces **direct connection** (strips proxy env vars) — api.mem0.ai is reachable from CN directly, and the Clash proxy causes intermittent SSL EOF.

```bash
P=~/.hermes/hermes-agent/venv/bin/python3
$P ~/.hermes/scripts/mem0_hermes.py <cmd> [args]
```

### Commands

| Command | Example | Notes |
|---|---|---|
| `add` | `add "用户喜欢简洁回复" --user pushaowei` | top-level entity kwargs (`user_id=`/`agent_id=`/`app_id=`); optional `--metadata '{"k":"v"}'`; returns `{event_id, status:PENDING}` (async) |
| `search` | `search "用户偏好?" --user pushaowei --limit 5` | semantic search; **requires `filters={'user_id': ...}` style** (SDK quirk: search takes filters, add takes top-level) |
| `list` | `list --user pushaowei --limit 50` | get_all with filters; prints `- memory (id, created)` |
| `delete` | `delete --memory-id <id> --user pushaowei` | delete one memory by id |
| `reset` | `reset --user pushaowei` | wipe all memories for a scope |
| `ping` | `ping` | connectivity + auth check (adds a scratch memory under user `ping_probe`) |

## API Quirk (mem0ai 2.2.1) — IMPORTANT

```python
client.add(text, user_id="x")            # top-level entity kwargs OK
client.search(q, filters={"user_id": "x"}) # filters dict REQUIRED
client.get_all(filters={"user_id": "x"})   # filters dict REQUIRED
client.delete(memory_id=id, filters={"user_id": "x"}) # filters dict REQUIRED
```
Do NOT pass `filters=` to `add()` — it raises ValidationError "At least one entity ID is required".

## Python API

```python
import os
# key auto-read from env; script already loads ~/.hermes/.env
from mem0 import MemoryClient
c = MemoryClient(api_key=os.environ["MEM0_API_KEY"])
c.add("fact", user_id="alice")
c.search("query", filters={"user_id": "alice"}, limit=5)
```

## Pitfalls
- Proxy: `api.mem0.ai` fails intermittently through Clash (SSL UNEXPECTED_EOF) — always strip proxy env vars in the script (already done).
- Memory `status: PENDING` on add is normal — processing is async; search shortly after usually still finds it.
- Xcode license blocks system `python3`/`pip3` — always use the venv python.
