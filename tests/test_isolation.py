"""Fail if agent code in src/ can reach the answer key (docs/eval_plan.md, Isolation rules 1 and 4).

  python -m unittest discover tests
"""

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# Any path into eval/, any import of the eval package, or the README filename.
FORBIDDEN = [
    (re.compile(r"\beval[/\\]"), "path under eval/"),
    (re.compile(r"^\s*(from|import)\s+eval\b", re.MULTILINE), "import of the eval package"),
    (re.compile(r"changelog_README", re.IGNORECASE), "the changelog README filename"),
]


class TestIsolation(unittest.TestCase):
    def test_src_never_references_eval(self):
        files = sorted(SRC.rglob("*.py"))
        self.assertTrue(files, "no source files found in src/")
        problems = []
        for path in files:
            text = path.read_text()
            for pattern, what in FORBIDDEN:
                for m in pattern.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    problems.append(f"{path.relative_to(SRC.parent)}:{line} references {what}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
