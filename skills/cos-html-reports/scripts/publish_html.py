#!/usr/bin/env python3
"""Publish one UTF-8 HTML report to COS; emit only a credential-free receipt."""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULTS = {
    "region": "ap-guangzhou",
    "bucket": "t-gz-1252130512",
    "base_path": "mlab-work-1",
    "public_url_prefix": "https://s.0x06.cn",
}
ENV_KEYS = {key: "COS_" + key.upper() for key in DEFAULTS}
ENV_KEYS.update(secret_id="COS_SECRET_ID", secret_key="COS_SECRET_KEY", token="COS_TOKEN")
MAX_HTML_BYTES = 25 * 1024 * 1024


class PublishError(Exception):
    """Contains only a predefined, credential-free error code."""


def utcnow():
    return datetime.now(timezone.utc)


def read_private_json(path):
    """Reject symlinks, non-owned files, and permissions other than 0600."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(Path(path).expanduser(), flags)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise PublishError("private_file_requires_owner_and_mode_0600")
            result = json.load(handle)
    except PublishError:
        raise
    except Exception:
        raise PublishError("private_file_unreadable_or_invalid") from None
    if not isinstance(result, dict):
        raise PublishError("private_file_must_be_json_object")
    return result


def write_json(path, value, *, exclusive=False):
    """Atomic 0600 receipt, or exclusive 0600 capability ticket."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if exclusive:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        return
    fd, temporary = tempfile.mkstemp(prefix=".cos-receipt-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_config(path=None, *, require_credentials=False):
    config = dict(DEFAULTS)
    location = Path(path).expanduser() if path else Path.home() / ".config/mlab/cos.json"
    if path or location.exists() or location.is_symlink():
        stored = read_private_json(location)
        config.update({key: stored[key] for key in ENV_KEYS if key in stored})
    for key, env in ENV_KEYS.items():
        if env in os.environ:
            config[key] = os.environ[env]
    for key in DEFAULTS:
        if not isinstance(config[key], str) or not config[key]:
            raise PublishError("invalid_configuration")
    if not re.fullmatch(r"[a-z0-9-]+", config["region"]):
        raise PublishError("invalid_region")
    if not re.fullmatch(r"[a-z0-9-]+-[0-9]+", config["bucket"]):
        raise PublishError("invalid_bucket")
    validate_path(config["base_path"])
    prefix = urllib.parse.urlsplit(config["public_url_prefix"])
    if (prefix.scheme != "https" or not prefix.hostname or prefix.username or prefix.password
            or prefix.query or prefix.fragment):
        raise PublishError("public_url_prefix_requires_unsigned_https")
    config["public_url_prefix"] = config["public_url_prefix"].rstrip("/")
    if require_credentials and not all(isinstance(config.get(k), str) and config[k]
                                       for k in ("secret_id", "secret_key")):
        raise PublishError("credentials_missing_use_environment_or_private_config")
    return config


def validate_path(value):
    if (not value or len(value.encode("utf-8")) > 1024
            or any(part in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", part)
                   for part in value.split("/"))):
        raise PublishError("invalid_object_path")


def choose_key(config, slug, explicit=None):
    if explicit:
        key = explicit
    else:
        clean_slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:64] or "report"
        now = utcnow()
        key = (f'{config["base_path"]}/reports/{now:%Y/%m/%d}/'
               f'{clean_slug}-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}/index.html')
    validate_path(key)
    if not key.startswith(config["base_path"] + "/") or not key.endswith(".html"):
        raise PublishError("key_must_be_html_inside_base_path")
    return key


def public_url(config, key):
    return config["public_url_prefix"] + "/" + urllib.parse.quote(key, safe="/")


