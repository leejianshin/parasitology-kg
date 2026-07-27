from __future__ import annotations

import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.build_derived_graph import build_graph
from scripts.build_pcms_graph import build_pcms_graph
from scripts.validate_pcms_regression import report_matches


ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}


class DeterministicLineEndingTests(unittest.TestCase):
    def test_controlled_text_files_are_forced_to_lf(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        paths = sorted(
            path
            for path in tracked
            if path and Path(path).suffix in CONTROLLED_TEXT_SUFFIXES
        )
        self.assertTrue(paths)

        completed = subprocess.run(
            ["git", "check-attr", "eol", "--", *paths],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        attributes = {}
        for line in completed.stdout.splitlines():
            path, attribute, value = line.rsplit(": ", 2)
            self.assertEqual(attribute, "eol")
            attributes[path] = value

        self.assertEqual(set(attributes), set(paths))
        self.assertTrue(
            all(value == "lf" for value in attributes.values()),
            attributes,
        )

    def test_canonical_hashes_ignore_crlf_worktree_bytes(self) -> None:
        expected_base = build_graph(ROOT)
        expected_pcms = build_pcms_graph(ROOT)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            for directory in (
                "knowledge",
                "knowledge-extensions",
                "schema",
                "sources",
            ):
                shutil.copytree(ROOT / directory, temporary_root / directory)

            for suffix in ("*.md", "*.yml", "*.yaml"):
                for path in temporary_root.rglob(suffix):
                    text = path.read_text(encoding="utf-8")
                    path.write_bytes(
                        text.replace("\n", "\r\n").encode("utf-8")
                    )

            actual_base = build_graph(temporary_root)
            actual_pcms = build_pcms_graph(temporary_root)

        self.assertEqual(actual_base, expected_base)
        self.assertEqual(actual_pcms, expected_pcms)

    def test_regression_report_ignores_only_line_ending_style(self) -> None:
        expected = (
            b"report_version: '1.0'\n"
            b"status: PASS\n"
            b"counts:\n"
            b"  cases: 16\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = Path(temporary_directory) / "report.yml"
            report_path.write_bytes(expected.replace(b"\n", b"\r\n"))
            self.assertTrue(report_matches(report_path, expected))

            report_path.write_bytes(
                expected.replace(b"status: PASS", b"status: FAIL")
            )
            self.assertFalse(report_matches(report_path, expected))


if __name__ == "__main__":
    unittest.main()
