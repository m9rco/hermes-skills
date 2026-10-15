"""Synthetic-only authentication transaction tests; no real credentials or UI."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import normal_auth_transaction as transaction


class EnvelopeError(Exception):
    """Synthetic stand-in for a decoder failure, with no real envelope data."""


class NormalAuthTransactionTests(unittest.TestCase):
    # These values are deliberately public synthetic fixtures, never credentials.
    DUMMY_SEQUENCE = "12345"
    DUMMY_HUMAN = "DUMMY synthetic only：请按划线顺序输入 12345。"
    RESULT_FIELDS = {
        "stage", "error_class", "input_attempted", "keyguard_cleared", "cleanup", "restored"
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cipher_path = self.root / "dummy-envelope.json"
        self.private_path = self.root / "dummy-private.pem"
        self._write_dummy_inputs()
        self.input_callback = Mock(return_value=False)
        self.verify_callback = Mock(return_value=True)
        self.restore_callback = Mock(return_value=None)
        self.decrypt_patcher = patch.object(
            transaction, "decrypt_envelope", return_value=self.DUMMY_HUMAN
        )
        self.decrypt = self.decrypt_patcher.start()
        self.addCleanup(self.decrypt_patcher.stop)

    def _write_dummy_inputs(self):
        self.cipher_path.write_text('{"dummy_ciphertext": true}\n', encoding="utf-8")
        self.private_path.write_bytes(b"DUMMY synthetic private bytes only\n")

    def _run(self, *, expected_key_sha256="0" * 64):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = transaction.transact(
                self.cipher_path,
                self.private_path,
                expected_key_sha256=expected_key_sha256,
                expected_nonce="DUMMY_SYNTHETIC_NONCE",
                expected_task="DUMMY_SYNTHETIC_TASK",
                normal_input_callback=self.input_callback,
                verify_callback=self.verify_callback,
                restore_callback=self.restore_callback,
            )
        self.assertEqual(set(result), self.RESULT_FIELDS)
        self.assertEqual(
            set(result["cleanup"]), {"private_deleted", "cipher_deleted", "error_classes"}
        )
        for name in ("input_attempted", "restored"):
            self.assertIs(type(result[name]), bool)
        self.assertTrue(
            result["keyguard_cleared"] is None or type(result["keyguard_cleared"]) is bool
        )
        self.assertIs(type(result["cleanup"]["private_deleted"]), bool)
        self.assertIs(type(result["cleanup"]["cipher_deleted"]), bool)
        self.assertTrue(result["cleanup"]["private_deleted"])
        self.assertTrue(result["cleanup"]["cipher_deleted"])
        self.assertFalse(self.private_path.exists())
        self.assertFalse(self.cipher_path.exists())
        self.assertIsInstance(result["cleanup"]["error_classes"], list)
        self.assertTrue(all(type(value) is str for value in result["cleanup"]["error_classes"]))
        serialized = json.dumps(result, ensure_ascii=False)
        for output in (serialized, stdout.getvalue(), stderr.getvalue()):
            self.assertNotIn(self.DUMMY_SEQUENCE, output)
            self.assertNotIn(self.DUMMY_HUMAN, output)
            if type(self.decrypt.return_value) is str:
                self.assertNotIn(self.decrypt.return_value, output)
            self.assertNotIn("DUMMY_SENSITIVE", output)
            self.assertNotIn("DUMMY-private-message", output)
        self.restore_callback.assert_called_once_with()
        self.decrypt.assert_called_once()
        return result

    def test_happy_path_decrypts_and_inputs_once_without_exposing_plaintext(self):
        # This ordinary human text is deliberately not a JSON document.
        result = self._run()
        self.assertEqual(result["stage"], "verified")
        self.assertIsNone(result["error_class"])
        self.assertTrue(result["input_attempted"])
        self.assertTrue(result["keyguard_cleared"])
        self.assertTrue(result["restored"])
        self.assertEqual(result["cleanup"]["error_classes"], [])
        self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
        self.verify_callback.assert_called_once_with()

    def test_real_test_only_rsa_envelope_flows_through_decoder_once(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        # A newly generated test-only key; no device or production material is used.
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        key_digest = hashlib.sha256(public_pem).hexdigest()
        self.private_path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        inner_bytes = json.dumps(
            {
                "t": "DUMMY_SYNTHETIC_TASK",
                "n": "DUMMY_SYNTHETIC_NONCE",
                "s": self.DUMMY_HUMAN,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = public_key.encrypt(
            inner_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        self.cipher_path.write_text(
            json.dumps(
                {
                    "ciphertext_hex": ciphertext.hex(),
                    "algorithm": "RSA-OAEP-SHA256",
                    "mgf1": "SHA256",
                    "label": None,
                    "key_sha256": key_digest,
                    "nonce": "DUMMY_SYNTHETIC_NONCE",
                }
            ),
            encoding="utf-8",
        )
        self.decrypt_patcher.stop()
        real_decrypt = transaction.decrypt_envelope

        def decode_actual_dummy_envelope(*args, **kwargs):
            human_text = real_decrypt(*args, **kwargs)
            self.assertIs(type(human_text), str)
            self.assertEqual(human_text, self.DUMMY_HUMAN)
            return human_text

        with patch.object(
            transaction, "decrypt_envelope", side_effect=decode_actual_dummy_envelope
        ) as decrypt_once:
            self.decrypt = decrypt_once
            result = self._run(expected_key_sha256=key_digest)
        self.assertEqual(result["stage"], "verified")
        self.assertTrue(result["keyguard_cleared"])
        self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
        self.assertIs(type(self.input_callback.call_args.args[0]), str)
        self.verify_callback.assert_called_once_with()

    def test_decrypt_failure_never_inputs_and_still_cleans_up(self):
        self.decrypt.side_effect = EnvelopeError("DUMMY_SENSITIVE decoder failure 12345")
        result = self._run()
        self.assertEqual(result["stage"], "decrypt")
        self.assertEqual(result["error_class"], "EnvelopeError")
        self.assertFalse(result["input_attempted"])
        self.assertIsNone(result["keyguard_cleared"])
        self.assertTrue(result["restored"])
        self.input_callback.assert_not_called()
        self.verify_callback.assert_not_called()

    def test_normal_input_failure_is_not_retried_or_verified(self):
        for error_type in (RuntimeError, SystemExit):
            with self.subTest(error_class=error_type.__name__):
                self._write_dummy_inputs()
                self.decrypt.reset_mock()
                self.input_callback.reset_mock()
                self.verify_callback.reset_mock()
                self.restore_callback.reset_mock()
                self.input_callback.side_effect = error_type("DUMMY-private-message")
                result = self._run()
                self.assertEqual(result["stage"], "normal_input")
                self.assertEqual(result["error_class"], error_type.__name__)
                self.assertTrue(result["input_attempted"])
                self.assertIsNone(result["keyguard_cleared"])
                self.assertTrue(result["restored"])
                self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
                self.verify_callback.assert_not_called()

    def test_false_verification_is_unverified_regardless_of_input_return_value(self):
        self.input_callback.return_value = True
        self.verify_callback.return_value = False
        result = self._run()
        self.assertEqual(result["stage"], "unverified")
        self.assertIsNone(result["error_class"])
        self.assertTrue(result["input_attempted"])
        self.assertFalse(result["keyguard_cleared"])
        self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
        self.verify_callback.assert_called_once_with()

    def test_verify_exception_reports_only_its_class(self):
        self.verify_callback.side_effect = LookupError("DUMMY_SENSITIVE verify failure 12345")
        result = self._run()
        self.assertEqual(result["stage"], "verify")
        self.assertEqual(result["error_class"], "LookupError")
        self.assertIsNone(result["keyguard_cleared"])
        self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
        self.verify_callback.assert_called_once_with()

    def test_restore_failure_reports_only_its_class(self):
        self.restore_callback.side_effect = OSError("DUMMY_SENSITIVE restore failure 12345")
        result = self._run()
        self.assertEqual(result["stage"], "restore")
        self.assertEqual(result["error_class"], "OSError")
        self.assertFalse(result["restored"])
        self.assertIn("OSError", result["cleanup"]["error_classes"])

    def test_primary_error_survives_a_restore_error(self):
        self.input_callback.side_effect = RuntimeError("DUMMY_SENSITIVE primary 12345")
        self.restore_callback.side_effect = LookupError("DUMMY_SENSITIVE restore 12345")
        result = self._run()
        self.assertEqual(result["stage"], "normal_input")
        self.assertEqual(result["error_class"], "RuntimeError")
        self.assertTrue(result["input_attempted"])
        self.assertFalse(result["restored"])
        self.assertIn("LookupError", result["cleanup"]["error_classes"])
        self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
        self.verify_callback.assert_not_called()

    def test_invalid_or_ambiguous_sequences_are_rejected_before_input(self):
        invalid_human_texts = (
            "DUMMY synthetic only：普通输入 12345。",  # Required literal absent.
            "DUMMY synthetic only：划线 12345 或 67891。",  # Two candidates.
            "DUMMY synthetic only：划线 12341。",  # Repeated digit.
            "DUMMY synthetic only：划线 12340。",  # Zero is forbidden.
            "DUMMY synthetic only：划线 1234567891。",  # Longer than nine.
            "DUMMY synthetic only：划线 123。",  # Shorter than four.
            "DUMMY synthetic only：划线 12 345。",  # Not contiguous.
            "DUMMY synthetic only：划线 １２３４５。",  # Not ASCII.
        )
        for human_text in invalid_human_texts:
            with self.subTest(case=invalid_human_texts.index(human_text)):
                self._write_dummy_inputs()
                self.decrypt.reset_mock()
                self.decrypt.return_value = human_text
                self.restore_callback.reset_mock()
                result = self._run()
                self.assertEqual(result["stage"], "extract_sequence")
                self.assertIsInstance(result["error_class"], str)
                self.assertFalse(result["input_attempted"])
                self.assertIsNone(result["keyguard_cleared"])
                self.assertTrue(result["restored"])
                self.input_callback.assert_not_called()
                self.verify_callback.assert_not_called()

    def test_structured_wrappers_are_not_accepted_as_human_instructions(self):
        wrappers = (
            " \n" + json.dumps(
                {
                    "kind": "DUMMY synthetic only",
                    "numbering": "DUMMY synthetic only",
                    "sequence": self.DUMMY_SEQUENCE,
                    "message": "划线 DUMMY synthetic only",
                },
                ensure_ascii=False,
            ),
            json.dumps(["划线 DUMMY synthetic only", self.DUMMY_SEQUENCE], ensure_ascii=False),
            json.dumps(self.DUMMY_HUMAN, ensure_ascii=False),
        )
        for index, human_text in enumerate(wrappers):
            with self.subTest(case=index):
                self._write_dummy_inputs()
                self.decrypt.reset_mock()
                self.decrypt.return_value = human_text
                self.restore_callback.reset_mock()
                result = self._run()
                self.assertEqual(result["stage"], "extract_sequence")
                self.assertIsInstance(result["error_class"], str)
                self.assertFalse(result["input_attempted"])
                self.assertIsNone(result["keyguard_cleared"])
                self.input_callback.assert_not_called()
                self.verify_callback.assert_not_called()

    def test_verification_must_return_an_actual_bool(self):
        for index, invalid_value in enumerate((1, 0, None, "true", [], {})):
            with self.subTest(case=index):
                self._write_dummy_inputs()
                self.decrypt.reset_mock()
                self.input_callback.reset_mock()
                self.verify_callback.reset_mock()
                self.verify_callback.return_value = invalid_value
                self.restore_callback.reset_mock()
                result = self._run()
                self.assertEqual(result["stage"], "verify")
                self.assertIsInstance(result["error_class"], str)
                self.assertIsNone(result["keyguard_cleared"])
                self.assertTrue(result["restored"])
                self.input_callback.assert_called_once_with(self.DUMMY_SEQUENCE)
                self.verify_callback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
