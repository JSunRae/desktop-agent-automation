#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SANDBOX_SELF_TEST_REPO = "desktop-agent-automation"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation.orchestration_v1.loop import build_default_loop  # noqa: E402
from automation.orchestration_v1.vscode_pilot import (  # noqa: E402
    build_window_preflight,
    dispatch_prompt_to_repo_window,
    poll_worker_outcome,
    prepare_explicit_fallback_targeting,
)


def _strict_reason_code(*, decision: str | None, report_status: str | None, pilot: dict | None) -> str:
    if decision == "accept":
        return "accepted"
    if decision == "wait":
        return "waiting_for_response"

    diagnostics = (pilot or {}).get("response_diagnostics") if isinstance(pilot, dict) else {}
    primary_rejection = diagnostics.get("primary_rejection", {}) if isinstance(diagnostics, dict) else {}
    primary_reason = str(primary_rejection.get("reason") or "").strip().upper()
    pilot_status = str((pilot or {}).get("status") or "").strip().lower()
    pilot_reason = str((pilot or {}).get("reason") or "").strip().lower()
    parse_mode = str((pilot or {}).get("parse_mode") or "").strip().lower()
    source = str((pilot or {}).get("source") or "").strip().lower()

    if pilot_status == "timeout" or source == "timeout":
        return "response_timeout"
    if parse_mode == "strict_failed_parse":
        if primary_reason == "E_AMBIGUOUS_REPO_WINDOW":
            return "ambiguous_repo_window"
        if primary_reason in {"E_DUPLICATE_CANDIDATE", "E_CONFLICTING_CANDIDATE"}:
            return "conflicting_response_candidates"
        if primary_reason.startswith("E_SANDBOX_"):
            return "sandbox_contract_rejected"
        return "strict_contract_rejected"
    if parse_mode == "failed_parse" or source == "malformed_report":
        return "malformed_response"
    if pilot_status == "duplicate_ignored":
        return "duplicate_completion_ignored"
    if pilot_status == "failed" and pilot_reason:
        return f"pilot_{pilot_reason}"
    if report_status == "partial" or decision == "follow_up":
        return "partial_response"
    if report_status == "blocked" or decision == "escalate":
        return "blocked_response"
    if report_status == "failed" or decision == "stop":
        return "failed_response"
    return "undetermined"


def _build_strict_response_payload(*, payload: dict, pilot_payload: dict | None) -> dict:
    decision = payload.get("decision")
    report_status = payload.get("report_status")
    verdict = "accepted" if decision == "accept" else ("pending" if decision == "wait" else "rejected")
    reason_code = _strict_reason_code(decision=decision, report_status=report_status, pilot=pilot_payload)
    diagnostics = (pilot_payload or {}).get("response_diagnostics") if isinstance(pilot_payload, dict) else {}
    rejected_candidates = diagnostics.get("rejected_candidates", []) if isinstance(diagnostics, dict) else []
    rejection_counts = diagnostics.get("rejection_counts_by_reason", {}) if isinstance(diagnostics, dict) else {}
    waiting_status = diagnostics.get("waiting_status", {}) if isinstance(diagnostics, dict) else {}
    primary_rejection = diagnostics.get("primary_rejection", {}) if isinstance(diagnostics, dict) else {}
    operator_guidance = diagnostics.get("operator_guidance", {}) if isinstance(diagnostics, dict) else {}
    top_reject = None
    if isinstance(primary_rejection, dict) and primary_rejection.get("reason"):
        top_reject = primary_rejection.get("reason")
    elif isinstance(rejection_counts, dict) and rejection_counts:
        top_reject = max(rejection_counts.items(), key=lambda item: int(item[1] or 0))[0]
    return {
        "mode": "strict",
        "verdict": verdict,
        "reason_code": reason_code,
        "reason": payload.get("decision_reason"),
        "decision": decision,
        "report_status": report_status,
        "source": (pilot_payload or {}).get("source"),
        "parse_mode": (pilot_payload or {}).get("parse_mode"),
        "malformed_seen": (pilot_payload or {}).get("malformed_seen"),
        "channels_polled": diagnostics.get("channels_polled") if isinstance(diagnostics, dict) else None,
        "candidate_count": diagnostics.get("candidate_count") if isinstance(diagnostics, dict) else None,
        "rejected_count": len(rejected_candidates) if isinstance(rejected_candidates, list) else 0,
        "top_reject_reason": top_reject,
        "primary_reject_reason": primary_rejection.get("reason") if isinstance(primary_rejection, dict) else None,
        "primary_hint_code": primary_rejection.get("hint_code") if isinstance(primary_rejection, dict) else None,
        "primary_hint_text": primary_rejection.get("hint_text") if isinstance(primary_rejection, dict) else None,
        "operator_action": (operator_guidance.get("recommended_actions") or [None])[0]
        if isinstance(operator_guidance, dict)
        else None,
        "operator_next_step": operator_guidance.get("next_step") if isinstance(operator_guidance, dict) else None,
        "waiting_state": waiting_status.get("state") if isinstance(waiting_status, dict) else None,
    }


def _format_strict_response_line(strict_payload: dict) -> str:
    channels = strict_payload.get("channels_polled") or []
    channels_str = ",".join(str(x) for x in channels) if isinstance(channels, list) and channels else "none"
    return (
        "strict_response "
        f"verdict={strict_payload.get('verdict')} "
        f"reason_code={strict_payload.get('reason_code')} "
        f"decision={strict_payload.get('decision')} "
        f"report_status={strict_payload.get('report_status')} "
        f"source={strict_payload.get('source')} "
        f"parse_mode={strict_payload.get('parse_mode')} "
        f"channels={channels_str} "
        f"candidates={strict_payload.get('candidate_count')} "
        f"rejected={strict_payload.get('rejected_count')} "
        f"top_reject={strict_payload.get('top_reject_reason')} "
        f"primary_hint={strict_payload.get('primary_hint_code')} "
        f"waiting_state={strict_payload.get('waiting_state')} "
        f"next_step={strict_payload.get('operator_next_step')}"
    )


