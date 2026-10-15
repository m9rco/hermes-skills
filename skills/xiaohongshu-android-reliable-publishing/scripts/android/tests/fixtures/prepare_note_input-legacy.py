#!/usr/bin/env python3
"""Prepare public per-post legacy UiAutomator arguments; never execute ADB."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import zipfile


# Verified from the actual device wrapper (4173B, SHA256
# 588f4e89975e626c1ae185c350389e4fad005b2cb9525834a42dfa7dfd548545).
APP_PROCESS_BASE_CLASSPATH = "/system/framework/android.test.runner.jar:/system/framework/uiautomator.jar"


def prepare(rendered: dict, *, post_id: str, adb_path: str, serial: str,
            remote_jar: str, launcher: str = "uiautomator") -> dict:
    if launcher not in {"uiautomator", "app-process"}:
        raise ValueError("unsupported launcher")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", post_id):
        raise ValueError("invalid post id")
    if not isinstance(rendered, dict) or rendered.get("post_id") != post_id:
        raise ValueError("rendered post id must match the explicitly requested post")
    title, caption = rendered.get("title"), rendered.get("caption")
    for value in (title, caption):
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("title and complete caption must be nonempty strings without NUL")
        value.encode("utf-8", errors="strict")
    if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", serial):
        raise ValueError("invalid device serial")
    if not isinstance(adb_path, str) or not adb_path or "\x00" in adb_path:
        raise ValueError("invalid adb path")
    if not re.fullmatch(r"/data/local/tmp/[A-Za-z0-9][A-Za-z0-9._-]*\.jar", remote_jar):
        raise ValueError("remote jar must be a simple .jar path under /data/local/tmp")
    digest = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    parameters = {"post_id": post_id, "title": title, "body": caption,
                  "title_sha256": digest(title), "body_sha256": digest(caption)}
    method = "com.shenqi.input.XhsNoteInput#testFillTitleAndBody"
    if launcher == "uiautomator":
        remote_argv = ["uiautomator", "runtest", remote_jar, "-c", method]
    else:
        # The actual legacy shell wrapper rebuilds then unquoted-expands args,
        # destroying spaces/newlines. Call its same Launcher and environment
        # directly; the standard runner still receives ordinary -e parameters.
        remote_argv = ["env", "CLASSPATH=" + APP_PROCESS_BASE_CLASSPATH + ":" + remote_jar,
                       "ANDROID_DATA=/data/local/tmp", "app_process", "/system/bin",
                       "com.android.commands.uiautomator.Launcher", "runtest", "-c", method,
                       "-e", "jars", remote_jar]
    for key, value in parameters.items():
        remote_argv.extend(["-e", key, value])
    # One explicitly quoted remote command argument survives the ADB shell hop.
    remote_command = shlex.join(remote_argv)
    adb_argv = [adb_path, "-s", serial, "shell", remote_command]
    return {"schema_version": 1, "post_id": post_id, "status": "prepared_only_not_executed",
            "parameters": parameters, "expected_title_utf16_length": len(title.encode("utf-16-le")) // 2,
            "expected_body_utf16_length": len(caption.encode("utf-16-le")) // 2,
            "remote_argv": remote_argv, "remote_command": remote_command,
            "adb_argv": adb_argv, "posix_host_command": shlex.join(adb_argv),
            "success_requires": "Actual SHENQI_INPUT_RESULT filled_and_verified for this post with both readback hashes matching the pins, plus actual XHS preview review. JUnit OK or exit 0 alone is insufficient.",
            "publication_clicked": False}


def read_rendered(args) -> tuple[dict, dict]:
    if args.rendered_post:
        path = Path(args.rendered_post)
        if path.name != "rendered_post.json":
            raise ValueError("the direct input must be the actual rendered_post.json file")
        raw = path.read_bytes()
        source = {"rendered_post": str(path), "rendered_sha256": hashlib.sha256(raw).hexdigest()}
    else:
        path = Path(args.materials_zip)
        with zipfile.ZipFile(path) as archive:
            if archive.namelist().count("rendered_post.json") != 1 or archive.namelist().count("manifest.json") != 1:
                raise ValueError("archive needs exactly one rendered_post.json and manifest.json")
            raw = archive.read("rendered_post.json")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("post_id") != args.post_id:
                raise ValueError("manifest post id mismatch")
            record = manifest.get("files", {}).get("rendered_post.json", {})
            if record.get("sha256") != hashlib.sha256(raw).hexdigest() or record.get("bytes") != len(raw):
                raise ValueError("rendered post manifest hash or size mismatch")
        source = {"materials_zip": str(path), "rendered_member": "rendered_post.json",
                  "rendered_sha256": hashlib.sha256(raw).hexdigest()}
    return json.loads(raw), source


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rendered-post")
    source.add_argument("--materials-zip")
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb-path", default="adb")
    parser.add_argument("--remote-jar", default="/data/local/tmp/shenqi-note-input.jar")
    parser.add_argument("--launcher", choices=("uiautomator", "app-process"), default="uiautomator")
    args = parser.parse_args(argv)
    try:
        rendered, source_record = read_rendered(args)
        result = prepare(rendered, post_id=args.post_id, adb_path=args.adb_path,
                         serial=args.serial, remote_jar=args.remote_jar, launcher=args.launcher)
        result["source"] = source_record
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        print(json.dumps({"status": "prepare_failed", "error_class": "InvalidInputOrSource"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
