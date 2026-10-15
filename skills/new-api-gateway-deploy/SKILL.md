---
name: new-api-gateway-deploy
description: "Deploy New-API LLM gateway behind nginx with HTTPS."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [new-api, one-api, llm-gateway, nginx, reverse-proxy, certbot, https, deployment, openai-compatible]
    homepage: https://github.com/QuantumNous/new-api
    related_skills: [mainland-china-networking, hermes-agent]
---

# Deploy New-API LLM Gateway behind nginx

Install QuantumNous/new-api (One-API successor) — an OpenAI-compatible LLM
gateway aggregating multiple upstream model vendors — and front it with nginx
serving HTTP :80 + HTTPS :443.

Use when asked to self-host an LLM gateway / API aggregator, expose one
OpenAI-compatible endpoint spanning multiple vendors (DeepSeek, GLM, Kimi,
Hunyuan, …), or put a model management UI + `/v1` endpoint on a domain.

Target end state:

```
external request
   ├─ :80   ─┐
   │         ├─→ nginx ──→ 127.0.0.1:3000 (new-api)
   └─ :443 ─┘     TLS terminated by nginx
```

## Prerequisites (verify first)

```bash
uname -m                 # x86_64 or arm64 (32-bit unsupported)
sudo -n true && echo ok  # need passwordless sudo, OR be root
free -h                  # new-api itself only ~30MB RSS
ss -tlnp | grep -E ':(80|443|3000) '
```

Docker is optional. On small hosts (<2GB RAM) the **official Go binary +
SQLite** is lighter and simpler than docker-compose.

## Step 1 — Install the binary

```bash
curl -s https://api.github.com/repos/QuantumNous/new-api/releases/latest \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tag_name']); \
[print('-',a['name'],round(a['size']/1048576,1),'MB') for a in d.get('assets',[])]"
```

Asset naming: `new-api-<tag>` = linux amd64; `new-api-arm64-<tag>` = arm64.

### Download — mainland China CRITICAL

GitHub releases direct are often ~50 KB/s (129MB → 40 min). Test proxies:

```bash
for M in https://gh-proxy.com/ https://ghfast.top/ https://ghproxy.net/; do
  printf '%-28s ' "$M"
  timeout 25 curl -sL -o /dev/null -w 'HTTP %{http_code} %{speed_download} B/s\n' \
    --max-time 22 "${M}https://github.com/QuantumNous/new-api/releases/download/<TAG>/new-api-<TAG>"
    2>/dev/null || echo FAIL
done
```

Typical winner: `gh-proxy.com` ≈ 8.8 MB/s (175x faster than direct).

```bash
sudo mkdir -p /opt/new-api/data /opt/new-api/logs
sudo chown -R $USER:$USER /opt/new-api
cd /opt/new-api
curl -sL --max-time 300 --retry 3 -o new-api \
  "https://gh-proxy.com/https://github.com/QuantumNous/new-api/releases/download/<TAG>/new-api-<TAG>"
curl -sL -o checksums-linux.txt \
  "https://gh-proxy.com/https://github.com/QuantumNous/new-api/releases/download/<TAG>/checksums-linux.txt"
sha256sum new-api            # MUST match the checksums entry
chmod +x new-api && ./new-api --version
```

## Step 2 — Decide port ownership BEFORE installing nginx

**Two processes cannot bind the same port.** Decide up front:

| Scheme | new-api | nginx | Use when |
|---|---|---|---|
| **A (recommended)** | 3000 | 80 + 443 | HTTPS / real reverse proxy |
| B | 80 | none | plain HTTP only, simplest |
| C | 80 | 443→? | **broken** — nothing to proxy to |

Going B→A later requires moving new-api off 80 first. Pick A at install.

To let new-api (non-root) bind 80/443 directly (scheme B):

```bash
sudo setcap 'cap_net_bind_service=+ep' /opt/new-api/new-api
getcap /opt/new-api/new-api
```

Without this, non-root binding of <1024 → PermissionError.

## Step 3 — systemd unit

Write to `/etc/systemd/system/new-api.service` (needs sudo — the write_file
tool refuses /etc paths, so stage to /tmp then `sudo cp`):

