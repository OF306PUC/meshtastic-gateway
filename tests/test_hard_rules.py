"""Rules over the source tree.

1. The gateway does not import meshtastic-platform: it owns its decoder and
   pairs with the platform only through deployments/ (user, 2026-10-26).
2. No sys.path manipulation: entry points import the packages beside them.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [p for p in ROOT.rglob("*.py")
           if ".venv" not in p.parts and p != Path(__file__).resolve()]


def _offenders(pattern: str) -> list[str]:
    rx = re.compile(pattern, re.MULTILINE)
    return [str(p.relative_to(ROOT)) for p in SOURCES if rx.search(p.read_text())]


class TestHardRules(unittest.TestCase):
    def test_the_scan_sees_the_sources(self):
        self.assertIn(ROOT / "gateway" / "decode.py", SOURCES)

    def test_no_platform_imports(self):
        self.assertEqual(_offenders(r"^\s*(from|import)\s+meshtastic_platform\b"), [])

    def test_no_sys_path_manipulation(self):
        self.assertEqual(_offenders(r"sys\.path"), [])


if __name__ == "__main__":
    unittest.main()
