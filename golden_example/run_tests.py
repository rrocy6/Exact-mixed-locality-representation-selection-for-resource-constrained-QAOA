"""Dependency-free runner for the pytest-compatible golden test functions."""

import inspect
import traceback

from tests import test_max3sat_worked_example as suite


def main():
    tests = [
        (name, function)
        for name, function in inspect.getmembers(suite, inspect.isfunction)
        if name.startswith("test_")
    ]
    failures = []
    for name, function in tests:
        try:
            function()
            print(f"PASS {name}")
        except Exception:
            failures.append(name)
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failures)} passed, {len(failures)} failed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
