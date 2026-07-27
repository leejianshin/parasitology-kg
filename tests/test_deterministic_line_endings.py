from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
