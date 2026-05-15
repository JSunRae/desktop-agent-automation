from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from automation.orchestration_v1.vscode_pilot import PilotDispatchResult

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "orchestration_v1.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("orchestration_v1_cli", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_loop(repo_id: str = "alpha"):
    repo = SimpleNamespace(repo_id=repo_id, root_path=f"C:/repos/{repo_id}")
    return SimpleNamespace(registry=SimpleNamespace(repos=[repo]))


def _fake_loop_with_run_once(repo_id: str = "alpha"):
    repo = SimpleNamespace(repo_id=repo_id, root_path=f"C:/repos/{repo_id}")

    def _unexpected_run_once(**kwargs):
        raise AssertionError("run_once should not be called for repo-targeted dry-run")

    return SimpleNamespace(registry=SimpleNamespace(repos=[repo]), run_once=_unexpected_run_once)


def test_readiness_only_mode_blocked_returns_guidance(monkeypatch, capsys) -> None:
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "build_default_loop", lambda **kwargs: _fake_loop("alpha"))

    probe = PilotDispatchResult(
        success=False,
        reason="dispatch_not_ready",
        repo_id="alpha",
        matched_window_titles=["Chat - alpha - Visual Studio Code"],
        selected_window_title="Chat - alpha - Visual Studio Code",
        selected_window_id="hwnd:601",
        diagnostics={
            "dispatch_readiness": {
                "reason_code": "target_not_foreground",
                "foreground": {"after": False},
                "operator_guidance": {
                    "issue": "target_not_foreground",
                    "recommended_actions": [
                        "Bring the selected window to the front (exact id/title shown above).",
                    ],
                },
            },
            "operator_guidance": {
                "issue": "target_not_foreground",
                "recommended_actions": ["Bring the selected window to the front"],
            },
        },
    )

    def _fake_dispatch(**kwargs):
        assert kwargs["readiness_only"] is True
        assert kwargs["safe_activate"] is True
        return probe

    monkeypatch.setattr(cli, "dispatch_prompt_to_repo_window", _fake_dispatch)

    rc = cli.main(
        [
            "--pilot-readiness-only",
            "--pilot-readiness-repo",
            "alpha",
            "--pilot-window-id",
            "hwnd:601",
            "--json",
        ]
    )

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 2
    assert payload["mode"] == "pilot_readiness_only"
    assert payload["repo_id"] == "alpha"
    assert payload["selected_window_id"] == "hwnd:601"
    assert payload["ready_to_send"] is False
    assert payload["next_step"] == "bring_selected_window_foreground_click_input_rerun_readiness_then_live_dispatch"
    assert payload["operator_guidance"]["issue"] == "target_not_foreground"


def test_readiness_only_mode_ready_returns_zero(monkeypatch, capsys) -> None:
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "build_default_loop", lambda **kwargs: _fake_loop("alpha"))

    probe = PilotDispatchResult(
        success=True,
        reason="readiness_ready",
        repo_id="alpha",
        matched_window_titles=["Chat - alpha - Visual Studio Code"],
        selected_window_title="Chat - alpha - Visual Studio Code",
        selected_window_id="hwnd:602",
        diagnostics={
            "dispatch_readiness": {
                "reason_code": "ready_to_send",
                "foreground": {"after": True},
                "operator_guidance": None,
            },
            "operator_guidance": None,
        },
    )
    monkeypatch.setattr(cli, "dispatch_prompt_to_repo_window", lambda **kwargs: probe)

    rc = cli.main(
        [
            "--pilot-readiness-only",
            "--pilot-readiness-repo",
            "alpha",
            "--pilot-window-id",
            "hwnd:602",
            "--json",
        ]
    )

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["ready_to_send"] is True
    assert payload["next_step"] == "run_live_dispatch"


def test_repo_targeted_dry_run_requires_live_dispatch_and_dry_run(capsys) -> None:
    cli = _load_cli_module()

    rc = cli.main([
        "--pilot-dry-run-repo",
        "alpha",
        "--json",
    ])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 12
    assert payload["mode"] == "pilot_repo_targeted_dry_run"
    assert payload["error"] == "repo_targeted_dry_run_requires_live_dispatch_and_dry_run"


def test_repo_targeted_dry_run_bypasses_scheduler_and_dispatches_by_repo(monkeypatch, capsys) -> None:
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "build_default_loop", lambda **kwargs: _fake_loop_with_run_once("alpha"))

    probe = PilotDispatchResult(
        success=True,
        reason="dry_run",
        repo_id="alpha",
        matched_window_titles=["Task A - alpha - Visual Studio Code"],
        selected_window_title="Task A - alpha - Visual Studio Code",
        selected_window_id="hwnd:603",
        diagnostics={"selection": {"selected_window_id": "hwnd:603"}},
    )

    def _fake_dispatch(**kwargs):
        assert kwargs["repo_id"] == "alpha"
        assert kwargs["repo_root"] == "C:/repos/alpha"
        assert kwargs["prompt_text"] == ""
        assert kwargs["dry_run"] is True
        assert kwargs["window_id"] == "hwnd:603"
        return probe

    monkeypatch.setattr(cli, "dispatch_prompt_to_repo_window", _fake_dispatch)

    rc = cli.main(
        [
            "--pilot-live-dispatch",
            "--pilot-dry-run",
            "--pilot-dry-run-repo",
            "alpha",
            "--pilot-window-id",
            "hwnd:603",
            "--json",
        ]
    )

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["mode"] == "pilot_repo_targeted_dry_run"
    assert payload["scope"] == "targeting_only"
    assert payload["repo_id"] == "alpha"
    assert payload["selected_window_id"] == "hwnd:603"
    assert payload["targetable"] is True
    assert payload["next_step"] == "run_readiness_only_then_scheduler_backed_live_dispatch"


