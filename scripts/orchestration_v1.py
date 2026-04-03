#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.orchestration_v1.loop import build_default_loop  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestration_v1.py",
        description="Run one controlled V1 orchestration cycle for managed trading repos.",
    )
    parser.add_argument("--registry", help="Path to managed workspace registry JSON")
    parser.add_argument("--ledger", help="Path to append-only orchestration ledger JSONL")
    parser.add_argument("--dispatch-root", help="Directory for dispatch envelopes and worker prompts")
    parser.add_argument("--report-root", help="Directory where worker completion reports are read")
    parser.add_argument("--poll-seconds", type=int, default=0, help="How long to poll for worker report")
    parser.add_argument("--poll-interval", type=int, default=5, help="Polling interval in seconds")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    loop = build_default_loop(
        registry_path=Path(args.registry) if args.registry else None,
        ledger_path=Path(args.ledger) if args.ledger else None,
        dispatch_root=Path(args.dispatch_root) if args.dispatch_root else None,
        report_root=Path(args.report_root) if args.report_root else None,
    )
    result = loop.run_once(poll_seconds=args.poll_seconds, poll_interval_seconds=args.poll_interval)

    payload = {
        "run_id": result.run_id,
        "selected_work_item": result.selected_work_item.work_item_id if result.selected_work_item else None,
        "selected_repo": result.selected_work_item.repo if result.selected_work_item else None,
        "decision": result.decision.action if result.decision else None,
        "decision_reason": result.decision.reason if result.decision else None,
        "report_status": result.report.status.value if result.report else None,
        "notes": result.notes,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("V1 orchestration cycle complete")
        for key, value in payload.items():
            print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