def _known_good_strict_appendix(*, run_id: str, repo_id: str, report_root: Path) -> str:
    report_candidate_1 = report_root / f"{run_id}.md"
    report_candidate_2 = report_root / repo_id / f"{run_id}.md"
    payload = {
        "protocol": "pilot_response_v1",
        "run_id": run_id,
        "repo_id": repo_id,
        "status": "partial",
        "summary": "ACK: scoped task received. Strict triage summary attached.",
        "body": {
            "files_changed": [],
            "validation_run": [
                {
                    "command": "not_run_in_first_reply",
                    "result": "not_run",
                    "notes": "strict_first_reply_mode",
                }
            ],
            "blockers": [],
            "risks": [],
            "next_recommended_actions": [],
        },
        "handover_written_to": "",
    }
    return (
        "\n\n"
        "STRICT FIRST-REPLY KNOWN-GOOD MODE\n"
        "Goal: maximize first accepted strict round-trip with low risk and minimal ambiguity.\n"
        "Do not edit files in this mode. Do not run heavy commands.\n"
        "Prefer writing your strict marker-framed response to one of these report files:\n"
        f"- {report_candidate_1}\n"
        f"- {report_candidate_2}\n"
        "If file write is unavailable, return the same strict payload in chat output with no extra text.\n"
        "Output exactly three blocks only (START marker, one JSON object, END marker).\n"
        f"[[DAA_PILOT_RESPONSE_V1|START|run_id={run_id}|repo_id={repo_id}]]\n"
        f"{json.dumps(payload, separators=(',', ':'))}\n"
        f"[[DAA_PILOT_RESPONSE_V1|END|run_id={run_id}|repo_id={repo_id}]]\n"
    )


def _sandbox_self_test_run_id() -> str:
    return "sandbox-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sandbox_report_paths(*, run_id: str, repo_id: str, report_root: Path) -> list[Path]:
    return [
        report_root / f"{run_id}.md",
        report_root / repo_id / f"{run_id}.md",
    ]


def _prepare_sandbox_report_paths(*, run_id: str, repo_id: str, report_root: Path) -> list[str]:
    paths = _sandbox_report_paths(run_id=run_id, repo_id=repo_id, report_root=report_root)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    return [str(path.resolve(strict=False)) for path in paths]


def _sandbox_self_test_prompt(*, run_id: str, report_root: Path) -> str:
    repo_id = _SANDBOX_SELF_TEST_REPO
    return (
        "SANDBOX SELF-TEST MODE (OPERATOR-OPT-IN)\n"
        "This is a safety-only strict round-trip self-test.\n"
        "Do not edit code, do not mutate non-report files, and do not run write operations.\n"
        "Return triage-only strict payload with status partial or blocked.\n"
        "validation_run entries must be not_run only and files_changed must be empty.\n"
        + _known_good_strict_appendix(run_id=run_id, repo_id=repo_id, report_root=report_root)
    )


def _print_preflight_plain(preflight: dict) -> None:
    summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    enum_diag = preflight.get("window_enumeration_diagnostics", {}) if isinstance(preflight, dict) else {}
    enum_summary = enum_diag.get("summary", {}) if isinstance(enum_diag, dict) else {}
    print("V1 pilot preflight complete")
    print(f"- windows_total: {summary.get('windows_total')}")
    print(f"- repos_total: {summary.get('repos_total')}")
    print(f"- repos_eligible: {summary.get('repos_eligible')}")
    print(f"- windows_omitted_from_uia: {enum_summary.get('windows_omitted_from_uia')}")

    windows = preflight.get("windows_discovered", []) if isinstance(preflight, dict) else []
    print("- discovered_windows:")
    if not windows:
        print("  (none)")
    for row in windows:
        if not isinstance(row, dict):
            continue
        print(
            "  "
            f"[{row.get('window_index')}] id={row.get('window_id')} "
            f"parsed_repo={row.get('parsed_repo')} "
            f"title={row.get('title')}"
        )

    repos = preflight.get("repo_diagnostics", []) if isinstance(preflight, dict) else []
    print("- repo_matchability:")
    if not repos:
        print("  (none)")
    for row in repos:
        if not isinstance(row, dict):
            continue
        sel = row.get("selection", {}) if isinstance(row.get("selection"), dict) else {}
        info = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
        guidance = row.get("operator_guidance", {}) if isinstance(row.get("operator_guidance"), dict) else {}
        print(
            "  "
            f"repo={row.get('repo_id')} "
            f"eligible={info.get('eligible_for_dispatch')} "
            f"matched={info.get('matched_windows')} "
            f"reason={sel.get('reason_code')} "
            f"selected_window_id={sel.get('selected_window_id')}"
        )
        if guidance:
            print(f"    guidance={guidance.get('summary')}")
            for step in guidance.get("recommended_actions", []):
                print(f"    action={step}")
            for command in guidance.get("exact_target_commands", []):
                if not isinstance(command, dict):
                    continue
                if command.get("window_id"):
                    print(
                        "    "
                        f"candidate window_id={command.get('window_id')} "
                        f"title={command.get('title')}"
                    )
                if command.get("readiness_command"):
                    print(f"    readiness_command={command.get('readiness_command')}")
                if command.get("dry_run_command"):
                    print(f"    dry_run_command={command.get('dry_run_command')}")
                if command.get("preflight_command"):
                    print(f"    preflight_command={command.get('preflight_command')}")


