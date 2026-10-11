---
name: codex-desktop-login
description: "Use when logging into the Codex desktop app or driving Electron apps via CDP."
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [codex, chatgpt, electron, cdp, login, oauth, google, chrome]
    category: software-development
---

# Codex Desktop Login via CDP (macOS)

Login flow for the Codex desktop app (which is the `ChatGPT.app` — bundle id `com.openai.codex`, Electron-based) using Google OAuth, driven headlessly via Chrome DevTools Protocol.

## Key facts

- **Codex desktop == ChatGPT.app** on macOS: `/Applications/ChatGPT.app`, bundle id `com.openai.codex`, contains bundled `codex-cli`. OpenAI merged Codex into the ChatGPT desktop app (2026-02). `codex app` opens it.
- The desktop auth flow: app shows "继续登录" → copies a link `https://chatgpt.com/codex/desktop-auth?authorize_url=...` → browser completes OAuth → callback hits `http://127.0.0.1:1455/auth/callback` (app listens on 1455).
- **Proxy matters**: OpenAI/Google endpoints get Cloudflare-blocked from some exit nodes (esp. HK). Switch Clash to a Taiwan/Japan node before starting (`clash-verge-macos` skill). Cloudflare error shows "Unable to load site ... Ray ID".

## Steps

### 1. Start the app with CDP enabled

```bash
osascript -e 'tell application "ChatGPT" to quit' 2>&1; sleep 3
open -a "ChatGPT" --args --remote-debugging-port=9222 --remote-allow-origins=*
sleep 6
curl -s http://127.0.0.1:9222/json   # find the 'page' target, type=page, title=ChatGPT, url=app://-/index.html
```

CDP over WebSocket needs `websocket-client` (pip3 install websocket-client).

### 2. Click "继续登录" and grab the auth URL

```python
import json, urllib.request, websocket, time
page = next(t for t in json.load(open('/tmp/cdp.json')) if t.get('type') == 'page')
ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=20)
# send Runtime.evaluate with expression to find button with text '继续登录' and .click()
# then find '复制登录链接' element, click it
# clipboard: pbpaste
```

### 3. Chrome with user profile (needs the user's Google session)

A **fresh Chrome profile has no Google cookies** — Google will ask for email+password anyway. Use the user's real Chrome profile so Google session (and passkeys) are available:

```bash
pkill -9 -f "Google Chrome"   # release profile lock (SingletonLock)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9223 --remote-allow-origins=* &
```

Login to Google as the saved account: read `~/Library/Application Support/Google/Chrome/Default/Preferences` → `"email":"..."` (user's own Chrome data).

### 4. Drive the OAuth flow in Chrome via CDP

- Navigate the **authorize_url** directly (skip the chatgpt.com wrapper which Cloudflare sometimes blocks): `Page.navigate` to the decoded `authorize_url` query param.
- On auth.openai.com login page, click element whose text contains `Google` ("使用 Google 账户继续").
- Google may show **challenge/selection** (2FA method picker) → click "输入您的密码" → fill `input[type=password]` → click 下一步.
  - Set input value via native setter: `Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(input, pwd)` + dispatch input/change events.
  - Click buttons by computing center coordinates from getBoundingClientRect() and dispatching `Input.dispatchMouseEvent` mousePressed/mouseReleased (JS .click() often does NOT work on Google's custom widgets; real mouse events do).
- 2FA SMS: click the option LI containing 接收验证码 (get exact y from leaf text element), wait for SMS, fill `#idvPin` (Input.insertText), click 下一步.
- Google may show challenge/ipp/verify after sending SMS. Fill code, next.
- Then OpenAI consent page (选择一个工作空间) → click 继续.

### 5. Verify login

- Check `curl http://127.0.0.1:9222/json` → page URL becomes `app://-/index.html?initialRoute=/space/...` (logged in).
- App main UI text shows 首页/空间/定时任务/插件.
- `lsof -iTCP:1455` shows the codex callback connection was made.

## Pitfalls

- **JS .click() fails on Google custom widgets** — use Input.dispatchMouseEvent with real coordinates. Element's getBoundingClientRect gives page coords; CDP mouse events use viewport coords (window is scrolled to 0,0 for these flows).
- **URL-encode group names** when hitting mihomo API (♻️ 自动选择 etc.) — `urllib.parse.quote`.
- **URLTest groups ignore manual node selection** — set the parent Selector group (🚀 节点选择) instead.
- **HTTP/2 framing errors on git push through proxy** — use SSH remote (`git@github.com:...`) instead of HTTPS.
- **ChatGPT.app quit + relaunch** resets some state; callback port 1455 only listens while app is waiting for auth.
- vision_analyze may be unavailable (model-dependent); drive by DOM text + coordinates instead.

## Related skills

- `clash-verge-macos` — proxy setup, node switching (Taiwan node for OpenAI auth).
- `hermes-agent` — general Hermes operations.
