"""Legacy wrapper for the panel alignment script.

This file previously contained an incomplete, pasted fragment of
`scripts/align_panels.py` that failed to import/compile.

Keeping this wrapper preserves any external references to
`scripts/align_panels_main_fix.py` while delegating execution to the real
implementation.
"""

from __future__ import annotations

from pathlib import Path
import runpy


def main() -> None:
    runpy.run_path(str(Path(__file__).with_name("align_panels.py")), run_name="__main__")


if __name__ == "__main__":
    main()
