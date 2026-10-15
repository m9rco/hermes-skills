"""Local argument-transport tests; every executable and payload is synthetic."""

import hashlib
import importlib.util
import contextlib
import copy
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "prepare_note_input.py"
SPEC = importlib.util.spec_from_file_location("synthetic_prepare_note_input_test", SOURCE)
prepare_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_module)
LEGACY_SOURCE = Path(__file__).resolve().parent / "fixtures" / "prepare_note_input-legacy.py"
LEGACY_SPEC = importlib.util.spec_from_file_location("synthetic_legacy_prepare_note_input_test", LEGACY_SOURCE)
legacy_module = importlib.util.module_from_spec(LEGACY_SPEC)
LEGACY_SPEC.loader.exec_module(legacy_module)


class PrepareNoteInputTests(unittest.TestCase):
    POST_ID = "synthetic-d01"
    SERIAL = "SYNTHETIC-SERIAL"
    REMOTE_JAR = "/data/local/tmp/synthetic-note-input.jar"
    METHOD = "com.shenqi.input.XhsNoteInput#testFillTitleAndBody"

    def _prepare(self, *, title="合成测试标题", body="合成测试正文。", adb_path="synthetic-adb", **kwargs):
        return prepare_module.prepare(
            {"post_id": self.POST_ID, "title": title, "caption": body},
            post_id=self.POST_ID,
            adb_path=adb_path,
            serial=self.SERIAL,
            remote_jar=self.REMOTE_JAR,
            **kwargs,
        )

    def _parameters(self, argv):
        pairs = {}
        for index, token in enumerate(argv):
            if token == "-e":
                self.assertNotIn(argv[index + 1], pairs)
                pairs[argv[index + 1]] = argv[index + 2]
        return pairs

    def _write_dummy_executable(self, path, python_source):
        path.write_text(
            "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -c "
            + shlex.quote(python_source) + ' "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o700)

    def test_default_launcher_preserves_legacy_uiautomator_arguments(self):
        result = self._prepare()
        argv = result["remote_argv"]
        self.assertEqual(argv[:5], ["uiautomator", "runtest", self.REMOTE_JAR, "-c", self.METHOD])
        self.assertEqual(self._parameters(argv), result["parameters"])
        self.assertEqual(list(result["parameters"]), ["post_id", "title", "body", "title_sha256", "body_sha256"])
        self.assertEqual(shlex.split(result["remote_command"]), argv)
        self.assertEqual(shlex.split(result["posix_host_command"]), result["adb_argv"])
        self.assertEqual(result["status"], "prepared_only_not_executed")
        self.assertIs(result["publication_clicked"], False)

    def test_app_process_argv_includes_jars_and_unchanged_five_parameters(self):
        legacy = self._prepare()
        result = self._prepare(launcher="app-process")
        argv = result["remote_argv"]
        self.assertEqual(argv[0], "env")
        self.assertEqual(
            argv[1],
            "CLASSPATH=/system/framework/android.test.runner.jar:/system/framework/uiautomator.jar:"
            + self.REMOTE_JAR,
        )
        self.assertEqual(argv[2], "ANDROID_DATA=/data/local/tmp")
        self.assertEqual(
            argv[3:12],
            ["app_process", "/system/bin", "com.android.commands.uiautomator.Launcher",
             "runtest", "-c", self.METHOD, "-e", "jars", self.REMOTE_JAR],
        )
        self.assertEqual(argv[12:], legacy["remote_argv"][5:])
        self.assertEqual(result["parameters"], legacy["parameters"])
        self.assertEqual(self._parameters(argv), {"jars": self.REMOTE_JAR, **legacy["parameters"]})
        self.assertEqual(shlex.split(result["remote_command"]), argv)
        self.assertEqual(result["adb_argv"][-1], result["remote_command"])

    def test_actual_two_shell_hops_preserve_text_and_never_execute_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "synthetic tools"
            tools.mkdir()
            capture = root / "captured-arguments.json"
            fake_adb = tools / "dummy adb never a device"
            fake_app_process = tools / "app_process"
            dollar_sentinel = root / "dollar-must-not-exist"
            backtick_sentinel = root / "backtick-must-not-exist"
            semicolon_sentinel = root / "semicolon-must-not-exist"
            title = (
                "合成 title 空格 ' \" 😀 $(touch " + shlex.quote(str(dollar_sentinel)) + ")"
            )
            body = (
                "合成第一行 ' \" \\ 😀\n第二行 `touch "
                + shlex.quote(str(backtick_sentinel)) + "` ; touch "
                + shlex.quote(str(semicolon_sentinel)) + " ; 保持纯文本"
            )
            self._write_dummy_executable(
                fake_adb,
                "import os, subprocess, sys\n"
                "if len(sys.argv) != 5 or sys.argv[1:4] != ['-s', 'SYNTHETIC-SERIAL', 'shell']:\n"
                "    raise SystemExit(97)\n"
                "result = subprocess.run(['/bin/sh', '-c', sys.argv[4]], env=os.environ, check=False)\n"
                "raise SystemExit(result.returncode)\n",
            )
            self._write_dummy_executable(
                fake_app_process,
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['SYNTHETIC_CAPTURE_PATH']).write_text(json.dumps("
                "{'argv': sys.argv[1:], 'classpath': os.environ.get('CLASSPATH'), "
                "'android_data': os.environ.get('ANDROID_DATA')}, "
                "ensure_ascii=False), encoding='utf-8')\n",
            )
            result = self._prepare(
                title=title, body=body, adb_path=str(fake_adb), launcher="app-process"
            )
            completed = subprocess.run(
                ["/bin/sh", "-c", result["posix_host_command"]],
                env={"PATH": str(tools) + ":/usr/bin:/bin", "SYNTHETIC_CAPTURE_PATH": str(capture)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
                shell=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            captured = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(captured["argv"], result["remote_argv"][4:])
            self.assertEqual(captured["classpath"], result["remote_argv"][1].partition("=")[2])
            self.assertEqual(captured["android_data"], "/data/local/tmp")
            pairs = self._parameters(captured["argv"])
            self.assertEqual(pairs["jars"], self.REMOTE_JAR)
            self.assertEqual(pairs["post_id"], self.POST_ID)
            self.assertEqual(pairs["title"], title)
            self.assertEqual(pairs["body"], body)
            self.assertEqual(pairs["title_sha256"], hashlib.sha256(title.encode("utf-8")).hexdigest())
            self.assertEqual(pairs["body_sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())
            for sentinel in (dollar_sentinel, backtick_sentinel, semicolon_sentinel):
                self.assertFalse(sentinel.exists())

    def test_unknown_launcher_is_rejected(self):
        with self.assertRaises(ValueError):
            self._prepare(launcher="synthetic-unsupported-launcher")

    def _rendered_with_parts(self, disclosure=""):
        parts = {
            "body": "  合成正文提到 #针织穿搭 #日常穿搭。\n空格和原文都保留  ",
            "question": "  你会选哪一套？😀 ",
            "disclosure": disclosure,
            "hashtags": ["#针织穿搭", "#日常穿搭"],
        }
        sections = [parts["body"], parts["question"]]
        if disclosure != "":
            sections.append(disclosure)
        return {"post_id": self.POST_ID, "title": "合成标题😀", "caption_parts": parts,
                "caption": "\n\n".join([*sections, " ".join(parts["hashtags"])])}

    def _prepare_document(self, rendered, **kwargs):
        return prepare_module.prepare(rendered, post_id=self.POST_ID, adb_path="synthetic-adb",
                                      serial=self.SERIAL, remote_jar=self.REMOTE_JAR, **kwargs)

    def test_default_and_explicit_full_caption_are_exactly_legacy_compatible(self):
        for rendered in (
            self._rendered_with_parts(),
            {"post_id": self.POST_ID, "title": "旧输入", "caption": "旧输入无需 caption_parts"},
            {"post_id": self.POST_ID, "title": "旧输入", "caption": "正文", "caption_parts": None},
        ):
            for launcher in ("uiautomator", "app-process"):
                with self.subTest(rendered=rendered, launcher=launcher):
                    expected = legacy_module.prepare(rendered, post_id=self.POST_ID, adb_path="synthetic-adb",
                                                     serial=self.SERIAL, remote_jar=self.REMOTE_JAR, launcher=launcher)
                    self.assertEqual(self._prepare_document(rendered, launcher=launcher), expected)
                    self.assertEqual(self._prepare_document(rendered, launcher=launcher, input_phase="full-caption"), expected)

    def test_prefix_removes_only_exact_tail_and_keeps_source_argv_hashes_separate(self):
        rendered = self._rendered_with_parts()
        before = copy.deepcopy(rendered)
        expected = rendered["caption_parts"]["body"] + "\n\n" + rendered["caption_parts"]["question"] + "\n\n"
        for launcher in ("uiautomator", "app-process"):
            result = self._prepare_document(rendered, launcher=launcher, input_phase="body-before-native-topics")
            self.assertEqual(rendered, before)
            self.assertEqual(result["parameters"]["body"], expected)
            self.assertTrue(result["parameters"]["body"].endswith("\n\n"))
            self.assertIn("#针织穿搭 #日常穿搭", result["parameters"]["body"])
            self.assertEqual(result["parameters"]["body_sha256"], hashlib.sha256(expected.encode()).hexdigest())
            self.assertEqual(result["source_final_caption_sha256"], hashlib.sha256(rendered["caption"].encode()).hexdigest())
            self.assertNotEqual(result["source_final_caption_sha256"], result["parameters"]["body_sha256"])
            self.assertEqual(result["parameters"]["title_sha256"], hashlib.sha256(rendered["title"].encode()).hexdigest())
            self.assertEqual(result["expected_body_utf16_length"], len(expected.encode("utf-16-le")) // 2)
            actual_parameters = self._parameters(shlex.split(result["remote_command"]))
            if launcher == "app-process":
                self.assertEqual(actual_parameters.pop("jars"), self.REMOTE_JAR)
            self.assertEqual(actual_parameters, result["parameters"])
            self.assertEqual(shlex.split(result["posix_host_command"]), result["adb_argv"])
            self.assertEqual(result["input_phase"], "body-before-native-topics")
            self.assertIs(result["final_caption_ready"], False)
            self.assertIs(result["native_topic_binding_verified"], False)
            self.assertIs(result["publication_clicked"], False)

    def test_legacy_disclosure_remains_exactly_in_prefix(self):
        rendered = self._rendered_with_parts(disclosure=" 原创虚拟成人角色，AI生成画面。 ")
        result = self._prepare_document(rendered, input_phase="body-before-native-topics")
        parts = rendered["caption_parts"]
        self.assertEqual(result["parameters"]["body"], "\n\n".join([parts["body"], parts["question"], parts["disclosure"]]) + "\n\n")

    def test_malformed_parts_and_inexact_final_caption_are_rejected_without_mutation(self):
        valid = self._rendered_with_parts()
        bad_documents = []
        for value in (None, [], "wrong-type"):
            bad = copy.deepcopy(valid)
            bad["caption_parts"] = value
            bad_documents.append(bad)
        for key, value in (
            ("body", None), ("body", ""), ("question", 1), ("question", ""),
            ("disclosure", None), ("hashtags", []), ("hashtags", [""]),
            ("hashtags", ["#"]), ("hashtags", ["#普通", None]),
            ("hashtags", ("#普通",)), ("hashtags", ["不是标签"]),
            ("hashtags", ["#普通 标签"]), ("hashtags", ["#普通\n标签"]),
            ("hashtags", list(reversed(valid["caption_parts"]["hashtags"]))),
        ):
            bad = copy.deepcopy(valid)
            bad["caption_parts"][key] = value
            bad_documents.append(bad)
        bad = copy.deepcopy(valid)
        del bad["caption_parts"]["disclosure"]
        bad_documents.append(bad)
        for caption in (valid["caption"] + "\n", valid["caption"] + " ",
                        valid["caption"].replace("合成正文", "未经确认的正文"),
                        valid["caption"].replace("\n\n", "\n", 1)):
            bad = copy.deepcopy(valid)
            bad["caption"] = caption
            bad_documents.append(bad)
        for rendered in bad_documents:
            before = copy.deepcopy(rendered)
            with self.subTest(rendered=rendered), self.assertRaises(ValueError):
                self._prepare_document(rendered, input_phase="body-before-native-topics")
            self.assertEqual(rendered, before)

    def test_unknown_input_phase_is_rejected(self):
        with self.assertRaises(ValueError):
            self._prepare_document(self._rendered_with_parts(), input_phase="typo")

    def test_cli_explicit_phase_emits_prefix_and_retains_source_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rendered_post.json"
            raw = json.dumps(self._rendered_with_parts(), ensure_ascii=False).encode()
            path.write_bytes(raw)
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                status = prepare_module.main(["--rendered-post", str(path), "--post-id", self.POST_ID,
                                              "--serial", self.SERIAL, "--launcher", "app-process",
                                              "--input-phase", "body-before-native-topics"])
            self.assertEqual(status, 0)
            result = json.loads(captured.getvalue())
            self.assertEqual(result["source"]["rendered_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(result["input_phase"], "body-before-native-topics")
            self.assertTrue(result["parameters"]["body"].endswith("\n\n"))

    def test_terminal_space_is_removed_with_tags_and_never_with_prefix_or_legacy_disclosure(self):
        for disclosure in ("", " 原创虚拟成人角色 · AI 影像。 "):
            with self.subTest(disclosure=disclosure):
                original = self._rendered_with_parts(disclosure)
                baseline = self._prepare_document(original, input_phase="body-before-native-topics", launcher="app-process")
                rendered = copy.deepcopy(original)
                rendered["caption_parts"]["topic_terminal_separator"] = " "
                rendered["caption"] += " "
                before = copy.deepcopy(rendered)
                result = self._prepare_document(rendered, input_phase="body-before-native-topics", launcher="app-process")
                self.assertEqual(result["parameters"], baseline["parameters"])
                self.assertEqual(result["adb_argv"], baseline["adb_argv"])
                self.assertEqual(result["source_final_caption_sha256"], hashlib.sha256(rendered["caption"].encode()).hexdigest())
                self.assertNotEqual(result["source_final_caption_sha256"], baseline["source_final_caption_sha256"])
                actual = self._parameters(shlex.split(result["remote_command"]))
                self.assertEqual(actual["body"], baseline["parameters"]["body"])
                self.assertEqual(actual["body_sha256"], hashlib.sha256(actual["body"].encode()).hexdigest())
                self.assertTrue(actual["body"].endswith("\n\n"))
                self.assertEqual(rendered, before)

    def test_explicit_empty_separator_has_same_prefix_output_as_absent(self):
        rendered = self._rendered_with_parts()
        baseline = self._prepare_document(rendered, input_phase="body-before-native-topics")
        rendered["caption_parts"]["topic_terminal_separator"] = ""
        self.assertEqual(self._prepare_document(rendered, input_phase="body-before-native-topics"), baseline)

    def test_invalid_separator_and_mismatched_caption_are_rejected(self):
        for separator in (None, "  ", "\n", "\t", "\u00a0", 0, False, [], {}):
            for phase in ("full-caption", "body-before-native-topics"):
                with self.subTest(separator=separator, phase=phase):
                    rendered = self._rendered_with_parts()
                    rendered["caption_parts"]["topic_terminal_separator"] = separator
                    with self.assertRaises(ValueError):
                        self._prepare_document(rendered, input_phase=phase)
        for separator, added in ((" ", ""), ("", " ")):
            with self.subTest(separator=separator, added=added):
                rendered = self._rendered_with_parts()
                rendered["caption_parts"]["topic_terminal_separator"] = separator
                rendered["caption"] += added
                with self.assertRaises(ValueError):
                    self._prepare_document(rendered, input_phase="body-before-native-topics")


if __name__ == "__main__":
    unittest.main()
