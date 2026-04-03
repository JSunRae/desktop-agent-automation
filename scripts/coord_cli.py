#!/usr/bin/env python3
"""Coordination CLI dashboard.

Gives you a real-time view of all active tasks across TF, contracts, and Trading,
highlights overlaps and drift, and lets you run a quick North Star alignment check
on any text you paste.

Commands
--------
  status          Print the full cross-repo coordination report.
  north-star      Print the current North Star goal and context.
  check <text>    Run the coordination guard against the given text/prompt.
  refresh         Force-refresh the North Star and ledger caches.
  tasks [--repo]  List active tasks, optionally filtered by repo.

Examples
--------
  python scripts/coord_cli.py status
  python scripts/coord_cli.py north-star
  python scripts/coord_cli.py tasks --repo TF
  python scripts/coord_cli.py check "Refactor the data pipeline parquet writer"
  python scripts/coord_cli.py refresh
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

# Ensure the repo root is on sys.path when run directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _print_divider(char: str = "-", width: int = 72) -> None:
    print(char * width)


def _fmt_task(task) -> str:
    status_icon = {
        "in_progress": "[RUNNING]",
        "planned": "[PLANNED]",
        "blocked": "[BLOCKED]",
        "review": "[REVIEW] ",
    }.get(task.status, "[?]     ")
    assignee = f" [{task.assignee_id}]" if task.assignee_id else ""
    note = f"\n     notes: {task.note_preview[:80]}" if task.note_preview else ""
    return (
        f"  {status_icon} [{task.priority}] [{task.repo}] {task.task_id}\n"
        f"     {task.title}{assignee}{note}"
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    from automation.repo_task_ledger import get_ledger_report

    report = get_ledger_report(force_refresh=True)
    print(report.summary_text())
    return 0


def cmd_north_star(args: argparse.Namespace) -> int:
    from automation.north_star import get_north_star

    ns = get_north_star(force_refresh=True)

    _print_divider("=")
    print("NORTH STAR - CURRENT PRIMARY GOAL")
    _print_divider("=")
    print()
    print("Goal:")
    print(textwrap.fill(ns.primary_goal, width=72, initial_indent="  ", subsequent_indent="  "))
    if ns.primary_task_id:
        print(f"\n  Task ID: {ns.primary_task_id}")
    print()
    _print_divider()
    print("Repo Dependency Order:")
    print("  " + " -> ".join(ns.dependency_order))
    print()
    _print_divider()
    print("Repo Roles:")
    for repo in ns.dependency_order:
        role = ns.repo_roles.get(repo)
        if role:
            print(f"\n  {repo}")
            print("  Owns:")
            for own in role.owns:
                print(f"    + {own}")
            print("  Must NOT do:")
            for forbidden in role.must_not_do[:3]:
                print(f"    - {forbidden}")
    print()
    _print_divider()
    print("Routing Summary:")
    print(textwrap.indent(ns.routing_summary[:800], "  "))
    print()
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    from automation.north_star import get_north_star

    ns = get_north_star(force_refresh=True)
    tasks = ns.active_tasks
    if args.repo:
        tasks = [t for t in tasks if t.repo.lower() == args.repo.lower()]

    if not tasks:
        filter_note = f" in {args.repo}" if args.repo else ""
        print(f"No active tasks found{filter_note}.")
        return 0

    _print_divider("=")
    filter_header = f" - {args.repo}" if args.repo else " (all repos)"
    print(f"ACTIVE TASKS{filter_header}  ({len(tasks)} found)")
    _print_divider("=")
    for t in tasks:
        print(_fmt_task(t))
        print()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from automation.coordination_guard import CoordinationGuard

    text = " ".join(args.text or [])
    if not text:
        print("Error: provide text to check.", file=sys.stderr)
        return 1

    guard = CoordinationGuard()
    decision = guard.evaluate(text, target_repo=args.repo or None)

    _print_divider("=")
    print(f"COORDINATION CHECK - {decision.outcome.value.upper()}")
    _print_divider("=")
    print(f"Target repo : {decision.target_repo or '(auto-detected)'}")
    print(f"Alignment   : {decision.alignment_score:.2f}/1.00")
    print()

    if decision.should_block:
        print(f"[BLOCKED] {decision.block_reason}")
    elif decision.should_redirect:
        print(f"[REDIRECT] to '{decision.redirect_to_repo}': {decision.block_reason}")
    else:
        if decision.cautions:
            print("[CAUTIONS]:")
            for c in decision.cautions:
                print(f"   * {c}")
        else:
            print("[OK] Safe to dispatch.")

    if args.verbose and decision.context_prefix:
        print()
        _print_divider()
        print("Context prefix that would be prepended to the prompt:")
        _print_divider()
        print(decision.context_prefix[:1200])
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    from automation.north_star import get_north_star
    from automation.repo_task_ledger import get_ledger_report

    print("Refreshing North Star cache...", end=" ", flush=True)
    get_north_star(force_refresh=True)
    print("done.")

    print("Refreshing ledger report cache...", end=" ", flush=True)
    get_ledger_report(force_refresh=True)
    print("done.")

    print("\nRun 'coord_cli.py status' to see the updated report.")
    return 0


# ---------------------------------------------------------------------------
# CLI bootstrap
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coord_cli.py",
        description="Agent coordination dashboard for TF / contracts / Trading.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="Sub-command to run")
    sub.required = True

    # status
    sub.add_parser("status", help="Full cross-repo coordination report")

    # north-star
    sub.add_parser("north-star", help="Print the current North Star goal")

    # tasks
    tasks_p = sub.add_parser("tasks", help="List active tasks")
    tasks_p.add_argument("--repo", help="Filter by repo name (TF | Trading | contracts)")

    # check
    check_p = sub.add_parser("check", help="Evaluate a prompt/text against the coordination guard")
    check_p.add_argument("text", nargs="*", help="Text to evaluate")
    check_p.add_argument("--repo", help="Target repo for the check")
    check_p.add_argument("--verbose", "-v", action="store_true", help="Show full context prefix")

    # refresh
    sub.add_parser("refresh", help="Force-refresh all caches")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "status": cmd_status,
        "north-star": cmd_north_star,
        "tasks": cmd_tasks,
        "check": cmd_check,
        "refresh": cmd_refresh,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if "--traceback" in (argv or sys.argv):
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