```ini
[Unit]
Description=New-API LLM Gateway
Documentation=https://github.com/QuantumNous/new-api
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/new-api
ExecStart=/opt/new-api/new-api --port 3000 --log-dir /opt/new-api/logs
Restart=always
RestartSec=5
Environment=TZ=Asia/Shanghai
Environment=SQLITE_PATH=/opt/new-api/data/new-api.db

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp /tmp/new-api.service /etc/systemd/system/new-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now new-api.service
sudo systemctl is-active new-api.service
curl -s localhost:3000/api/status | head -c 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/
```

Only flags are `--port` and `--log-dir`. **No built-in TLS** (the
ListenAndServeTLS symbols in the binary come from pprof deps, not the server).

## Step 4 — Initialize admin

`/api/setup` needs a password CONFIRMATION field named **`confirmPassword`**
(camelCase) — NOT `password2`, `confirm_password`, `password_confirm`.
Wrong key → silent `Passwords do not match`.

```bash
curl -s -X POST http://127.0.0.1:3000/api/setup \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"<GEN>","confirmPassword":"<GEN>"}'

# login is /api/user/login — NOT /api/auth/login (that 404s)
TOK=$(curl -s -X POST http://127.0.0.1:3000/api/user/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"<GEN>"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
```

Save creds immediately to a `chmod 600` file.

## Step 5 — Add an upstream channel (THE big gotcha)

Create takes a **nested envelope with required `mode`**:

```json
{"mode":"single","channel":{ ... }}
```

- `mode` must be `"single"` or `"batch"` → else `Unsupported add mode`
- Flat fields → `channel cannot be empty`. That message literally means
  `AddChannelRequest.Channel == nil` (JSON unbind failed), NOT a missing field
- Field is **`group` (singular string)**, not `groups`
- `mode` / `multi_key_mode` live on the ENVELOPE, not the channel object

```bash
curl -s -X POST http://127.0.0.1:3000/api/channel/ \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOK" \
  -d '{"mode":"single","channel":{
        "name":"myvendor","type":1,
        "key":"<UPSTREAM_KEY>",
        "base_url":"https://<vendor>/v1",
        "models":"model-a,model-b",
        "group":"default","priority":0,"weight":1,"status":1
      }}'
```

**Updating** is the OPPOSITE shape — `PUT` with a **FLAT** body:

```bash
curl -s -X PUT http://127.0.0.1:3000/api/channel/ \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOK" \
  -d '{"id":1,"base_url":"https://<vendor>"}'
```

PUT + nested `{"channel":{...}}` → `record not found`.

Source of truth if the API drifts:
`raw.githubusercontent.com/QuantumNous/new-api/main/controller/channel.go`
(see `AddChannelRequest`, `validateChannel`). Reading the real source beats
guessing field names.

## Step 6 — Enable self-use mode (required before inference)

Otherwise every call → `Model X price not configured. ... enable self-use mode`.

`/api/option/` does NOT work — it creates a junk row. Real option keys are
**Capitalized** in the sqlite `options` table. Fix via DB:

```bash
sudo python3 - <<'PY'
import sqlite3
con = sqlite3.connect("file:/opt/new-api/data/new-api.db?mode=rw", uri=True)
cur = con.cursor()
cur.execute("UPDATE options SET value='true' WHERE key='SelfUseModeEnabled'")
cur.execute("DELETE FROM options WHERE key='self_use_mode_enabled'")
con.commit(); con.close()
PY
sudo systemctl restart new-api.service
curl -s localhost:3000/api/status \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["self_use_mode_enabled"])'
```

## Step 7 — API tokens & reading the FULL key

Every list/create API returns a **masked** key (`sJBM****6I8v`) — useless.
Read real keys straight from sqlite:

```bash
sudo python3 - <<'PY'
import sqlite3
con = sqlite3.connect("file:/opt/new-api/data/new-api.db?mode=ro", uri=True)
for r in con.execute("SELECT id,key FROM tokens"): print(r)
PY
```

New tokens default `remain_quota=0` and empty `group` → every request returns
`401 Invalid token`. Fix both:

```sql
UPDATE tokens SET remain_quota=500000000, unlimited_quota=1,
  'group'='default', model_limits_enabled=0, status=1;
```

