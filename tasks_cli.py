#!/usr/bin/env python3
"""Convenience entrypoint for the task CLI.

This repo's task CLI lives in `scripts/tasks_cli.py`, but some environments and docs
expect `python tasks_cli.py ...` from the repo root.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    cli_path = Path(__file__).parent / "scripts" / "tasks_cli.py"
    runpy.run_path(str(cli_path), run_name="__main__")


if __name__ == "__main__":
    main()