def test_preflight_plain_output_surfaces_exact_target_commands(monkeypatch, capsys) -> None:
    cli = _load_cli_module()
    monkeypatch.setattr(cli, "build_default_loop", lambda **kwargs: _fake_loop("alpha"))
    monkeypatch.setattr(
        cli,
        "build_window_preflight",
        lambda **kwargs: {
            "summary": {"windows_total": 2, "repos_total": 1, "repos_eligible": 0},
            "window_enumeration_diagnostics": {"summary": {"windows_omitted_from_uia": 0}},
            "windows_discovered": [],
            "repo_diagnostics": [
                {
                    "repo_id": "alpha",
                    "summary": {"eligible_for_dispatch": False, "matched_windows": 2},
                    "selection": {
                        "reason_code": "ambiguous_repo_window",
                        "selected_window_id": None,
                    },
                    "operator_guidance": {
                        "summary": "Multiple eligible repo windows share the same best match rank; preflight cannot auto-select one safely.",
                        "recommended_actions": [
                            "Choose one exact window_id from exact_target_commands and rerun readiness-only.",
                        ],
                        "exact_target_commands": [
                            {
                                "window_id": "hwnd:111",
                                "title": "Task A - alpha - Visual Studio Code",
                                "readiness_command": "python scripts\\orchestration_v1.py --pilot-readiness-only --pilot-readiness-repo alpha --pilot-window-id hwnd:111 --json",
                                "dry_run_command": "python scripts\\orchestration_v1.py --pilot-live-dispatch --pilot-dry-run --pilot-dry-run-repo alpha --pilot-window-id hwnd:111 --json",
                            }
                        ],
                    },
                }
            ],
        },
    )

    rc = cli.main(["--pilot-preflight", "--pilot-preflight-repo", "alpha"])

    out = capsys.readouterr().out
    assert rc == 2
    assert "guidance=Multiple eligible repo windows share the same best match rank" in out
    assert "readiness_command=python scripts\\orchestration_v1.py --pilot-readiness-only --pilot-readiness-repo alpha --pilot-window-id hwnd:111 --json" in out
    assert "dry_run_command=python scripts\\orchestration_v1.py --pilot-live-dispatch --pilot-dry-run --pilot-dry-run-repo alpha --pilot-window-id hwnd:111 --json" in out


def test_strict_response_payload_surfaces_primary_rejection_details() -> None:
    cli = _load_cli_module()

    strict_payload = cli._build_strict_response_payload(
        payload={
            "decision": "stop",
            "report_status": "failed",
            "decision_reason": "Pilot strict response rejected",
        },
        pilot_payload={
            "status": "failed",
            "source": "malformed_report",
            "parse_mode": "strict_failed_parse",
            "malformed_seen": True,
            "response_diagnostics": {
                "channels_polled": ["report_file"],
                "candidate_count": 1,
                "rejected_candidates": [{"reason": "E_PAYLOAD_NOT_JSON"}],
                "rejection_counts_by_reason": {"E_PAYLOAD_NOT_JSON": 1},
                "primary_rejection": {
                    "reason": "E_PAYLOAD_NOT_JSON",
                    "hint_code": "payload_not_json",
                    "hint_text": "The content between the markers is not valid JSON near line 1, column 12.",
                },
                "operator_guidance": {
                    "recommended_actions": ["Return one valid JSON object only."],
                    "next_step": "resend_valid_json_object",
                },
                "waiting_status": {"state": "malformed"},
            },
        },
    )

    assert strict_payload["reason_code"] == "strict_contract_rejected"
    assert strict_payload["top_reject_reason"] == "E_PAYLOAD_NOT_JSON"
    assert strict_payload["primary_reject_reason"] == "E_PAYLOAD_NOT_JSON"
    assert strict_payload["primary_hint_code"] == "payload_not_json"
    assert strict_payload["operator_action"] == "Return one valid JSON object only."
    assert strict_payload["operator_next_step"] == "resend_valid_json_object"


def test_strict_reason_code_maps_ambiguous_window_and_sandbox_rejections() -> None:
    cli = _load_cli_module()

    ambiguous = cli._strict_reason_code(
        decision="stop",
        report_status="failed",
        pilot={
            "source": "malformed_report",
            "parse_mode": "strict_failed_parse",
            "response_diagnostics": {"primary_rejection": {"reason": "E_AMBIGUOUS_REPO_WINDOW"}},
        },
    )
    sandbox = cli._strict_reason_code(
        decision="stop",
        report_status="failed",
        pilot={
            "source": "malformed_report",
            "parse_mode": "strict_failed_parse",
            "response_diagnostics": {"primary_rejection": {"reason": "E_SANDBOX_FILES_CHANGED"}},
        },
    )

    assert ambiguous == "ambiguous_repo_window"
    assert sandbox == "sandbox_contract_rejected"
