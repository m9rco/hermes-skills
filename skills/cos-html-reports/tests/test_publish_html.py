"""Local-only contract tests: no COS credentials or remote service are used."""

from contextlib import redirect_stdout
from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


MODULE = Path(__file__).resolve().parents[1] / "scripts/publish_html.py"
SPEC = importlib.util.spec_from_file_location("publish_html", MODULE)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class FakeResponse:
    def __init__(self, body, content_type="text/html; charset=utf-8", disposition="inline"):
        self.body = body
        self.status = 200
        self.headers = {"Content-Type": content_type, "Content-Disposition": disposition}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.body = b"<!doctype html><html><body>Local test</body></html>"
        self.html = self.root / "report.html"
        self.html.write_bytes(self.body)
        self.config = self.root / "config.json"
        self.config.write_text("{}")
        self.config.chmod(0o600)

    def args(self, *extra):
        return publisher.parser().parse_args([str(self.html), "--config", str(self.config), *extra])

    def test_dry_run_and_constrained_unique_keys(self):
        receipt, status = publisher.run(self.args("--dry-run", "--slug", "XHS Report"))
        self.assertEqual(status, 0)
        self.assertFalse(receipt["uploaded"])
        self.assertFalse(receipt["success"])
        self.assertIn("/xhs-report-", receipt["key"])
        self.assertTrue(receipt["key"].endswith("/index.html"))
        self.assertNotEqual(receipt["key"], publisher.choose_key(publisher.DEFAULTS, "XHS Report"))
        for key in ("elsewhere/index.html", "mlab-work-1/../index.html", "mlab-work-1/%2e%2e/index.html"):
            with self.assertRaises(publisher.PublishError):
                publisher.choose_key(publisher.DEFAULTS, "report", key)

    def test_config_rejects_unsafe_permissions_and_symlink(self):
        self.config.chmod(0o644)
        with self.assertRaises(publisher.PublishError):
            publisher.load_config(str(self.config))
        self.config.chmod(0o600)
        link = self.root / "link.json"
        link.symlink_to(self.config)
        with self.assertRaises(publisher.PublishError):
            publisher.load_config(str(link))

    def test_sdk_upload_has_html_headers_md5_and_no_acl(self):
        client = Mock()
        client.put_object.return_value = {"ETag": "object-etag", "Authorization": "MUST NOT RETURN"}
        response = publisher.upload_sdk(client, publisher.DEFAULTS, "mlab-work-1/test.html", self.body)
        kwargs = client.put_object.call_args.kwargs
        self.assertEqual(kwargs["ContentType"], "text/html; charset=utf-8")
        self.assertEqual(kwargs["ContentDisposition"], "inline")
        self.assertEqual(kwargs["Body"], self.body)
        self.assertNotIn("ACL", kwargs)
        self.assertEqual(kwargs["Metadata"]["x-cos-meta-sha256"], publisher.digest(self.body))
        self.assertEqual(response, {"ETag": "object-etag"})

    def test_public_requires_200_body_and_renderable_headers(self):
        opener = Mock()
        with patch.object(publisher.urllib.request, "build_opener", return_value=opener):
            opener.open.return_value = FakeResponse(self.body)
            good = publisher.verify_public("https://example.com/test.html", publisher.digest(self.body), len(self.body), attempts=1)
            self.assertTrue(good["verified"])
            opener.open.return_value = FakeResponse(b"different")
            self.assertFalse(publisher.verify_public("https://example.com/test.html", publisher.digest(self.body), len(self.body), attempts=1)["verified"])
            opener.open.return_value = FakeResponse(self.body, disposition="attachment")
            self.assertFalse(publisher.verify_public("https://example.com/test.html", publisher.digest(self.body), len(self.body), attempts=1)["verified"])

    def test_uploaded_but_public_failure_and_no_raw_exception(self):
        with patch.object(publisher, "load_config", return_value=publisher.DEFAULTS), \
                patch.object(publisher, "make_client", return_value=Mock()), \
                patch.object(publisher, "upload_sdk", return_value={"ETag": "etag"}), \
                patch.object(publisher, "verify_public", return_value={"verified": False, "http_status": 403}):
            receipt, status = publisher.run(self.args())
            self.assertEqual(status, 3)
            self.assertTrue(receipt["uploaded"])
            self.assertFalse(receipt["public_verified"])
        with patch.object(publisher, "load_config", return_value=publisher.DEFAULTS), \
                patch.object(publisher, "make_client", side_effect=RuntimeError("SECRET_OR_SIGNATURE")):
            receipt, status = publisher.run(self.args())
            self.assertEqual(status, 2)
            self.assertNotIn("SECRET_OR_SIGNATURE", json.dumps(receipt))

    def test_ticket_fixed_content_scope_private_file_and_mismatch_rejected(self):
        client = Mock()
        key = "mlab-work-1/reports/test/index.html"
        client.get_presigned_url.return_value = (
            "https://t-gz-1252130512.cos.ap-guangzhou.myqcloud.com/" + key + "?q-signature=LOCAL_TEST")
        ticket = publisher.make_ticket(client, publisher.DEFAULTS, key, self.body, 300)
        self.assertEqual(client.get_presigned_url.call_args.kwargs["Method"], "PUT")
        self.assertTrue(client.get_presigned_url.call_args.kwargs["SignHost"])
        self.assertEqual(client.get_presigned_url.call_args.kwargs["Headers"], publisher.upload_headers(self.body))
        client.get_presigned_url.call_args.kwargs["Headers"]["Host"] = "sdk-added-host"
        self.assertEqual(ticket["headers"], publisher.upload_headers(self.body))
        target = self.root / "ticket.json"
        publisher.write_json(target, ticket, exclusive=True)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(publisher.PublishError):
            publisher.use_ticket(publisher.read_private_json(target), publisher.DEFAULTS, self.body + b"different")
        ticket["expires_at"] = (publisher.utcnow() - timedelta(seconds=1)).isoformat()
        target.write_text(json.dumps(ticket))
        with self.assertRaises(publisher.PublishError):
            publisher.use_ticket(publisher.read_private_json(target), publisher.DEFAULTS, self.body)

    def test_receipt_cannot_replace_config_or_html(self):
        for target in (self.config, self.html):
            receipt, status = publisher.run(self.args("--dry-run", "--output-json", str(target)))
            self.assertEqual(status, 2)
            self.assertEqual(receipt["error"], "receipt_cannot_replace_report_config_or_ticket")
        self.assertEqual(self.config.read_text(), "{}")

    def test_ticket_receipt_uses_same_single_read_key(self):
        key = "mlab-work-1/reports/test/index.html"
        ticket = {"key": key}
        target = self.root / "single-ticket.json"
        with patch.object(publisher, "load_config", return_value=publisher.DEFAULTS), \
                patch.object(publisher, "read_private_json", return_value=ticket) as read_ticket, \
                patch.object(publisher, "use_ticket", return_value=(key, {})) as upload, \
                patch.object(publisher, "verify_public", return_value={"verified": True}):
            receipt, status = publisher.run(self.args("--use-ticket", str(target)))
            self.assertEqual(status, 0)
            self.assertEqual(read_ticket.call_count, 1)
            self.assertIs(upload.call_args.args[0], ticket)
            self.assertEqual(receipt["key"], key)
            self.assertTrue(receipt["public_url"].endswith(key))
        self.assertEqual(self.html.read_bytes(), self.body)
        argv = [str(MODULE), str(self.html), "--config", str(self.config), "--dry-run",
                "--output-json", str(self.config)]
        with patch.object(publisher.sys, "argv", argv), redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.main(), 2)
        self.assertEqual(self.config.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
