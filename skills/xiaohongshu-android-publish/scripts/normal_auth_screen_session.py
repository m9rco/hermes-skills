"""Bounded screen_off_timeout guard, after existing verified normal authentication.

No authentication/lock/browser/permission settings are changed here. Only
settings {get,put,delete} system screen_off_timeout is allowed. The caller owns
fresh UI/account/worker guards. start_screen_guard is also available when the
caller has just verified an already-unlocked matching account without re-auth.

The detached watchdog receives ONLY a 0600 display-metadata state path. It is
armed and independently alive before any timeout change. It begins restoration
early enough to reserve bounded ADB call time before the duration deadline.
Unreachable devices/OS failure cannot be called restored: restore_pending stays
true until actual original-value readback. Publisher termination must call
restore_now (or --restore-now) immediately, rather than wait for the watchdog.

CLI accepts only dummy self-tests or credential-free restore/watchdog commands.
Real authentication is exclusively the in-process transact_with_screen_guard API.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

ADB_TIMEOUT = 5
RESTORE_RESERVE = 15
STARTUP_TIMEOUT = 4
SETTING = "screen_off_timeout"


class ScreenGuardError(RuntimeError):
    pass


class AdbCommandError(ScreenGuardError):
    pass


class GuardReadbackError(ScreenGuardError):
    pass


class WatchdogSetupError(ScreenGuardError):
    pass


class GuardAlreadyActive(ScreenGuardError):
    pass


def _auth_transact(**kwargs):
    # Restore/watchdog mode never imports the decoder or touches auth material.
    if __package__:
        from .normal_auth_transaction import transact
    else:
        from normal_auth_transaction import transact
    return transact(**kwargs)


def _identity(adb_path, serial, duration_seconds):
    if type(duration_seconds) is not int or not 30 <= duration_seconds <= 1800:
        raise ValueError("duration_seconds must be an integer from 30 to 1800")
    if not isinstance(adb_path, (str, os.PathLike)) or not os.fspath(adb_path):
        raise ValueError("adb_path is required")
    if not isinstance(serial, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", serial) is None:
        raise ValueError("invalid serial")
    return str(Path(adb_path).expanduser().absolute())


def _adb(adb_path, serial, *args):
    valid = args in (("get", "system", SETTING), ("delete", "system", SETTING))
    valid = valid or (len(args) == 4 and args[:3] == ("put", "system", SETTING) and isinstance(args[3], str) and re.fullmatch(r"[0-9]{1,10}", args[3]) is not None)
    if not valid:
        raise AdbCommandError()
    result = subprocess.run([adb_path, "-s", serial, "shell", "settings", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=ADB_TIMEOUT, check=False, shell=False)
    if result.returncode != 0:
        raise AdbCommandError()
    return result.stdout.decode("utf-8").strip()


def _value(text):
    if text == "null":
        return None
    if not isinstance(text, str) or re.fullmatch(r"[0-9]{1,10}", text) is None:
        raise GuardReadbackError()
    return int(text)


def _write(path, state):
    path = Path(path)
    if path.is_symlink():
        raise ScreenGuardError()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".screen-guard-", delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write((json.dumps(state, sort_keys=True) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ScreenGuardError()
    state = json.loads(path.read_bytes())
    if not isinstance(state, dict) or state.get("schema_version") != 1 or state.get("setting") != SETTING:
        raise ScreenGuardError()
    _identity(state.get("adb_path"), state.get("serial"), state.get("duration_seconds"))
    if state.get("original_value") is not None and (type(state["original_value"]) is not int or state["original_value"] < 0):
        raise ScreenGuardError()
    for name in ("created_epoch", "deadline_epoch"):
        if type(state.get(name)) not in {int, float}:
            raise ScreenGuardError()
    if abs(state["deadline_epoch"] - state["created_epoch"] - state["duration_seconds"]) > 0.01:
        raise ScreenGuardError()
    if not isinstance(state.get("guard_id"), str) or type(state.get("restore_pending")) is not bool:
        raise ScreenGuardError()
    return state


@contextlib.contextmanager
def _locked(path):
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield
    except BaseException:
        # fdopen owns fd after construction; only close a still-open descriptor.
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _safe_result(state=None, path=None, error_class=None):
    return {"active": bool(state and state.get("phase") == "active" and state.get("restore_pending")), "deadline": state.get("deadline") if state else None, "restore_pending": bool(state and state.get("restore_pending")), "restored": state.get("restored") if state else None, "error_class": error_class or (state.get("error_class") if state else None), "state_path": str(path) if path else None}


def _start_watchdog(path):
    keep = {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_PORT"}
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--watchdog", str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, env={key: value for key, value in os.environ.items() if key in keep})
    limit = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < limit:
        if process.poll() is not None:
            raise WatchdogSetupError()
        state = _load(path)
        if state.get("phase") == "armed" and state.get("watchdog_ready") is True and state.get("watchdog_pid") == process.pid:
            return process
        time.sleep(0.02)
    raise WatchdogSetupError()


def restore_now(guard_state_path):
    path = Path(guard_state_path).expanduser().absolute()
    with _locked(path):
        state = _load(path)
        try:
            try:
                actual = _value(_adb(state["adb_path"], state["serial"], "get", "system", SETTING))
                needs_write = actual != state["original_value"]
            except BaseException:
                needs_write = True  # Unknown partial application: restore original.
            if needs_write:
                if state["original_value"] is None:
                    _adb(state["adb_path"], state["serial"], "delete", "system", SETTING)
                else:
                    _adb(state["adb_path"], state["serial"], "put", "system", SETTING, str(state["original_value"]))
                actual = _value(_adb(state["adb_path"], state["serial"], "get", "system", SETTING))
            if actual != state["original_value"]:
                raise GuardReadbackError()
            state.update({"phase": "restored", "restored": True, "restore_pending": False, "restored_readback": actual, "restored_epoch": time.time(), "error_class": None})
        except BaseException as exc:
            state.update({"phase": "restore_failed", "restored": False, "restore_pending": True, "error_class": type(exc).__name__})
        _write(path, state)
        return _safe_result(state, path)


def start_screen_guard(adb_path, serial, guard_state_path, duration_seconds=1800):
    """Caller must have just verified real unlocked UI and matching account."""
    adb_path = _identity(adb_path, serial, duration_seconds)
    path = Path(guard_state_path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = None
    try:
        with _locked(path):
            if path.exists():
                existing = _load(path)
                if existing["restore_pending"]:
                    return _safe_result(existing, path, "GuardAlreadyActive")
            original = _value(_adb(adb_path, serial, "get", "system", SETTING))
            created = time.time()
            state = {"schema_version": 1, "guard_id": uuid.uuid4().hex, "setting": SETTING, "adb_path": adb_path, "serial": serial, "original_value": original, "desired_value": duration_seconds * 1000, "created_epoch": created, "duration_seconds": duration_seconds, "deadline_epoch": created + duration_seconds, "deadline": dt.datetime.fromtimestamp(created + duration_seconds, dt.timezone.utc).isoformat(), "phase": "preparing", "watchdog_ready": False, "watchdog_pid": None, "restore_pending": True, "restored": False, "error_class": None}
            _write(path, state)
        process = _start_watchdog(path)  # MUST be armed/live before settings put.
        with _locked(path):
            state = _load(path)
            if process.poll() is not None or state.get("phase") != "armed" or state.get("watchdog_ready") is not True or state.get("watchdog_pid") != process.pid or time.time() >= state["deadline_epoch"] - RESTORE_RESERVE:
                raise WatchdogSetupError()
            state["phase"] = "applying"
            _write(path, state)  # Partial put outcome is recoverable by watchdog.
            _adb(adb_path, serial, "put", "system", SETTING, str(state["desired_value"]))
            actual = _value(_adb(adb_path, serial, "get", "system", SETTING))
            if actual != state["desired_value"]:
                raise GuardReadbackError()
            state.update({"phase": "active", "active_readback": actual, "restore_pending": True, "restored": False})
            _write(path, state)
        return _safe_result(state, path)
    except BaseException as exc:
        error_class = type(exc).__name__
        if state is not None:
            # Roll back even when put may have taken effect before raising.
            try:
                result = restore_now(path)
                result["error_class"] = error_class
                return result
            except BaseException as rollback_exc:
                return {**_safe_result(state, path, error_class), "active": False, "restored": False, "restore_pending": True, "rollback_error_class": type(rollback_exc).__name__}
        return _safe_result(None, None, error_class)


def _verified(auth):
    cleanup = auth.get("cleanup") if isinstance(auth, dict) else None
    return bool(isinstance(auth, dict) and auth.get("stage") == "verified" and auth.get("error_class") is None and auth.get("input_attempted") is True and auth.get("keyguard_cleared") is True and auth.get("restored") is True and isinstance(cleanup, dict) and cleanup.get("private_deleted") is True and cleanup.get("cipher_deleted") is True and cleanup.get("error_classes") == [])


def transact_with_screen_guard(adb_path, serial, guard_state_path, duration_seconds=1800, **transact_kwargs):
    _identity(adb_path, serial, duration_seconds)  # Reject invalid setup before auth.
    path = Path(guard_state_path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        if path.exists():
            existing = _load(path)
            if existing["restore_pending"]:
                return {"auth": None, "guard": _safe_result(existing, path, "GuardAlreadyActive")}
    auth = _auth_transact(**transact_kwargs)  # Exactly one in-process auth call.
    guard = start_screen_guard(adb_path, serial, guard_state_path, duration_seconds) if _verified(auth) else _safe_result()
    return {"auth": auth, "guard": guard}


def watchdog(guard_state_path):
    """Credential-free detached display restoration; never UI or authentication."""
    path = Path(guard_state_path).expanduser().absolute()
    with _locked(path):
        state = _load(path)
        if not state["restore_pending"]:
            return 0
        if _value(_adb(state["adb_path"], state["serial"], "get", "system", SETTING)) != state["original_value"]:
            raise WatchdogSetupError()
        guard_id = state["guard_id"]
        state.update({"phase": "armed", "watchdog_ready": True, "watchdog_pid": os.getpid()})
        _write(path, state)
    limit = time.monotonic() + min(state["duration_seconds"], max(0, state["deadline_epoch"] - time.time()))
    while True:
        latest = _load(path)
        if latest["guard_id"] != guard_id or not latest["restore_pending"]:
            return 0
        if time.monotonic() >= limit - RESTORE_RESERVE:
            result = restore_now(path)
            if result["restored"] is True:
                return 0
            if time.monotonic() >= limit:
                return 2
        time.sleep(min(0.5, max(0.01, limit - time.monotonic())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="No-credential screen-timeout restore/watchdog or dummy tests only.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--restore-now")
    group.add_argument("--watchdog")
    args = parser.parse_args()
    if args.self_test:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent / "tests"), pattern="test_normal_auth_screen_session.py")
        if suite.countTestCases() == 0:
            raise SystemExit("No dummy tests found.")
        raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
    try:
        if args.watchdog:
            raise SystemExit(watchdog(args.watchdog))
        result = restore_now(args.restore_now)
        print(json.dumps({"guard": result}, sort_keys=True))
        raise SystemExit(0 if result["restored"] is True else 2)
    except Exception as exc:
        if not args.watchdog:
            print(json.dumps({"guard": {"active": False, "restored": False, "restore_pending": True, "error_class": type(exc).__name__}}, sort_keys=True))
        raise SystemExit(2)
