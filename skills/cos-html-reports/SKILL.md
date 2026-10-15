---
name: cos-html-reports
description: Generate HTML reports for this user, upload them to the configured Tencent COS report path, verify the public page, and return its URL. Also supports a short-lived upload ticket for a reporting agent without sharing permanent credentials.
---

# COS HTML reports

When the user needs a report, create a readable UTF-8 HTML document, publish it, and return the verified URL. Prefer a self-contained file with inline CSS and embedded assets so one object is sufficient. Include the report date, task ID, evidence/source links, findings, limitations, and next actions appropriate to the report. Check its layout in a browser before publication. Do not publish credentials, account identifiers, private chats, or raw logs in the report.

The user's existing destination is bucket `t-gz-1252130512`, region `ap-guangzhou`, key prefix `mlab-work-1`, custom public domain `https://s.0x06.cn`. Keep this destination unless the user changes it. The user has authorized this default publication workflow for reports they request; normal report publication does not need repeated approval. The helper uses an unsigned public GET to check HTTP 200, SHA-256 equality, HTML content type, and inline disposition. It never changes bucket policy or ACL. If upload succeeds but the public URL fails verification, report that distinction and preserve the receipt; do not claim a browsable report exists.

## Publish

Use `scripts/publish_html.py` with Python 3. The configured isolated runtime is `~/.cache/mlab/cos-reports-venv/bin/python`, with the official `cos-python-sdk-v5` dependency; another Python environment with that package also works. Credentials come only from `COS_SECRET_ID` / `COS_SECRET_KEY` (optional `COS_TOKEN`) or an external, current-user-owned **0600** JSON file at `~/.config/mlab/cos.json` (`--config` overrides its location). The JSON may contain `secret_id`, `secret_key`, `token` and the four nonsecret destination fields. Environment variables `COS_REGION`, `COS_BUCKET`, `COS_BASE_PATH`, `COS_PUBLIC_URL_PREFIX` override configuration fields.

Resolve the script against the directory containing this `SKILL.md`, not the shell's current directory. For a Hermes installation, use `<skill-directory>/scripts/publish_html.py`; for Codex, the usual path is `~/.codex/skills/cos-html-reports/scripts/publish_html.py`. Substitute the resolved absolute script path in the examples below.

Do not place credentials in the skill, source, report, shell command arguments, receipts, or chat. Do not print raw SDK errors or signed URLs. Keep credential setup outside this skill's repository.

```bash
~/.cache/mlab/cos-reports-venv/bin/python scripts/publish_html.py /path/to/report.html --slug xhs-opportunities --dry-run
~/.cache/mlab/cos-reports-venv/bin/python scripts/publish_html.py /path/to/report.html --slug xhs-opportunities --output-json /path/to/publish-receipt.json
```

Each default key is `mlab-work-1/reports/YYYY/MM/DD/<slug>-<UTC timestamp>-<random>/index.html`. Preserve each report version and its credential-free JSON receipt. `--key` permits an explicit `.html` key inside `base_path` and can overwrite that specific object; prefer a new version instead. `--verify-only --key <existing-key>` rechecks public availability and hash without uploading again.

Exit status `0` means the chosen operation succeeded; inspect its fields: dry-run and ticket creation deliberately retain `success:false`, `uploaded:false`, `public_verified:false`. Only a verified published page has `success:true`. Status `3` means public verification failed, even if `uploaded:true`; `2` is a preparation/upload/ticket error; `4` means the receipt could not be saved. Verify retries are limited to three public GET attempts; do not repeatedly upload when only public access needs repair.

## Reporting agent without permanent keys

Prefer having the agent deliver its HTML and source evidence to the existing task channel, then publish on the trusted machine that already holds credentials. If direct agent upload is necessary, the trusted machine can issue a **single-key, content-bound PUT capability** after it has that exact HTML file:

```bash
python scripts/publish_html.py /path/to/report.html --slug xhs-opportunities --presign-put /private/path/put-ticket.json --expires 300 --output-json /path/to/ticket-receipt.json
python scripts/publish_html.py /path/to/report.html --use-ticket /private/path/put-ticket.json --output-json /path/to/publish-receipt.json
```

The first command creates a new 0600 ticket and makes no upload; the second uploads without permanent credentials. The signed PUT expires in 60–900 seconds and binds the exact object key, host, Content-MD5, HTML type, inline disposition, and SHA metadata. The helper also checks SHA-256 before upload and against the public response. COS enforces the signed Content-MD5; the SHA metadata itself is not a server-enforced content hash, so use a trusted uploader if deliberately constructed MD5 collisions are in scope. A ticket is a temporary secret and can be reused until expiry: transfer it through the established private mechanism, never post it publicly or print it. Keep only its safe receipt in task history; remove the ticket after use/expiry. A new report body needs a new ticket. The public report URL is separate from the signed PUT URL.

Official references: [Python SDK upload and header parameters](https://cloud.tencent.com/document/product/436/65820), [presigned PUT and content-bound headers](https://cloud.tencent.com/document/product/436/35153), [SDK initialization](https://cloud.tencent.com/document/product/436/12269).