def _print_readiness_plain(payload: dict) -> None:
    readiness = payload.get("dispatch_readiness", {}) if isinstance(payload, dict) else {}
    fg = readiness.get("foreground", {}) if isinstance(readiness, dict) else {}
    guidance = payload.get("operator_guidance") if isinstance(payload, dict) else None
    print("V1 pilot readiness-only probe complete")
    print(f"- repo_id: {payload.get('repo_id')}")
    print(f"- selected_window_id: {payload.get('selected_window_id')}")
    print(f"- selected_window_title: {payload.get('selected_window_title')}")
    print(f"- ready_to_send: {payload.get('ready_to_send')}")
    print(f"- reason_code: {readiness.get('reason_code')}")
    print(f"- foreground_after: {fg.get('after')}")
    if isinstance(guidance, dict):
        print("- recommended_actions:")
        for step in guidance.get("recommended_actions", []):
            print(f"  - {step}")


def _print_repo_targeted_dry_run_plain(payload: dict) -> None:
    guidance = payload.get("operator_guidance") if isinstance(payload, dict) else None
    print("V1 pilot repo-targeted dry-run complete")
    print(f"- repo_id: {payload.get('repo_id')}")
    print(f"- selected_window_id: {payload.get('selected_window_id')}")
    print(f"- selected_window_title: {payload.get('selected_window_title')}")
    print(f"- targetable: {payload.get('targetable')}")
    print(f"- reason: {payload.get('reason')}")
    if isinstance(guidance, dict):
        print("- recommended_actions:")
        for step in guidance.get("recommended_actions", []):
            print(f"  - {step}")


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
    parser.add_argument(
        "--pilot-live-dispatch",
        action="store_true",
        help="Opt-in real pilot: send selected prompt to matching repo VS Code window and poll for outcome.",
    )
    parser.add_argument(
        "--pilot-safe-activate",
        action="store_true",
        help=(
            "Use explicit safe activation/send path: require verified foreground + chat input readiness before send. "
            "Does not enable blind inactive-panel sending."
        ),
    )
    parser.add_argument(
        "--pilot-readiness-only",
        action="store_true",
        help=(
            "Run dispatch-readiness checks for an explicitly selected repo/window and never send text. "
            "Designed for operator foreground/focus verification before live dispatch."
        ),
    )
    parser.add_argument(
        "--pilot-readiness-repo",
        default=None,
        help="Repo id for readiness-only mode.",
    )
    parser.add_argument(
        "--pilot-dry-run",
        action="store_true",
        help="When used with --pilot-live-dispatch, validate targeting without sending text.",
    )
    parser.add_argument(
        "--pilot-dry-run-repo",
        default=None,
        help=(
            "Repo id for direct repo-targeted live dry-run validation. Requires --pilot-live-dispatch and "
            "--pilot-dry-run. This branch validates targeting only and bypasses scheduler selection."
        ),
    )
    parser.add_argument(
        "--pilot-poll-seconds",
        type=int,
        default=180,
        help="Polling window for pilot outcome capture (file first, panel fallback).",
    )
    parser.add_argument(
        "--pilot-no-panel-fallback",
        action="store_true",
        help="Disable panel output fallback; only poll worker report files.",
    )
    parser.add_argument(
        "--pilot-window-index",
        type=int,
        default=None,
        help="1-based index into matched repo windows when multiple are found.",
    )
    parser.add_argument(
        "--pilot-window-id",
        default=None,
        help="Stable window id from preflight diagnostics (for explicit deterministic targeting).",
    )
    parser.add_argument(
        "--pilot-strict-response",
        action="store_true",
        help="Enable strict response contract validation for pilot outcome acceptance.",
    )
    parser.add_argument(
        "--pilot-known-good-strict",
        action="store_true",
        help="Append a deterministic strict-first-reply template and force strict file-first polling defaults.",
    )
    parser.add_argument(
        "--pilot-sandbox-self-test",
        action="store_true",
        help=(
            "Explicit sandbox path for desktop-agent-automation only; bypasses normal loop dispatch and enforces "
            "strict known-good read-only triage acceptance rules."
        ),
    )
    parser.add_argument(
        "--pilot-preflight",
        action="store_true",
        help="Read-only operator preflight: list discovered VS Code windows and repo matchability diagnostics.",
    )
    parser.add_argument(
        "--pilot-preflight-repo",
        default=None,
        help="Limit preflight diagnostics to a single managed repo id.",
    )
    parser.add_argument(
        "--pilot-preflight-all-repos",
        action="store_true",
        help="Evaluate preflight diagnostics for all managed repos.",
    )
    parser.add_argument(
        "--pilot-preflight-timeout",
        type=float,
        default=0.5,
        help="Window discovery timeout used during preflight.",
    )
    parser.add_argument(
        "--pilot-fallback-explicit-target",
        action="store_true",
        help="Operator-invoked fallback: use explicit repo/workspace targeting flow before dispatch.",
    )
    parser.add_argument(
        "--pilot-fallback-repo",
        default=None,
        help="Repo id for explicit fallback targeting.",
    )
    parser.add_argument(
        "--pilot-fallback-workspace-path",
        default=None,
        help="Absolute workspace root path for explicit fallback targeting.",
    )
    parser.add_argument(
        "--pilot-fallback-open-if-missing",
        action="store_true",
        help="When explicit fallback preflight is not ready, open the specified workspace path and rerun preflight.",
    )
    parser.add_argument(
        "--pilot-fallback-open-wait-seconds",
        type=float,
        default=2.0,
        help="Wait time after fallback open attempt before rerunning preflight.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--strict-plain-text",
        action="store_true",
        help="Print one concise strict-response verdict line in plain-text output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_targeted_dry_run_repo = str(args.pilot_dry_run_repo or "").strip()
    if repo_targeted_dry_run_repo and (not args.pilot_live_dispatch or not args.pilot_dry_run):
        payload = {
            "mode": "pilot_repo_targeted_dry_run",
            "error": "repo_targeted_dry_run_requires_live_dispatch_and_dry_run",
            "repo_id": repo_targeted_dry_run_repo,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("V1 pilot repo-targeted dry-run complete")
            print("- error: repo_targeted_dry_run_requires_live_dispatch_and_dry_run")
        return 12
    if args.pilot_fallback_explicit_target and not args.pilot_live_dispatch:
        payload = {
            "mode": "pilot_fallback",
            "error": "fallback_requires_live_dispatch",
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("V1 orchestration cycle complete")
            print("- error: fallback_requires_live_dispatch")
        return 5
    if args.pilot_fallback_explicit_target and (
        not str(args.pilot_fallback_repo or "").strip() or not str(args.pilot_fallback_workspace_path or "").strip()
    ):
        payload = {
            "mode": "pilot_fallback",
            "error": "fallback_requires_repo_and_workspace_path",
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("V1 orchestration cycle complete")
            print("- error: fallback_requires_repo_and_workspace_path")
        return 6
    if repo_targeted_dry_run_repo and args.pilot_fallback_explicit_target:
        payload = {
            "mode": "pilot_repo_targeted_dry_run",
            "error": "repo_targeted_dry_run_does_not_support_fallback",
            "repo_id": repo_targeted_dry_run_repo,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("V1 pilot repo-targeted dry-run complete")
            print("- error: repo_targeted_dry_run_does_not_support_fallback")
        return 13

    loop = build_default_loop(
        registry_path=Path(args.registry) if args.registry else None,
        ledger_path=Path(args.ledger) if args.ledger else None,
        dispatch_root=Path(args.dispatch_root) if args.dispatch_root else None,
        report_root=Path(args.report_root) if args.report_root else None,
    )

    if repo_targeted_dry_run_repo:
        repo_cfg = next(
            (r for r in loop.registry.repos if r.repo_id.strip().lower() == repo_targeted_dry_run_repo.lower()),
            None,
        )
        if repo_cfg is None:
            payload = {
                "mode": "pilot_repo_targeted_dry_run",
                "error": "repo_not_found",
                "repo_id": repo_targeted_dry_run_repo,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 pilot repo-targeted dry-run complete")
                print(f"- error: repo_not_found ({repo_targeted_dry_run_repo})")
            return 11

        probe = dispatch_prompt_to_repo_window(
            repo_id=repo_cfg.repo_id,
            repo_root=repo_cfg.root_path,
            prompt_text="",
            dry_run=True,
            window_index=args.pilot_window_index,
            window_id=str(args.pilot_window_id or "").strip(),
            safe_activate=bool(args.pilot_safe_activate),
        )
        operator_guidance = probe.diagnostics.get("operator_guidance") if isinstance(probe.diagnostics, dict) else None
        payload = {
            "mode": "pilot_repo_targeted_dry_run",
            "scope": "targeting_only",
            "repo_id": repo_cfg.repo_id,
            "repo_root": repo_cfg.root_path,
            "selected_window_id": probe.selected_window_id,
            "selected_window_title": probe.selected_window_title,
            "targetable": bool(probe.success),
            "reason": probe.reason,
            "operator_guidance": operator_guidance,
            "window_match_diagnostics": probe.diagnostics,
            "note": (
                "Repo-targeted live dry-run validates repo/window selection only. It does not exercise scheduler "
                "selection, allowlist checks, concurrency gates, prompt generation, or ledger dispatch."
            ),
            "next_step": (
                "run_readiness_only_then_scheduler_backed_live_dispatch"
                if probe.success
                else "follow_operator_guidance_or_rerun_preflight"
            ),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _print_repo_targeted_dry_run_plain(payload)
        return 0 if probe.success else 2

    if args.pilot_readiness_only:
        repo_id = str(args.pilot_readiness_repo or "").strip()
        if not repo_id:
            payload = {
                "mode": "pilot_readiness_only",
                "error": "readiness_requires_repo",
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 pilot readiness-only probe complete")
                print("- error: readiness_requires_repo")
            return 9
        if not str(args.pilot_window_id or "").strip():
            payload = {
                "mode": "pilot_readiness_only",
                "error": "readiness_requires_window_id",
                "repo_id": repo_id,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 pilot readiness-only probe complete")
                print(f"- repo_id: {repo_id}")
                print("- error: readiness_requires_window_id")
            return 10

        repo_cfg = next((r for r in loop.registry.repos if r.repo_id.strip().lower() == repo_id.lower()), None)
        if repo_cfg is None:
            payload = {
                "mode": "pilot_readiness_only",
                "error": "repo_not_found",
                "repo_id": repo_id,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 pilot readiness-only probe complete")
                print(f"- error: repo_not_found ({repo_id})")
            return 11

        probe = dispatch_prompt_to_repo_window(
            repo_id=repo_cfg.repo_id,
            repo_root=repo_cfg.root_path,
            prompt_text="",
            dry_run=False,
            window_index=args.pilot_window_index,
            window_id=str(args.pilot_window_id or "").strip(),
            safe_activate=True,
            readiness_only=True,
        )
        readiness = probe.diagnostics.get("dispatch_readiness") if isinstance(probe.diagnostics, dict) else None
        operator_guidance = None
        if isinstance(readiness, dict):
            operator_guidance = readiness.get("operator_guidance")
        if not isinstance(operator_guidance, dict) and isinstance(probe.diagnostics, dict):
            operator_guidance = probe.diagnostics.get("operator_guidance")

        payload = {
            "mode": "pilot_readiness_only",
            "repo_id": repo_cfg.repo_id,
            "repo_root": repo_cfg.root_path,
            "selected_window_id": probe.selected_window_id,
            "selected_window_title": probe.selected_window_title,
            "ready_to_send": bool(probe.success),
            "reason": probe.reason,
            "dispatch_readiness": readiness,
            "operator_guidance": operator_guidance,
            "window_match_diagnostics": probe.diagnostics,
            "next_step": (
                "run_live_dispatch"
                if probe.success
                else "bring_selected_window_foreground_click_input_rerun_readiness_then_live_dispatch"
            ),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _print_readiness_plain(payload)
        return 0 if probe.success else 2

    if args.pilot_preflight:
        repos = loop.registry.repos
        if args.pilot_preflight_repo:
            requested = str(args.pilot_preflight_repo).strip().lower()
            repos = [repo for repo in repos if repo.repo_id.strip().lower() == requested]
            if not repos:
                payload = {
                    "mode": "pilot_preflight",
                    "error": "repo_not_found",
                    "requested_repo": args.pilot_preflight_repo,
                }
                if args.json:
                    print(json.dumps(payload, indent=2))
                else:
                    print("V1 pilot preflight complete")
                    print(f"- error: repo_not_found ({args.pilot_preflight_repo})")
                return 4
        elif not args.pilot_preflight_all_repos and loop.registry.repos:
            repos = list(loop.registry.repos)

        window_index_by_repo = {}
        window_id_by_repo = {}
        if args.pilot_window_index is not None and len(repos) == 1:
            window_index_by_repo[repos[0].repo_id.strip().lower()] = args.pilot_window_index
        if args.pilot_window_id and len(repos) == 1:
            window_id_by_repo[repos[0].repo_id.strip().lower()] = str(args.pilot_window_id).strip()

        preflight = build_window_preflight(
            repo_targets=[(repo.repo_id, repo.root_path) for repo in repos],
            window_index_by_repo=window_index_by_repo,
            window_id_by_repo=window_id_by_repo,
            timeout=max(0.1, float(args.pilot_preflight_timeout)),
        )
        if args.json:
            print(json.dumps(preflight, indent=2))
        else:
            _print_preflight_plain(preflight)
        summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
        windows_total = int(summary.get("windows_total", 0) or 0)
        repos_total = int(summary.get("repos_total", 0) or 0)
        repos_eligible = int(summary.get("repos_eligible", 0) or 0)
        if windows_total == 0:
            return 3
        if repos_eligible < repos_total:
            return 2
        return 0

    if args.pilot_sandbox_self_test:
        if not args.pilot_live_dispatch:
            payload = {
                "mode": "pilot_sandbox_self_test",
                "error": "sandbox_requires_live_dispatch",
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 orchestration cycle complete")
                print("- error: sandbox_requires_live_dispatch")
            return 7
        if not str(args.pilot_window_id or "").strip():
            payload = {
                "mode": "pilot_sandbox_self_test",
                "error": "sandbox_requires_window_id",
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 orchestration cycle complete")
                print("- error: sandbox_requires_window_id")
            return 8

        report_root = Path(args.report_root) if args.report_root else (_REPO_ROOT / "state" / "orchestration" / "worker_reports")
        run_id = _sandbox_self_test_run_id()
        allowed_report_paths = _prepare_sandbox_report_paths(
            run_id=run_id,
            repo_id=_SANDBOX_SELF_TEST_REPO,
            report_root=report_root,
        )
        prompt_text = _sandbox_self_test_prompt(run_id=run_id, report_root=report_root)

        dispatch_result = dispatch_prompt_to_repo_window(
            repo_id=_SANDBOX_SELF_TEST_REPO,
            repo_root=str(_REPO_ROOT),
            prompt_text=prompt_text,
            dry_run=bool(args.pilot_dry_run),
            window_index=args.pilot_window_index,
            window_id=str(args.pilot_window_id or "").strip(),
            safe_activate=bool(args.pilot_safe_activate),
        )

        if not dispatch_result.success:
            payload = {
                "run_id": run_id,
                "selected_work_item": None,
                "selected_repo": _SANDBOX_SELF_TEST_REPO,
                "decision": "stop",
                "decision_reason": f"Pilot sandbox dispatch failed: {dispatch_result.reason}",
                "report_status": None,
                "notes": ["Sandbox dispatch failed"],
                "diagnostics": {"sandbox_mode": True, "window_id_required": True, "known_good_mode": True},
                "pilot": {
                    "enabled": True,
                    "sandbox_mode": True,
                    "known_good_mode": True,
                    "status": "failed",
                    "reason": dispatch_result.reason,
                    "selected_window_title": dispatch_result.selected_window_title,
                    "selected_window_id": dispatch_result.selected_window_id,
                    "window_match_diagnostics": dispatch_result.diagnostics,
                    "sandbox_allowed_report_paths": allowed_report_paths,
                },
            }
            payload["strict_response"] = _build_strict_response_payload(payload=payload, pilot_payload=payload.get("pilot"))
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 orchestration cycle complete")
                if args.strict_plain_text:
                    print("- " + _format_strict_response_line(payload["strict_response"]))
                for key, value in payload.items():
                    print(f"- {key}: {value}")
            return 0

        if args.pilot_dry_run:
            payload = {
                "run_id": run_id,
                "selected_work_item": None,
                "selected_repo": _SANDBOX_SELF_TEST_REPO,
                "decision": "stop",
                "decision_reason": "Pilot sandbox dry-run completed without sending prompt",
                "report_status": None,
                "notes": ["Sandbox dry-run completed"],
                "diagnostics": {"sandbox_mode": True, "window_id_required": True, "known_good_mode": True},
                "pilot": {
                    "enabled": True,
                    "sandbox_mode": True,
                    "known_good_mode": True,
                    "status": "dry_run",
                    "reason": dispatch_result.reason,
                    "selected_window_title": dispatch_result.selected_window_title,
                    "selected_window_id": dispatch_result.selected_window_id,
                    "window_match_diagnostics": dispatch_result.diagnostics,
                    "sandbox_allowed_report_paths": allowed_report_paths,
                },
            }
            payload["strict_response"] = _build_strict_response_payload(payload=payload, pilot_payload=payload.get("pilot"))
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("V1 orchestration cycle complete")
                if args.strict_plain_text:
                    print("- " + _format_strict_response_line(payload["strict_response"]))
                for key, value in payload.items():
                    print(f"- {key}: {value}")
            return 0

        poll_result = poll_worker_outcome(
            run_id=run_id,
            repo_id=_SANDBOX_SELF_TEST_REPO,
            repo_root=str(_REPO_ROOT),
            report_root=report_root,
            poll_seconds=max(0, args.pilot_poll_seconds),
            poll_interval_seconds=max(1, args.poll_interval),
            allow_panel_fallback=False,
            strict_mode=True,
            sandbox_mode=True,
            sandbox_allowed_report_paths=allowed_report_paths,
        )

        if poll_result.report is None:
            decision = "stop"
            decision_reason = "Pilot sandbox did not yield a structured response before timeout"
            report_status = None
            note = "Sandbox response timeout"
            pilot_status = "timeout"
        elif poll_result.source == "malformed_report":
            decision = "stop"
            decision_reason = "Pilot sandbox strict response rejected"
            report_status = poll_result.report.status.value
            note = "Sandbox strict response rejected"
            pilot_status = "failed"
        else:
            decision = "accept"
            decision_reason = "Pilot sandbox strict response accepted"
            report_status = poll_result.report.status.value
            note = "Sandbox strict response accepted"
            pilot_status = "completed"

        payload = {
            "run_id": run_id,
            "selected_work_item": None,
            "selected_repo": _SANDBOX_SELF_TEST_REPO,
            "decision": decision,
            "decision_reason": decision_reason,
            "report_status": report_status,
            "notes": [note],
            "diagnostics": {
                "sandbox_mode": True,
                "window_id_required": True,
                "known_good_mode": True,
                "sandbox_allowed_report_paths": allowed_report_paths,
            },
            "pilot": {
                "enabled": True,
                "sandbox_mode": True,
                "known_good_mode": True,
                "status": pilot_status,
                "source": poll_result.source,
                "report_path": poll_result.report_path,
                "parse_mode": poll_result.parse_mode,
                "elapsed_ms": poll_result.elapsed_ms,
                "malformed_seen": poll_result.malformed_seen,
                "response_diagnostics": poll_result.response_diagnostics,
                "selected_window_title": dispatch_result.selected_window_title,
                "selected_window_id": dispatch_result.selected_window_id,
                "window_match_diagnostics": dispatch_result.diagnostics,
                "sandbox_allowed_report_paths": allowed_report_paths,
            },
        }
        payload["strict_response"] = _build_strict_response_payload(payload=payload, pilot_payload=payload.get("pilot"))

        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("V1 orchestration cycle complete")
            if args.strict_plain_text:
                print("- " + _format_strict_response_line(payload["strict_response"]))
            for key, value in payload.items():
                print(f"- {key}: {value}")
        return 0

    effective_poll = -1 if args.pilot_live_dispatch else args.poll_seconds
    result = loop.run_once(poll_seconds=effective_poll, poll_interval_seconds=args.poll_interval)

    pilot_payload = None
    if args.pilot_live_dispatch and result.run_id and result.selected_work_item:
        repo_cfg = loop.repo_index.get(result.selected_work_item.repo.lower())
        dispatch_root = Path(args.dispatch_root) if args.dispatch_root else (_REPO_ROOT / "state" / "orchestration" / "dispatch_queue")
        report_root = Path(args.report_root) if args.report_root else (_REPO_ROOT / "state" / "orchestration" / "worker_reports")
        prompt_path = dispatch_root / result.selected_work_item.repo / f"{result.run_id}.prompt.md"
        fallback_diag = None

        if not prompt_path.is_file():
            decision = loop.record_stopped(
                run_id=result.run_id,
                selected=result.selected_work_item,
                reason_code="dispatch_prompt_missing",
                decision_reason="Pilot dispatch prompt file missing",
                extra_payload={"prompt_path": str(prompt_path)},
            )
            result.decision = decision
            pilot_payload = {
                "enabled": True,
                "status": "failed",
                "reason": "dispatch_prompt_missing",
                "prompt_path": str(prompt_path),
            }
        else:
            prompt_text = prompt_path.read_text(encoding="utf-8", errors="ignore")
            if args.pilot_known_good_strict:
                prompt_text += _known_good_strict_appendix(
                    run_id=result.run_id,
                    repo_id=result.selected_work_item.repo,
                    report_root=report_root,
                )

            effective_window_index = args.pilot_window_index
            effective_window_id = args.pilot_window_id
            if args.pilot_fallback_explicit_target:
                selected_repo = str(result.selected_work_item.repo or "").strip().lower()
                fallback_repo = str(args.pilot_fallback_repo or "").strip().lower()
                if selected_repo != fallback_repo:
                    decision = loop.record_stopped(
                        run_id=result.run_id,
                        selected=result.selected_work_item,
                        reason_code="fallback_repo_mismatch",
                        decision_reason="Fallback repo does not match selected dispatch repo",
                        extra_payload={
                            "selected_repo": result.selected_work_item.repo,
                            "fallback_repo": args.pilot_fallback_repo,
                        },
                    )
                    result.decision = decision
                    result.notes.append(decision.reason)
                    pilot_payload = {
                        "enabled": True,
                        "status": "failed",
                        "reason": "fallback_repo_mismatch",
                        "fallback_targeting": {
                            "repo": args.pilot_fallback_repo,
                            "workspace_path": args.pilot_fallback_workspace_path,
                        },
                    }
                else:
                    fallback_diag = prepare_explicit_fallback_targeting(
                        repo_id=result.selected_work_item.repo,
                        repo_root=repo_cfg.root_path if repo_cfg else None,
                        workspace_path=str(args.pilot_fallback_workspace_path),
                        window_index=args.pilot_window_index,
                        window_id=args.pilot_window_id,
                        preflight_timeout=max(0.1, float(args.pilot_preflight_timeout)),
                        open_if_missing=bool(args.pilot_fallback_open_if_missing),
                        open_wait_seconds=max(0.0, float(args.pilot_fallback_open_wait_seconds)),
                    )
                    effective_window_id = fallback_diag.get("selected_window_id") or effective_window_id
                    fallback_index_value = fallback_diag.get("selected_window_index")
                    if isinstance(fallback_index_value, int) and fallback_index_value > 0:
                        effective_window_index = fallback_index_value

                    loop.ledger.append(
                        "pilot_fallback_targeting",
                        {
                            "run_id": result.run_id,
                            "repo": result.selected_work_item.repo,
                            "dispatch_allowed": bool(fallback_diag.get("dispatch_allowed")),
                            "reason": fallback_diag.get("reason"),
                            "fallback_targeting": fallback_diag,
                        },
                    )

                    if not bool(fallback_diag.get("dispatch_allowed")):
                        decision = loop.record_stopped(
                            run_id=result.run_id,
                            selected=result.selected_work_item,
                            reason_code="pilot_fallback_rejected",
                            decision_reason=f"Pilot fallback rejected: {fallback_diag.get('reason')}",
                            extra_payload={"fallback_targeting": fallback_diag},
                        )
                        result.decision = decision
                        result.notes.append(decision.reason)
                        pilot_payload = {
                            "enabled": True,
                            "status": "failed",
                            "reason": str(fallback_diag.get("reason") or "pilot_fallback_rejected"),
                            "fallback_targeting": fallback_diag,
                        }

            if result.decision and result.decision.action == "stop":
                dispatch_result = None
            else:
                dispatch_result = dispatch_prompt_to_repo_window(
                    repo_id=result.selected_work_item.repo,
                    repo_root=repo_cfg.root_path if repo_cfg else None,
                    prompt_text=prompt_text,
                    dry_run=bool(args.pilot_dry_run),
                    window_index=effective_window_index,
                    window_id=effective_window_id,
                    safe_activate=bool(args.pilot_safe_activate),
                )
            if dispatch_result is None:
                pass
            else:

                loop.ledger.append(
                    "pilot_live_dispatch",
                    {
                        "run_id": result.run_id,
                        "repo": result.selected_work_item.repo,
                        "dry_run": bool(args.pilot_dry_run),
                        "success": dispatch_result.success,
                        "reason": dispatch_result.reason,
                        "matched_window_titles": dispatch_result.matched_window_titles,
                        "selected_window_title": dispatch_result.selected_window_title,
                        "selected_window_id": dispatch_result.selected_window_id,
                        "window_index": effective_window_index,
                        "window_id": effective_window_id,
                        "safe_activate": bool(args.pilot_safe_activate),
                        "prompt_path": str(prompt_path),
                        "window_match_diagnostics": dispatch_result.diagnostics,
                        "fallback_targeting": fallback_diag,
                    },
                )

            if dispatch_result is None:
                pass
            elif not dispatch_result.success:
                decision = loop.record_stopped(
                    run_id=result.run_id,
                    selected=result.selected_work_item,
                    reason_code="pilot_dispatch_failed",
                    decision_reason=f"Pilot dispatch failed: {dispatch_result.reason}",
                    extra_payload={
                        "matched_window_titles": dispatch_result.matched_window_titles,
                        "selected_window_title": dispatch_result.selected_window_title,
                        "selected_window_id": dispatch_result.selected_window_id,
                        "window_match_diagnostics": dispatch_result.diagnostics,
                    },
                )
                result.decision = decision
                result.notes.append(decision.reason)
                pilot_payload = {
                    "enabled": True,
                    "status": "failed",
                    "reason": dispatch_result.reason,
                    "matched_window_titles": dispatch_result.matched_window_titles,
                    "selected_window_title": dispatch_result.selected_window_title,
                    "selected_window_id": dispatch_result.selected_window_id,
                    "dispatch_readiness": dispatch_result.diagnostics.get("dispatch_readiness"),
                    "operator_guidance": dispatch_result.diagnostics.get("operator_guidance"),
                    "window_match_diagnostics": dispatch_result.diagnostics,
                    "fallback_targeting": fallback_diag,
                }
            elif dispatch_result is not None and args.pilot_dry_run:
                decision = loop.record_stopped(
                    run_id=result.run_id,
                    selected=result.selected_work_item,
                    reason_code="pilot_dry_run",
                    decision_reason="Pilot dry-run completed without sending prompt",
                )
                result.decision = decision
                result.notes.append(decision.reason)
                pilot_payload = {
                    "enabled": True,
                    "status": "dry_run",
                    "reason": dispatch_result.reason,
                    "selected_window_title": dispatch_result.selected_window_title,
                    "selected_window_id": dispatch_result.selected_window_id,
                    "window_match_diagnostics": dispatch_result.diagnostics,
                    "fallback_targeting": fallback_diag,
                }
            elif dispatch_result is not None:
                strict_mode_enabled = bool(args.pilot_strict_response or args.pilot_known_good_strict)
                allow_panel_fallback = False if args.pilot_known_good_strict else (not bool(args.pilot_no_panel_fallback))
                poll_result = poll_worker_outcome(
                    run_id=result.run_id,
                    repo_id=result.selected_work_item.repo,
                    repo_root=repo_cfg.root_path if repo_cfg else None,
                    report_root=report_root,
                    poll_seconds=max(0, args.pilot_poll_seconds),
                    poll_interval_seconds=max(1, args.poll_interval),
                    allow_panel_fallback=allow_panel_fallback,
                    strict_mode=strict_mode_enabled,
                )

                loop.ledger.append(
                    "pilot_worker_response",
                    {
                        "run_id": result.run_id,
                        "repo": result.selected_work_item.repo,
                        "source": poll_result.source,
                        "report_path": poll_result.report_path,
                        "parse_mode": poll_result.parse_mode,
                        "elapsed_ms": poll_result.elapsed_ms,
                        "malformed_seen": poll_result.malformed_seen,
                        "known_good_mode": bool(args.pilot_known_good_strict),
                        "response_diagnostics": poll_result.response_diagnostics,
                    },
                )

                if poll_result.report is None:
                    decision = loop.record_stopped(
                        run_id=result.run_id,
                        selected=result.selected_work_item,
                        reason_code="pilot_response_timeout",
                        decision_reason="Pilot dispatch did not yield a structured response before timeout",
                        extra_payload={
                            "elapsed_ms": poll_result.elapsed_ms,
                            "source": poll_result.source,
                            "response_diagnostics": poll_result.response_diagnostics,
                        },
                    )
                    result.decision = decision
                    result.notes.append(decision.reason)
                    pilot_payload = {
                        "enabled": True,
                        "known_good_mode": bool(args.pilot_known_good_strict),
                        "status": "timeout",
                        "source": poll_result.source,
                        "parse_mode": poll_result.parse_mode,
                        "elapsed_ms": poll_result.elapsed_ms,
                        "malformed_seen": poll_result.malformed_seen,
                        "response_diagnostics": poll_result.response_diagnostics,
                        "fallback_targeting": fallback_diag,
                    }
                else:
                    if loop.ledger.has_terminal_event(result.run_id):
                        decision = loop.record_stopped(
                            run_id=result.run_id,
                            selected=result.selected_work_item,
                            reason_code="duplicate_completion_ignored",
                            decision_reason="Duplicate completion ignored for terminal run",
                            extra_payload={"source": poll_result.source},
                        )
                        result.decision = decision
                        result.notes.append(decision.reason)
                        pilot_payload = {
                            "enabled": True,
                            "known_good_mode": bool(args.pilot_known_good_strict),
                            "status": "duplicate_ignored",
                            "source": poll_result.source,
                            "parse_mode": poll_result.parse_mode,
                            "elapsed_ms": poll_result.elapsed_ms,
                            "malformed_seen": poll_result.malformed_seen,
                            "response_diagnostics": poll_result.response_diagnostics,
                            "decision": decision.action,
                            "fallback_targeting": fallback_diag,
                        }
                    else:
                        decision = loop.record_report_and_decision(
                            run_id=result.run_id,
                            selected=result.selected_work_item,
                            report=poll_result.report,
                            response_meta={
                                "source": poll_result.source,
                                "report_path": poll_result.report_path,
                                "parse_mode": poll_result.parse_mode,
                                "elapsed_ms": poll_result.elapsed_ms,
                                "malformed_seen": poll_result.malformed_seen,
                                "response_diagnostics": poll_result.response_diagnostics,
                            },
                        )
                        result.report = poll_result.report
                        result.decision = decision
                        result.notes.append(f"Pilot response captured from {poll_result.source}")
                        pilot_payload = {
                            "enabled": True,
                            "known_good_mode": bool(args.pilot_known_good_strict),
                            "status": "completed",
                            "source": poll_result.source,
                            "report_path": poll_result.report_path,
                            "parse_mode": poll_result.parse_mode,
                            "elapsed_ms": poll_result.elapsed_ms,
                            "malformed_seen": poll_result.malformed_seen,
                            "response_diagnostics": poll_result.response_diagnostics,
                            "decision": decision.action,
                            "fallback_targeting": fallback_diag,
                        }

    payload = {
        "run_id": result.run_id,
        "selected_work_item": result.selected_work_item.work_item_id if result.selected_work_item else None,
        "selected_repo": result.selected_work_item.repo if result.selected_work_item else None,
        "decision": result.decision.action if result.decision else None,
        "decision_reason": result.decision.reason if result.decision else None,
        "report_status": result.report.status.value if result.report else None,
        "notes": result.notes,
        "diagnostics": result.diagnostics,
        "pilot": pilot_payload,
    }
    payload["strict_response"] = _build_strict_response_payload(payload=payload, pilot_payload=pilot_payload)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("V1 orchestration cycle complete")
        if args.strict_plain_text:
            print("- " + _format_strict_response_line(payload["strict_response"]))
        for key, value in payload.items():
            print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
