#!/usr/bin/env python3
"""Panel inspection and coordination test runner.

A thin CLI wrapper around tests/test_panel_coordination.py that can be
invoked directly or wired into the master CLI.

Usage
-----
  python scripts/panel_inspect.py                      # all suites, dry-run
  python scripts/panel_inspect.py --suite scan         # scanner only
  python scripts/panel_inspect.py --suite overlap      # overlap only
  python scripts/panel_inspect.py --suite response     # response controls
  python scripts/panel_inspect.py --suite refresh      # refresh controls
  python scripts/panel_inspect.py --target-repo TF     # focus on TF windows
  python scripts/panel_inspect.py --live-click         # CAUTION: actually clicks
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Delegate entirely to the test module's main entry point.
from tests.test_panel_coordination import _parse_args, run_all  # noqa: E402


def main(argv=None) -> int:
    args = _parse_args()
    return run_all(args)


if __name__ == "__main__":
    sys.exit(main())
