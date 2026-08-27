"""Run the smoke-pipeline regression suite without requiring pytest."""

from __future__ import annotations

import sys
import unittest


def main() -> int:
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