def read_html(path):
    try:
        location = Path(path)
        fd = os.open(location, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise PublishError("html_must_be_regular_file")
            if info.st_size > MAX_HTML_BYTES:
                raise PublishError("html_exceeds_25_mib")
            body = handle.read(MAX_HTML_BYTES + 1)
        if len(body) > MAX_HTML_BYTES:
            raise PublishError("html_exceeds_25_mib")
        content = body.decode("utf-8-sig")
    except PublishError:
        raise
    except Exception:
        raise PublishError("html_unreadable_or_not_utf8") from None
    if not body or len(body) > MAX_HTML_BYTES or not re.search(r"<html(?:\s|>)", content, re.I):
        raise PublishError("input_must_be_nonempty_html_document")
    return body


def digest(body):
    return hashlib.sha256(body).hexdigest()


def upload_headers(body):
    return {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Disposition": "inline",
        "Content-MD5": base64.b64encode(hashlib.md5(body).digest()).decode("ascii"),
        "x-cos-meta-sha256": digest(body),
    }


def make_client(config):
    # SDK HTTP diagnostics can contain signed request details. Keep them disabled.
    logging.disable(logging.CRITICAL)
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError:
        raise PublishError("sdk_missing_install_cos_python_sdk_v5") from None
    return CosS3Client(CosConfig(
        Region=config["region"], SecretId=config["secret_id"], SecretKey=config["secret_key"],
        Token=config.get("token") or None, Scheme="https", Timeout=30))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_public(url, expected_sha256, expected_bytes, *, attempts=3, timeout=20):
    """Read the unsigned public URL, require HTTP 200 and exact body SHA-256."""
    last = {"verified": False, "error": "public_verification_failed"}
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"}, method="GET")
            with opener.open(request, timeout=timeout) as response:
                status = response.status
                body = response.read(expected_bytes + 1)
                actual = digest(body)
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
                disposition = response.headers.get("Content-Disposition", "").split(";", 1)[0].lower().strip()
                last = {"verified": status == 200 and len(body) == expected_bytes and actual == expected_sha256
                        and content_type == "text/html" and disposition in ("", "inline"),
                        "http_status": status, "sha256": actual,
                        "bytes": len(body), "content_type": content_type,
                        "content_disposition": disposition, "attempts": attempt + 1}
                if last["verified"]:
                    return last
                last["error"] = "public_content_mismatch"
        except urllib.error.HTTPError as error:
            last = {"verified": False, "http_status": error.code,
                    "error": "public_http_error", "attempts": attempt + 1}
        except Exception:
            last = {"verified": False, "error": "public_network_error", "attempts": attempt + 1}
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    return last


def upload_sdk(client, config, key, body):
    headers = upload_headers(body)
    response = client.put_object(
        Bucket=config["bucket"], Key=key, Body=body,
        ContentType=headers["Content-Type"], ContentDisposition=headers["Content-Disposition"],
        ContentMD5=headers["Content-MD5"], Metadata={"x-cos-meta-sha256": digest(body)})
    # Do not return the full SDK response, which may include signed transport fields.
    return {field: str(response[field]) for field in ("ETag", "x-cos-request-id", "x-cos-version-id")
            if field in response}


def make_ticket(client, config, key, body, expires):
    headers = upload_headers(body)
    url = client.get_presigned_url(Bucket=config["bucket"], Key=key, Method="PUT", Expired=expires,
                                   Headers=dict(headers), SignHost=True)
    return {
        "schema_version": 1, "method": "PUT", "bucket": config["bucket"], "region": config["region"],
        "key": key, "put_url": url, "headers": headers, "sha256": digest(body), "bytes": len(body),
        "public_url": public_url(config, key),
        "expires_at": (utcnow() + timedelta(seconds=expires)).isoformat(),
    }


def use_ticket(ticket, config, body, requested_key=None):
    if not isinstance(ticket.get("key"), str) or not ticket["key"]:
        raise PublishError("invalid_ticket_key")
    key = choose_key(config, "report", ticket.get("key"))
    if requested_key and requested_key != key:
        raise PublishError("ticket_key_mismatch")
    try:
        expiry = datetime.fromisoformat(ticket["expires_at"])
        url = urllib.parse.urlsplit(ticket["put_url"])
    except Exception:
        raise PublishError("invalid_ticket") from None
    expected_host = f'{config["bucket"]}.cos.{config["region"]}.myqcloud.com'
    if (ticket.get("schema_version") != 1 or ticket.get("method") != "PUT"
            or ticket.get("bucket") != config["bucket"] or ticket.get("region") != config["region"]
            or ticket.get("sha256") != digest(body) or ticket.get("bytes") != len(body)
            or ticket.get("headers") != upload_headers(body)
            or ticket.get("public_url") != public_url(config, key)
            or expiry.tzinfo is None or expiry <= utcnow()
            or url.scheme != "https" or url.netloc != expected_host or url.fragment
            or urllib.parse.unquote(url.path) != "/" + key or not url.query):
        raise PublishError("ticket_target_content_or_expiry_mismatch")
    request = urllib.request.Request(ticket["put_url"], data=body, headers=ticket["headers"], method="PUT")
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        if response.status != 200:
            raise PublishError("ticket_upload_non_200")
        metadata = {name: response.headers[name] for name in ("ETag", "x-cos-request-id")
                    if name in response.headers}
    return key, metadata


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("html", help="UTF-8, preferably self-contained HTML document")
    result.add_argument("--slug", default="report")
    result.add_argument("--key", help="explicit .html key inside base_path; may overwrite that key")
    result.add_argument("--config", help="owner-only 0600 JSON; default ~/.config/mlab/cos.json")
    result.add_argument("--output-json", help="save credential-free result receipt")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="compute key/hash without SDK or network")
    modes.add_argument("--presign-put", metavar="PRIVATE_TICKET_JSON", help="write bounded PUT ticket, not upload")
    modes.add_argument("--use-ticket", metavar="PRIVATE_TICKET_JSON", help="upload using a ticket, without COS credentials")
    modes.add_argument("--verify-only", action="store_true", help="verify existing --key without uploading")
    result.add_argument("--expires", type=int, default=300, help="PUT ticket lifetime, 60–900 seconds")
    result.add_argument("--verify-attempts", type=int, default=3, help="1–3 public GET attempts")
    return result


