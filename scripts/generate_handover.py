#!/usr/bin/env python3
"""Generate a handover document prompt for one or more repos.

The handover prompt contains:
  - North Star goal and repo boundaries
  - In-progress / P0 tasks from the trading-system ledger
  - Overlap / drift coordination warnings
  - A live transcript snippet from the relevant VS Code panel (if open)
  - Optional AI summary (requires OPENAI_API_KEY)

Usage
-----
  python scripts/generate_handover.py --repo Trading
  python scripts/generate_handover.py --repo TF --summarise
  python scripts/generate_handover.py --all-repos
  python scripts/generate_handover.py --all-repos --out handover.md
  python scripts/generate_handover.py --repo contracts --no-transcript
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.handover_prompt_builder import (  # noqa: E402
    build_all_handover_prompts,
    build_handover_prompt,
)

_KNOWN_REPOS = ["contracts", "TF", "Trading", "desktop-agent-automation"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate agent handover prompt(s)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--repo",
        choices=_KNOWN_REPOS,
        help="Generate handover for a single repo.",
    )
    group.add_argument(
        "--all-repos",
        action="store_true",
        help="Generate handover for all repos (contracts → TF → Trading → desktop-agent-automation).",
    )
    p.add_argument(
        "--summarise",
        action="store_true",
        default=False,
        help="Use OpenAI to summarise the panel transcript (requires OPENAI_API_KEY).",
    )
    p.add_argument(
        "--no-transcript",
        action="store_true",
        default=False,
        help="Skip live transcript reading (faster, headless-safe).",
    )
    p.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help="Save output to FILE instead of printing to stdout.",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    include_transcript = not args.no_transcript

    if args.all_repos:
        output = build_all_handover_prompts(
            include_transcript=include_transcript,
            summarise=args.summarise,
        )
    else:
        output = build_handover_prompt(
            args.repo,
            include_transcript=include_transcript,
            summarise=args.summarise,
        )

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(output, encoding="utf-8")
        print(f"[generate-handover] Written to {out_path.resolve()}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
