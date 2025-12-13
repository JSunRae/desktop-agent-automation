"""Backwards-compatible shim for the packaged master launcher."""

from __future__ import annotations

from automation.cli.master import main

if __name__ == "__main__":
    raise SystemExit(main())