def run(args):
    receipt = {"schema_version": 1, "created_at": utcnow().isoformat(),
               "success": False, "uploaded": False, "public_verified": False}
    phase = "prepare"
    try:
        if not 1 <= args.verify_attempts <= 3 or not 60 <= args.expires <= 900:
            raise PublishError("invalid_attempts_or_ticket_expiry")
        if args.verify_only and not args.key:
            raise PublishError("verify_only_requires_key")
        protected = {Path(args.html).expanduser().resolve(),
                     Path(args.config or "~/.config/mlab/cos.json").expanduser().resolve()}
        for path in (args.presign_put, args.use_ticket):
            if path:
                protected.add(Path(path).expanduser().resolve())
        if args.output_json and Path(args.output_json).expanduser().resolve() in protected:
            raise PublishError("receipt_cannot_replace_report_config_or_ticket")
        if args.presign_put and Path(args.presign_put).expanduser().resolve() in {
                Path(args.html).expanduser().resolve(),
                Path(args.config or "~/.config/mlab/cos.json").expanduser().resolve()}:
            raise PublishError("ticket_cannot_replace_report_or_config")
        needs_credentials = not (args.dry_run or args.verify_only or args.use_ticket)
        config = load_config(args.config, require_credentials=needs_credentials)
        body = read_html(args.html)
        key = choose_key(config, args.slug, args.key)
        ticket_data = None
        if args.use_ticket:
            # Use the ticket's stable key; dry-run never consumes the capability.
            ticket_data = read_private_json(args.use_ticket)
            ticket_key = ticket_data.get("key")
            if not isinstance(ticket_key, str) or not ticket_key:
                raise PublishError("invalid_ticket_key")
            key = choose_key(config, args.slug, ticket_key)
        receipt.update(bucket=config["bucket"], region=config["region"], key=key,
                       public_url=public_url(config, key), sha256=digest(body), bytes=len(body))
        if args.dry_run:
            receipt.update(dry_run=True, stage="dry_run")
            return receipt, 0
        if args.presign_put:
            phase = "presign"
            client = make_client(config)
            ticket = make_ticket(client, config, key, body, args.expires)
            write_json(args.presign_put, ticket, exclusive=True)
            receipt.update(stage="ticket_created", ticket_created=True,
                           ticket_file=str(Path(args.presign_put).expanduser()), expires_at=ticket["expires_at"])
            return receipt, 0
        if args.verify_only:
            receipt["uploaded"] = None  # This invocation has no evidence of how the object was uploaded.
        else:
            phase = "upload"
            if args.use_ticket:
                key, metadata = use_ticket(ticket_data, config, body, args.key)
            else:
                client = make_client(config)
                metadata = upload_sdk(client, config, key, body)
            receipt.update(uploaded=True, upload_response=metadata)
        phase = "public_verify"
        verification = verify_public(receipt["public_url"], digest(body), len(body), attempts=args.verify_attempts)
        receipt.update(public_verification=verification, public_verified=verification["verified"],
                       success=verification["verified"], stage="complete" if verification["verified"] else "public_verify_failed")
        return receipt, 0 if verification["verified"] else 3
    except PublishError as error:
        receipt.update(stage=phase + "_failed", error=str(error))
    except Exception as error:
        # Exception text/tracebacks may contain credentials, signature URLs, or request headers.
        receipt.update(stage=phase + "_failed", error=phase + "_failed", exception_type=type(error).__name__)
    return receipt, 2


def main():
    args = parser().parse_args()
    receipt, status = run(args)
    if args.output_json and receipt.get("error") != "receipt_cannot_replace_report_config_or_ticket":
        try:
            write_json(args.output_json, receipt)
        except Exception:
            print(json.dumps({"success": False, "uploaded": receipt["uploaded"],
                              "public_verified": receipt["public_verified"], "error": "receipt_write_failed"}))
            return 4
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
