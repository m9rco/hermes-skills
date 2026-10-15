#!/usr/bin/env python3
"""Build the fill-only helper with existing tools; never download or run on-device."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

SOURCE = Path(__file__).resolve().parent / "com/shenqi/input/XhsNoteInput.java"
STUB_NAME = "com/android/uiautomator/testrunner/UiAutomatorTestCase"
ANNOTATION_NAME = "android/test/RepetitiveTest"
MAIN_NAME = "com/shenqi/input/XhsNoteInput"
STUB_SOURCE = """package com.android.uiautomator.testrunner;
public class UiAutomatorTestCase {
    public android.os.Bundle getParams() {
        throw new UnsupportedOperationException("COMPILE_TIME_SIGNATURE_ONLY");
    }
}
"""
# Preserve the compatibility annotation actually used by the successful D01 jar.
# Its member has no default; this is not a claim to reproduce every AOSP default.
ANNOTATION_SOURCE = """package android.test;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface RepetitiveTest {
    int numIterations();
}
"""


class BuildError(Exception):
    def __init__(self, error_class, step=None):
        self.error_class, self.step = error_class, step
        super().__init__(error_class)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def archive_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return out.getvalue()


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def preflight(args):
    inputs, errors = {}, []
    if not SOURCE.is_file():
        return inputs, ["MissingCompanionSource"]
    inputs["source"] = {"path": str(SOURCE), "bytes": SOURCE.stat().st_size, "sha256": file_digest(SOURCE)}
    for name, supplied, required_entry in (("android_jar", args.android_jar, "android/os/Bundle.class"),
                                           ("d8_jar", args.d8_jar, "com/android/tools/r8/D8.class")):
        path = Path(supplied).expanduser()
        if not path.is_file():
            errors.append("MissingAndroidJar" if name == "android_jar" else "MissingD8Jar")
            continue
        try:
            with zipfile.ZipFile(path) as jar:
                if required_entry not in jar.namelist():
                    raise BuildError("RequiredClassMissing")
            inputs[name] = {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_digest(path)}
        except Exception:
            errors.append("InvalidAndroidJar" if name == "android_jar" else "InvalidD8Jar")
    for name, supplied in (("javac", args.javac), ("java", args.java)):
        resolved = shutil.which(supplied)
        if resolved is None:
            errors.append("MissingJavac" if name == "javac" else "MissingJava")
        else:
            inputs[name] = str(Path(resolved).resolve())
    return inputs, errors


def dex_class_descriptors(data):
    """Read DEX class_defs, not all referenced strings; prove stubs are not defined."""
    if len(data) < 112 or not data.startswith(b"dex\n"):
        raise BuildError("InvalidDexHeader", "verify_dex")
    def u32(offset):
        if offset < 0 or offset + 4 > len(data):
            raise BuildError("InvalidDexBounds", "verify_dex")
        return struct.unpack_from("<I", data, offset)[0]
    if u32(32) != len(data) or u32(40) != 0x12345678:
        raise BuildError("InvalidDexHeader", "verify_dex")
    strings_n, strings_off = u32(56), u32(60)
    types_n, types_off = u32(64), u32(68)
    classes_n, classes_off = u32(96), u32(100)
    if strings_off + strings_n * 4 > len(data) or types_off + types_n * 4 > len(data) or classes_off + classes_n * 32 > len(data):
        raise BuildError("InvalidDexBounds", "verify_dex")
    result = set()
    for index in range(classes_n):
        type_index = u32(classes_off + index * 32)
        if type_index >= types_n:
            raise BuildError("InvalidDexType", "verify_dex")
        string_index = u32(types_off + type_index * 4)
        if string_index >= strings_n:
            raise BuildError("InvalidDexString", "verify_dex")
        offset = u32(strings_off + string_index * 4)
        for _ in range(5):
            if offset >= len(data):
                raise BuildError("InvalidDexString", "verify_dex")
            byte = data[offset]
            offset += 1
            if not byte & 128:
                break
        else:
            raise BuildError("InvalidDexString", "verify_dex")
        end = data.find(b"\0", offset, min(len(data), offset + 1024))
        if end == -1:
            raise BuildError("InvalidDexString", "verify_dex")
        try:
            result.add(data[offset:end].decode("ascii"))
        except UnicodeError:
            raise BuildError("UnexpectedDexDescriptor", "verify_dex") from None
    return result


def build(inputs, build_root):
    root = Path(build_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="shenqi-note-build-", dir=root))
    logs = {}
    record = {"schema_version": 1, "purpose": "post_publish_maintenance_only", "status": "build_started",
              "inputs": inputs, "build_dir": str(work), "commands": [], "runtime_jar_sha256": None,
              "sdk_compile_status": "pending", "real_home_acceptance": "pending",
              "device_ui_validation": "pending_D02_unpublished_draft", "publication_action": "not_performed",
              "compile_time_stub_excluded_from_runtime": False}
    def run(step, argv):
        record["commands"].append({"step": step, "argv": [str(x) for x in argv], "shell": False})
        try:
            process = subprocess.run([str(x) for x in argv], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, timeout=120, check=False, shell=False, cwd=work)
            logs[step + ".log"] = process.stdout
        except subprocess.TimeoutExpired as error:
            logs[step + ".log"] = error.stdout or b""
            raise BuildError("CommandTimeout", step) from None
        except OSError:
            raise BuildError("CommandUnavailable", step) from None
        if process.returncode != 0:
            record["failed_command_returncode"] = process.returncode
            raise BuildError("CommandFailed", step)
    success = False
    try:
        # Snapshot the public source; subsequent edits cannot silently change this build.
        source_data = SOURCE.read_bytes()
        if digest(source_data) != inputs["source"]["sha256"]:
            raise BuildError("SourceChangedAfterPreflight")
        main_source = work / "runtime-src" / (MAIN_NAME + ".java")
        annotation_source = work / "runtime-src" / (ANNOTATION_NAME + ".java")
        stub_source = work / "compile-only-src" / (STUB_NAME + ".java")
        write_new(main_source, source_data)
        write_new(annotation_source, ANNOTATION_SOURCE.encode())
        write_new(stub_source, STUB_SOURCE.encode())
        record["compile_time_stub_source_sha256"] = digest(STUB_SOURCE.encode())
        record["runtime_annotation_source_sha256"] = digest(ANNOTATION_SOURCE.encode())
        stub_classes, runtime_classes, dex_dir = work / "compile-only-classes", work / "runtime-classes", work / "dex"
        for directory in (stub_classes, runtime_classes, dex_dir):
            directory.mkdir()
        android_jar, d8_jar = inputs["android_jar"]["path"], inputs["d8_jar"]["path"]
        java, javac = inputs["java"], inputs["javac"]
        flags = ["-encoding", "UTF-8", "-source", "8", "-target", "8", "-g:none"]
        run("javac-version", [javac, "-version"])
        run("java-version", [java, "-version"])
        run("compile-signature-only", [javac, *flags, "-classpath", android_jar, "-d", stub_classes, stub_source])
        stub_class = stub_classes / (STUB_NAME + ".class")
        if not stub_class.is_file():
            raise BuildError("CompileSignatureMissing")
        stub_library = work / "compile-only-uiautomator.jar"
        write_new(stub_library, archive_bytes({STUB_NAME + ".class": stub_class.read_bytes()}))
        run("compile-runtime-classes", [javac, *flags, "-classpath", android_jar + os.pathsep + str(stub_classes),
                                       "-d", runtime_classes, main_source, annotation_source])
        own = sorted(p for p in runtime_classes.rglob("*.class")
                     if p.relative_to(runtime_classes).as_posix() == MAIN_NAME + ".class"
                     or p.relative_to(runtime_classes).as_posix().startswith(MAIN_NAME + "$")
                     or p.relative_to(runtime_classes).as_posix() == ANNOTATION_NAME + ".class")
        relative = {p.relative_to(runtime_classes).as_posix() for p in own}
        if not {MAIN_NAME + ".class", MAIN_NAME + "$Field.class", ANNOTATION_NAME + ".class"} <= relative:
            raise BuildError("OwnInnerClassOrAnnotationMissing")
        if relative != {p.relative_to(runtime_classes).as_posix() for p in runtime_classes.rglob("*.class")}:
            raise BuildError("UnexpectedRuntimeClass")
        record["d8_program_classes"] = sorted(relative)
        # Path argv preserves '$Field'; only own classes + compatibility annotation are program inputs.
        run("d8", [java, "-cp", d8_jar, "com.android.tools.r8.D8", "--release", "--min-api", "21",
                   "--lib", android_jar, "--lib", stub_library, "--output", dex_dir, *own])
        if sorted(p.name for p in dex_dir.iterdir()) != ["classes.dex"]:
            raise BuildError("UnexpectedDexOutput", "verify_dex")
        dex_data = (dex_dir / "classes.dex").read_bytes()
        defined = dex_class_descriptors(dex_data)
        expected = {"L" + name[:-6] + ";" for name in relative}
        if defined != expected or any(x.startswith("Lcom/android/uiautomator/") for x in defined):
            raise BuildError("RuntimeDexContainsUnexpectedClassOrStub", "verify_dex")
        jar_data = archive_bytes({"classes.dex": dex_data})
        if jar_data != archive_bytes({"classes.dex": dex_data}):
            raise BuildError("JarContainerNotDeterministic")
        jar = work / "shenqi-note-input.jar"
        write_new(jar, jar_data)
        with zipfile.ZipFile(jar) as archive:
            if archive.namelist() != ["classes.dex"] or archive.testzip() is not None:
                raise BuildError("RuntimeJarInvalid")
        record.update({"status": "compiled_not_installed_or_ui_tested", "sdk_compile_status": "completed",
                       "runtime_jar": str(jar), "runtime_jar_bytes": len(jar_data), "runtime_jar_sha256": digest(jar_data),
                       "dex_defined_classes": sorted(defined), "compile_time_stub_excluded_from_runtime": True,
                       "jar_container_deterministic": True,
                       "whole_toolchain_reproducibility": "not_claimed_from_one_build"})
        success = True
    except BuildError as error:
        record.update({"status": "build_failed", "error_class": error.error_class, "failed_step": error.step})
    except Exception:
        record.update({"status": "build_failed", "error_class": "BuildFailed"})
    record_data = json_bytes(record)
    write_new(work / "build-record.json", record_data)
    log_files = {"build-record.json": record_data, **{"logs/" + name: data for name, data in logs.items()}}
    log_data = archive_bytes(log_files)
    log_path = work / "build-logs.zip"
    write_new(log_path, log_data)
    return success, {**record, "log_archive": str(log_path), "log_archive_bytes": len(log_data), "log_archive_sha256": digest(log_data)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-jar", default="/tmp/android-4.1.1.4.jar")
    parser.add_argument("--d8-jar", default="/tmp/bt34/android-14/lib/d8.jar")
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--java", default="java")
    parser.add_argument("--build-root", default="output/android-builds")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        inputs, errors = preflight(args)
        if errors or args.check_only:
            print(json.dumps({"purpose": "post_publish_maintenance_only", "status": "prerequisites_missing" if errors else "prerequisites_present_not_compiled",
                              "inputs": inputs, "error_classes": errors, "runtime_jar_sha256": None,
                              "log_archive": None, "real_home_compile_and_D02_draft_validation": "pending"}, sort_keys=True))
            return 2 if errors else 0
        success, result = build(inputs, args.build_root)
        print(json.dumps(result, sort_keys=True))
        return 0 if success else 2
    except Exception:
        print(json.dumps({"purpose": "post_publish_maintenance_only", "status": "build_failed", "error_class": "BuildFailed"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
