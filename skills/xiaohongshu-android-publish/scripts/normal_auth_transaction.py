"""One-process, secret-silent normal-auth transaction; no device implementation.

The existing caller owns authorization, fresh normal-UI checks and worker guards.
Pass its existing normal input, read-only verification and restoration functions
as callbacks. This module never runs ADB, retries input, changes settings, or
prints/persists decrypted text or an extracted sequence. Verification must return
an actual bool. input_attempted means the callback was invoked, not an unlock.

decrypt_envelope returns the ORIGINAL HUMAN STRING. It is not a JSON adapter and
must never be json.loads'ed or indexed using s/sequence by this transaction.
Private/cipher deletion and restore are attempted in finally, including failure.
restored means the restoration callback returned normally; that callback is
responsible for checking any real restoration. Clearing local references does
not make a secure-memory-erasure claim.

There is no real credential CLI. --self-test runs only the separately shipped
dummy test file tests/test_normal_auth_transaction.py.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

if __package__:
    from .normal_auth_envelope import decrypt_envelope
else:
    from normal_auth_envelope import decrypt_envelope


class SequenceInstructionError(ValueError):
    """The original natural-language instruction is absent or ambiguous."""


class VerificationResultError(TypeError):
    """Verification did not return a literal bool."""


class CallbackContractError(TypeError):
    """A required callback is not callable."""


def _extract_sequence(human_text: str) -> str:
    if not isinstance(human_text, str) or "划线" not in human_text:
        raise SequenceInstructionError()
    if human_text.lstrip().startswith(("{", "[", '"')):
        # Explicitly reject old JSON/sequence wrappers, even if their strings
        # contain an otherwise valid sequence. No adapter/JSON fallback.
        raise SequenceInstructionError()
    candidates = re.findall(r"(?<![A-Za-z0-9])[0-9]{4,9}(?![A-Za-z0-9])", human_text)
    if len(candidates) != 1:
        raise SequenceInstructionError()
    sequence = candidates[0]
    if "0" in sequence or len(set(sequence)) != len(sequence):
        raise SequenceInstructionError()
    return sequence


def transact(
    envelope_path,
    private_path,
    *,
    expected_key_sha256,
    expected_nonce,
    expected_task,
    normal_input_callback,
    verify_callback,
    restore_callback,
):
    """Decrypt once, pass one in-memory sequence once, verify, finally clean up.

    Only fixed stages, exception CLASS NAMES and booleans leave the function.
    cleanup.error_classes records finally failures, including restoration errors.
    The primary operation's exception class takes precedence over finally errors.
    No exception messages, args, reprs, locals or callback return objects are kept.
    """
    result = {
        "stage": "validate_callbacks",
        "error_class": None,
        "input_attempted": False,
        "keyguard_cleared": None,
        "cleanup": {"private_deleted": False, "cipher_deleted": False, "error_classes": []},
        "restored": False,
    }
    envelope = private_bytes = human_text = sequence = verification = None
    try:
        if not all(callable(callback) for callback in (normal_input_callback, verify_callback, restore_callback)):
            raise CallbackContractError()
        result["stage"] = "load_envelope"
        # JSON is parsed ONLY for the public encrypted envelope, never human_text.
        with Path(envelope_path).open("r", encoding="utf-8") as stream:
            envelope = json.load(stream)
        result["stage"] = "load_private"
        private_bytes = Path(private_path).read_bytes()
        result["stage"] = "decrypt"
        human_text = decrypt_envelope(
            envelope,
            private_bytes,
            expected_key_sha256=expected_key_sha256,
            expected_nonce=expected_nonce,
            expected_task=expected_task,
        )
        result["stage"] = "extract_sequence"
        sequence = _extract_sequence(human_text)
        result["stage"] = "normal_input"
        result["input_attempted"] = True
        normal_input_callback(sequence)
        result["stage"] = "verify"
        verification = verify_callback()
        if type(verification) is not bool:
            raise VerificationResultError()
        result["keyguard_cleared"] = verification
        result["stage"] = "verified" if verification else "unverified"
    except BaseException as exc:
        # A callback may terminate with SystemExit/KeyboardInterrupt. Preserve
        # only its class; never let a credential-bearing exit message escape.
        result["error_class"] = type(exc).__name__
    finally:
        # No plaintext is serialized. Drop references before invoking restoration.
        envelope = private_bytes = human_text = sequence = verification = None
        for field, path in (("private_deleted", private_path), ("cipher_deleted", envelope_path)):
            try:
                Path(path).unlink(missing_ok=True)
                result["cleanup"][field] = True
            except BaseException as exc:
                error_class = type(exc).__name__
                result["cleanup"]["error_classes"].append(error_class)
                if result["error_class"] is None:
                    result["stage"], result["error_class"] = "cleanup", error_class
        try:
            restore_callback()
            result["restored"] = True
        except BaseException as exc:
            error_class = type(exc).__name__
            result["cleanup"]["error_classes"].append(error_class)
            if result["error_class"] is None:
                result["stage"], result["error_class"] = "restore", error_class
    return result


if __name__ == "__main__":
    import sys
    import unittest

    if sys.argv[1:] != ["--self-test"]:
        raise SystemExit("Only --self-test is supported; real use requires in-process callbacks.")
    directory = Path(__file__).resolve().parent / "tests"
    suite = unittest.defaultTestLoader.discover(str(directory), pattern="test_normal_auth_transaction.py")
    if suite.countTestCases() == 0:
        raise SystemExit("Dummy self-test suite missing; refusing a zero-test success.")
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