Then verify END-TO-END (don't stop at `GET /v1/models` succeeding):

```python
urllib.request.urlopen(urllib.request.Request(
  BASE+"/v1/chat/completions",
  data=json.dumps({"model":"m","messages":[{"role":"user","content":"Say OK"}],
                   "max_tokens":400}).encode(),
  headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}))
```

Low `max_tokens` yields EMPTY content with reasoning models — not a bug.

## Step 8 — nginx reverse proxy

```bash
sudo apt-get install -y nginx
```

`/etc/nginx/sites-available/newapi`:

```nginx
upstream newapi_backend {
    server 127.0.0.1:3000;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name YOUR_DOMAIN;

    # MUST precede the redirect or certbot http-01 gets 301'd and fails
    location /.well-known/acme-challenge/ {
        proxy_pass http://newapi_backend;
        proxy_set_header Host $host;
    }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name YOUR_DOMAIN;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 64m;
    proxy_http_version 1.1;
    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    location / {
        proxy_pass http://newapi_backend;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

nginx 1.24 uses `listen 443 ssl http2;`; 1.25+ uses separate `http2 on;`.
A stray `http2 on;` on 1.24 → `unknown directive "http2"`.

Needs the websocket map in `/etc/nginx/conf.d/websocket_upgrade.conf`:

```nginx
map $http_upgrade $connection_upgrade { default upgrade; '' ''; }
```

```bash
sudo ln -sf /etc/nginx/sites-available/newapi /etc/nginx/sites-enabled/newapi
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## Step 9 — Let's Encrypt HTTPS

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN --non-interactive --agree-tos \
  -m admin@YOUR_DOMAIN --no-eff-email --redirect
sudo certbot renew --dry-run
systemctl is-enabled certbot.timer
```

Pre-flight — confirm the ACME path is NOT redirected away:

```bash
printf 'probe' | sudo tee /var/www/html/probe.txt
curl -s -o /dev/null -w '%{http_code}\n' \
  http://YOUR_DOMAIN/.well-known/acme-challenge/probe.txt
# 200 = OK; 301 = your redirect rule will break certbot
```

**Always verify WITHOUT `-k`.** `curl -k` hides the exact error the user
sees in a browser:

```bash
curl -sS https://YOUR_DOMAIN/ -o /dev/null -w '%{http_code}\n'
echo | openssl s_client -connect YOUR_DOMAIN:443 -servername YOUR_DOMAIN \
  2>/dev/null | openssl x509 -noout -issuer   # must be Let's Encrypt
```

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `channel cannot be empty` (create) | flat body | `{"mode":"single","channel":{...}}` |
| `Unsupported add mode` | no `mode` | add `"mode":"single"` |
| `record not found` (update) | POST + nested | PUT + FLAT body |
| `Passwords do not match` | wrong confirm key | `confirmPassword` camelCase |
| `Invalid URL /api/auth/login` | wrong endpoint | `/api/user/login` |
| `Model X price not configured` | self-use off | `SelfUseModeEnabled=true` in sqlite |
| `401 Invalid token` | quota 0 / blank group | UPDATE tokens in sqlite |
| masked key `xxxx****xxxx` | API never returns full key | read sqlite `tokens.key` |
| empty `content` reply | `max_tokens` too low | 300–400 (thinking models) |
| `unknown directive "http2"` | nginx <1.25 | `listen 443 ssl http2;` |
| certbot http-01 fails | challenge 301'd | add `/.well-known/` block before redirect |
| unit reverts to :3000 | something overwrote it | re-check `ExecStart` |
| :80 already in use | caddy/nginx auto-installed | check `apt history.log` |

## Verification checklist

Do not declare success until all pass:

- [ ] `ss -tlnp`: nginx on 80+443, new-api on 3000
- [ ] `http://DOMAIN` → 301 → https
- [ ] `https://DOMAIN` → 200 **without `-k`**
- [ ] cert issuer = Let's Encrypt
- [ ] `/v1/models` with token → model list
- [ ] real `POST /v1/chat/completions` → non-empty content
- [ ] `certbot renew --dry-run` OK, `certbot.timer` enabled
- [ ] all services `systemctl is-enabled`

## Notes

- Cloud hosts may run agents (`sgagenttask`, `yunjing`, vendor CLIs) that
  auto-install nginx/certbot and hijack :80. If config "mysteriously" reverts,
  check `/var/log/apt/history.log` and `last`.
- Public-cloud security groups are separate from host firewall: a port can be
  LISTENing yet unreachable from outside. Test `curl http://<PUBLIC_IP>:<port>`.
- Never let two things fight over :80 — decide the owner once, up front.
- Keys that transited plaintext HTTP should be rotated afterward.
