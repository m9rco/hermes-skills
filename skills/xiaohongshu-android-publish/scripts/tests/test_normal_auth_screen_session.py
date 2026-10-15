"""Synthetic-only display guard tests; no ADB, device, auth, or secrets are used."""

import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import normal_auth_screen_session as session


class ScreenSessionTests(unittest.TestCase):
    VERIFIED_AUTH = {
        "stage": "verified",
        "error_class": None,
        "input_attempted": True,
        "keyguard_cleared": True,
        "cleanup": {"private_deleted": True, "cipher_deleted": True, "error_classes": []},
        "restored": True,
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.adb_path = self.root / "synthetic-adb-never-executed"
        self.adb_path.write_text("DUMMY metadata fixture only\n", encoding="utf-8")
        self.serial = "SYNTHETIC-SERIAL"
        self.state_path = self.root / "display-guard.json"
        self.original_value = "30000"
        self.current_value = self.original_value
        self.guard_value = "1800000"
        self.events = []
        self.fail_guard_put_once = False
        self.override_guard_readback_once = False
        self.fail_restore_put = False
        self.real_adb = session._adb
        self.real_start_watchdog = session._start_watchdog
        self.auth_patcher = patch.object(session, "_auth_transact", return_value=copy.deepcopy(self.VERIFIED_AUTH))
        self.adb_patcher = patch.object(session, "_adb", side_effect=self._fake_adb)
        self.watchdog_patcher = patch.object(session, "_start_watchdog", side_effect=self._ready_watchdog)
        self.auth = self.auth_patcher.start()
        self.adb = self.adb_patcher.start()
        self.watchdog = self.watchdog_patcher.start()
        self.addCleanup(self.auth_patcher.stop)
        self.addCleanup(self.adb_patcher.stop)
        self.addCleanup(self.watchdog_patcher.stop)

    def _fake_adb(self, adb_path, serial, *settings_args):
        self.assertEqual(str(adb_path), str(self.adb_path))
        self.assertEqual(serial, self.serial)
        operation = settings_args[0]
        self.assertIn(operation, {"get", "put", "delete"})
        self.assertEqual(settings_args[1:3], ("system", "screen_off_timeout"))
        self.events.append((operation, *settings_args[3:]))
        if operation == "get":
            self.assertEqual(len(settings_args), 3)
            if self.current_value == self.guard_value and self.override_guard_readback_once:
                self.override_guard_readback_once = False
                return "777"
            return self.current_value
        if operation == "delete":
            self.assertEqual(len(settings_args), 3)
            self.current_value = "null"
            return ""
        self.assertEqual(len(settings_args), 4)
        value = str(settings_args[3])
        if value == self.original_value and self.fail_restore_put:
            raise OSError("DUMMY display restoration failure")
        self.current_value = value
        if value == self.guard_value and self.fail_guard_put_once:
            self.fail_guard_put_once = False
            # Simulate an uncertain command result after the setting changed.
            raise OSError("DUMMY display write failure")
        return ""

    def _ready_watchdog(self, state_path):
        path = Path(state_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update({"phase": "armed", "watchdog_ready": True, "watchdog_pid": 1234})
        path.write_text(json.dumps(data), encoding="utf-8")
        self.events.append(("watchdog_ready",))
        return SimpleNamespace(pid=1234, poll=lambda: None)

    def _activate(self, duration=1800):
        return session.transact_with_screen_guard(
            str(self.adb_path),
            self.serial,
            str(self.state_path),
            duration_seconds=duration,
            dummy_marker="SYNTHETIC_TEST_ONLY",
        )

    def _assert_auth_once(self):
        self.auth.assert_called_once_with(dummy_marker="SYNTHETIC_TEST_ONLY")

    def test_only_strict_verified_clean_and_restored_auth_can_activate(self):
        invalid_results = []
        for name, value in (
            ("stage", "unverified"), ("input_attempted", False),
            ("keyguard_cleared", False), ("restored", False),
            ("error_class", "RuntimeError"), ("input_attempted", 1),
            ("keyguard_cleared", 1), ("restored", 1),
        ):
            item = copy.deepcopy(self.VERIFIED_AUTH)
            item[name] = value
            invalid_results.append(item)
        for name, value in (
            ("private_deleted", False), ("cipher_deleted", False),
            ("error_classes", ["OSError"]), ("private_deleted", 1),
        ):
            item = copy.deepcopy(self.VERIFIED_AUTH)
            item["cleanup"][name] = value
            invalid_results.append(item)
        for index, auth_result in enumerate(invalid_results):
            with self.subTest(case=index):
                self.auth.reset_mock()
                self.adb.reset_mock()
                self.watchdog.reset_mock()
                self.auth.return_value = auth_result
                result = self._activate()
                self._assert_auth_once()
                self.assertEqual(result["auth"], auth_result)
                self.assertIs(result["guard"]["active"], False)
                self.adb.assert_not_called()
                self.watchdog.assert_not_called()

    def test_activation_waits_for_watchdog_and_readback_and_uses_private_state(self):
        result = self._activate()
        self._assert_auth_once()
        self.assertEqual(
            self.events,
            [("get",), ("watchdog_ready",), ("put", self.guard_value), ("get",)],
        )
        self.assertEqual(result["auth"], self.VERIFIED_AUTH)
        self.assertIs(result["guard"]["active"], True)
        self.assertIs(result["guard"]["restore_pending"], True)
        self.assertIs(result["guard"]["restored"], False)
        self.assertIsInstance(result["guard"]["deadline"], str)
        self.assertEqual(Path(result["guard"]["state_path"]), self.state_path)
        self.assertEqual(stat.S_IMODE(self.state_path.stat().st_mode), 0o600)
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "active")
        self.assertIs(data["watchdog_ready"], True)
        self.assertNotIn("auth", data)
        for forbidden in ("SYNTHETIC_TEST_ONLY", "private_path", "ciphertext", "sequence"):
            self.assertNotIn(forbidden, json.dumps(data))

    def test_watchdog_setup_failure_never_puts_guard_and_confirms_original(self):
        self.watchdog.side_effect = OSError("DUMMY watchdog setup failure")
        result = self._activate()
        self._assert_auth_once()
        self.assertIs(result["guard"]["active"], False)
        self.assertIs(result["guard"]["restored"], True)
        self.assertIs(result["guard"]["restore_pending"], False)
        self.assertFalse(any(event[0] in {"put", "delete"} for event in self.events))
        self.assertGreaterEqual(self.events.count(("get",)), 2)
        self.assertEqual(self.current_value, self.original_value)

    def test_guard_write_or_readback_failure_rolls_back_without_retrying_auth(self):
        for failure in ("put", "readback"):
            with self.subTest(failure=failure):
                self.events.clear()
                self.current_value = self.original_value
                self.state_path = self.root / ("failure-" + failure + ".json")
                self.auth.reset_mock()
                self.fail_guard_put_once = failure == "put"
                self.override_guard_readback_once = failure == "readback"
                result = self._activate()
                self._assert_auth_once()
                self.assertIs(result["guard"]["active"], False)
                self.assertIs(result["guard"]["restored"], True)
                self.assertIs(result["guard"]["restore_pending"], False)
                self.assertEqual(self.current_value, self.original_value)
                self.assertIn(("put", self.guard_value), self.events)
                self.assertIn(("put", self.original_value), self.events)
                self.assertEqual(self.events[-1], ("get",))

    def test_null_original_is_restored_with_delete_and_verified(self):
        self.original_value = self.current_value = "null"
        self._activate()
        self.assertIsNone(json.loads(self.state_path.read_text(encoding="utf-8"))["original_value"])
        self.events.clear()
        result = session.restore_now(str(self.state_path))
        self.assertEqual(self.events, [("get",), ("delete",), ("get",)])
        self.assertEqual(self.current_value, "null")
        self.assertIs(result["restored"], True)
        self.assertIs(result["restore_pending"], False)
        self._assert_auth_once()

    def test_restore_does_not_write_when_original_value_is_already_present(self):
        self._activate()
        self.current_value = self.original_value
        self.events.clear()
        result = session.restore_now(str(self.state_path))
        self.assertTrue(self.events)
        self.assertTrue(all(event[0] == "get" for event in self.events))
        self.assertIs(result["restored"], True)
        self.assertIs(result["restore_pending"], False)
        self._assert_auth_once()

    def test_failed_restore_remains_pending_and_never_claims_restored(self):
        self._activate()
        self.fail_restore_put = True
        result = session.restore_now(str(self.state_path))
        self.assertIs(result["restored"], False)
        self.assertIs(result["restore_pending"], True)
        self.assertIsInstance(result["error_class"], str)
        self.assertEqual(self.current_value, self.guard_value)
        self._assert_auth_once()

    def test_existing_pending_guard_is_preserved_before_auth_or_adb(self):
        self._activate()
        original_state = self.state_path.read_bytes()
        self.events.clear()
        self.auth.reset_mock()
        self.adb.reset_mock()
        self.watchdog.reset_mock()

        guard = session.start_screen_guard(
            str(self.adb_path), self.serial, str(self.state_path), duration_seconds=1800
        )
        self.assertIs(guard["active"], True)
        self.assertIs(guard["restore_pending"], True)
        self.assertEqual(guard["error_class"], "GuardAlreadyActive")
        self.assertEqual(self.state_path.read_bytes(), original_state)
        self.auth.assert_not_called()
        self.adb.assert_not_called()
        self.watchdog.assert_not_called()

        result = self._activate()
        self.assertIsNone(result["auth"])
        self.assertIs(result["guard"]["active"], True)
        self.assertIs(result["guard"]["restore_pending"], True)
        self.assertEqual(result["guard"]["error_class"], "GuardAlreadyActive")
        self.assertEqual(self.state_path.read_bytes(), original_state)
        self.assertEqual(self.events, [])
        self.auth.assert_not_called()
        self.adb.assert_not_called()
        self.watchdog.assert_not_called()

    def test_watchdog_handshake_requires_matching_armed_live_process(self):
        self._activate()
        initial_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for case in ("exited", "wrong_pid", "ready"):
            with self.subTest(case=case):
                state_data = copy.deepcopy(initial_state)
                state_data.update(
                    {"phase": "armed", "watchdog_ready": True, "watchdog_pid": 1234 if case == "wrong_pid" else 4321}
                )
                self.state_path.write_text(json.dumps(state_data), encoding="utf-8")
                process = SimpleNamespace(pid=4321, poll=Mock(return_value=0 if case == "exited" else None))
                clock_values = [0.0, 0.1, 5.0]
                with (
                    patch.object(session.subprocess, "Popen", return_value=process) as popen,
                    patch.object(session.time, "monotonic", side_effect=clock_values),
                    patch.object(session.time, "sleep") as sleep,
                    patch.dict(session.os.environ, {"PATH": "/DUMMY/bin", "DUMMY_AUTH_SECRET": "synthetic-only"}, clear=True),
                ):
                    if case == "ready":
                        self.assertIs(self.real_start_watchdog(self.state_path), process)
                    else:
                        with self.assertRaises(session.WatchdogSetupError):
                            self.real_start_watchdog(self.state_path)
                popen.assert_called_once()
                args, kwargs = popen.call_args
                self.assertEqual(args[0][-2:], ["--watchdog", str(self.state_path)])
                self.assertNotIn("DUMMY_AUTH_SECRET", kwargs["env"])
                self.assertIs(kwargs.get("shell", False), False)
                if case == "wrong_pid":
                    sleep.assert_called()
                elif case == "exited":
                    sleep.assert_not_called()

    def test_invalid_duration_fails_before_auth_or_display_changes(self):
        for duration in (0, 29, 1801, -1, True, "1800"):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    self._activate(duration)
                self.auth.assert_not_called()
                self.adb.assert_not_called()
                self.watchdog.assert_not_called()

    def test_adb_helper_uses_only_fixed_settings_command_without_host_shell(self):
        completed = SimpleNamespace(returncode=0, stdout=b"30000\n", stderr=b"")
        with patch.object(session.subprocess, "run", return_value=completed) as run:
            value = self.real_adb(
                str(self.adb_path), self.serial, "get", "system", "screen_off_timeout"
            )
        self.assertEqual(value, "30000")
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [str(self.adb_path), "-s", self.serial, "shell", "settings", "get", "system", "screen_off_timeout"],
        )
        self.assertIs(kwargs.get("shell", False), False)
        self.assertIsNone(kwargs.get("input"))
        self.assertNotIn("SYNTHETIC_TEST_ONLY", repr(run.call_args))


if __name__ == "__main__":
    unittest.main()
