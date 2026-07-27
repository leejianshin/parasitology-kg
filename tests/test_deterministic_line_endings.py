from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATED_TEXT_SUFFIXES = {".md", ".yml", ".jsonl", ".csv"}


class DeterministicLineEndingTests(unittest.TestCase):
    def test_generated_text_artifacts_are_forced_to_lf(self) -> None:
        paths = sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "derived").rglob("*")
            if path.is_file() and path.suffix in GENERATED_TEXT_SUFFIXES
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


if __name__ == "__main__":
    unittest.main()
