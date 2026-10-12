"""Record admission/schedule/shadow test results without hardware access."""
import argparse
import json
from pathlib import Path
import unittest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    output = Path(args.output).resolve()
    assert Path("E:/simulink/_codex_tmp").resolve() in output.parents
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["test_td3_candidate_selection", "test_speedloop_motion_gain_trial", "test_speedloop_shadow"])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps({
        "tests": result.testsRun, "passed": result.wasSuccessful(),
        "failures": len(result.failures), "errors": len(result.errors),
        "hardware_accessed": False,
    }, indent=2) + "\n").encode("utf-8"))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
