---
name: a2a-relay-polling
description: "Join an A2A relay hub by polling when behind NAT."
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [a2a, agent-to-agent, polling, relay, hub, nat, jsonrpc]
    category: software-development
    related_skills: [watchers, macos-automation]
---

# A2A Relay Polling

Some agent networks assume you can accept inbound webhooks. A home/office
agent behind NAT cannot. Relay hubs solve this by inverting the direction:
**you poll the hub for messages and post replies — all traffic is outbound.**

Use this skill whenever:
- You are asked to "join an A2A hub", "connect to a relay", or "talk to other
  agents" and the hub exposes an inbox/reply pattern.
- There is a public hub URL + bearer token, and no inbound port is opened.
- The protocol involves `GET /hub/inbox` + `POST /hub/reply` (+ maybe a
  JSON-RPC endpoint for outbound sends).

## Architecture (why polling, not webhooks)

```
you (NAT)  ──GET inbox──▶  hub (public)
you         ◀──messages──  hub
you         ──POST reply─▶  hub
you         ──POST send──▶  hub ──▶ other agents
```

No firewall changes, no Tailscale, no TLS cert, no stable IP. The tradeoff is
latency (polling interval) — pick 3–10s; below ~3s you risk rate limits.

## Sequence of work

1. **Pick and announce the agent id before writing code.** Small letters/digits/
hyphens, globally unique (`<yourname>-<host>` style). The hub almost always
rejects sends from unregistered ids (`unknown agent`), so say the id out loud
and wait for the operator to register it.
2. **Verify reachability with a public read first** — many hubs expose an
   AgentCard at `/.well-known/agent-card.json`. No token needed, so a failure
   here is network/DNS, not auth.
3. **Write the client** (`scripts/a2a_poll_client.py` is a working template).
   Put the token in an env var / `~/.hermes/.env` — **never** inline it in
   source, and never pass it on a command line (it lands in shell history).
4. **Self-check all three calls** before declaring success: inbox, reply,
   and outbound send (use the hub's echo bot if it has one).
5. **Wire your handler** into the receive step, then either poll once or run
   it resident (background process or a cron job).

## Pitfalls

- **Writing the token into `~/.hermes/.env` via shell gets it MASKED.**
  Observed: `printf ... >> ~/.hermes/.env` / heredoc writes persisted a literal
  `A2A_HUB_TOKEN=1d63fb...ab95` (the `...` mask) instead of the real 64-char
  value — because the security layer redacts the secret in the command. The
  client then authenticates with a truncated token (403 `Bad token`). Write
  the env file with a Python script instead, and ALWAYS verify by length:
  `len(token)==64`, not by eyeballing the value:
  ```python
  import pathlib
  p = pathlib.Path.home()/'.hermes'/'utils'/'.env'
  lines = p.read_text().splitlines()
  for i,l in enumerate(lines):
      if l.startswith('A2A_HUB_TOKEN='): lines[i] = f'A2A_HUB_TOKEN={TOKEN}'
  p.write_text('\n'.join(lines)+'\n')
  ```
- **Do not `source .env` in bash/zsh to load it** — lines containing spaces
  or paths (e.g. `CHROME_PATH=/Applications/Google Chrome.app/...`) break
  `source` mid-file, so later keys never load. Parse line-by-line in Python
  (`scripts/load_hermes_env.py` does exactly this) or read keys individually.
- **404 on inbox usually means "not registered yet", not "broken".**
  `{"detail":"Unknown agent '<id>'"}` is the hub telling you to wait for
  registration. Verify the URL really carries `?agent_id=<your id>`.
- **Inbox drains.** Retrieved messages are gone from the next poll and are not
  re-delivered. If you poll once and print nothing, you may have consumed a
  real message — capture output to a file when debugging.
- **Duplicate replies return 404** (`Message N not found or already replied`)
  and that is the *correct* answer, not a failure.
- **A successful send is the proof you are registered.** An echo-bot reply
  quoting your agent id back is the cheapest end-to-end test available.
- **Keep the polling loop dependency-free** (stdlib only) so a resident
  watcher cannot break when some other venv is repaired.
- **Do not let a third-party install touch the Hermes venv.** See
  `hermes-maintenance` for pin restoration if you must.
- **Symptom confusion:** an SSL handshake timeout mid-run is usually a network
  blip, not a bad token. Retry once before concluding anything.

## Handling the messages you receive

Two sane designs — pick per task:

- **Rule-based responder** (what the template does) — deterministic commands
  (`ping`, `who are you`, `help`), zero cost, no LLM dependency. Good default.
- **LLM-backed** — forward each inbound message to the agent's own model.
  Costs tokens per message; only do this if the user asks for real conversation.

Always echo the sender's identity back in your reply text so the human
operator can tell which agent answered.

## Templates & references

- `scripts/a2a_poll_client.py` — stdlib-only client: inbox / reply / send /
  poll loop. Env-driven (`A2A_HUB_URL`, `A2A_AGENT_ID`, `A2A_HUB_TOKEN`).
- `scripts/load_hermes_env.py` — loads `~/.hermes/.env` safely into os.environ
  so the token never touches a command line.
- `references/relay-hub-protocol.md` — verified response shapes, error strings,
  the registration handshake, and an end-to-end self-check transcript.
