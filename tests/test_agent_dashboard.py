from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from datetime import datetime
from pathlib import Path

from automation.panel_state import PanelState, PanelStatus


def _load_agent_dashboard_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "agent_dashboard.py"
    spec = importlib.util.spec_from_file_location("agent_dashboard", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_panel_state(path: Path) -> None:
    now = datetime(2026, 4, 25, 14, 32, 7)
    trading = PanelState(
        window_title="Worker - Trading - Visual Studio Code",
        panel_id="1",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        last_scanned=now,
        last_allow_check=now,
        status=PanelStatus.RUNNING,
        is_running=True,
        repo_name="Trading",
        assigned_task_name="Implement order validation with additional guards",
    )
    tf = PanelState(
        window_title="Worker - TF - Visual Studio Code",
        panel_id="2",
        first_seen=now,
        last_allow_click=now,
        last_output_change=now,
        last_scanned=now,
        last_allow_check=now,
        status=PanelStatus.FINISHED,
        is_running=False,
        repo_name="TF",
        assigned_task_name="Add regression tests for orchestration edge cases",
    )
    path.write_text(
        json.dumps(
            {
                "saved_at": now.isoformat(),
                "next_prompt_index": 0,
                "repo_prompt_indices": {},
                "panels": {
                    "panel-1": trading.to_dict(),
                    "panel-2": tf.to_dict(),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_allow_metrics(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-25T14:30:00",
                "allows_last_window": 14,
                "retention_minutes": 60,
                "last_allow_time": "2026-04-25T14:29:55",
                "max_allows_per_hour": 55,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_cost_metrics(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-25T14:31:00",
                "source": "tests",
                "event": "snapshot",
                "model": "gpt-4o-mini",
                "input_tokens": 100,
                "output_tokens": 200,
                "vision_images": 0,
                "token_cost": 1.23,
                "vision_cost": 0.0,
                "total_cost": 1.23,
                "details": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ts": "2026-04-25T14:30:00+00:00",
                "event": "run_completed",
                "payload": {"repo": "Trading"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_json_mode_produces_expected_keys(tmp_path: Path) -> None:
    module = _load_agent_dashboard_module()
    state_path = tmp_path / "panel_state.json"
    allow_path = tmp_path / "allow_metrics.jsonl"
    cost_path = tmp_path / "cost_metrics.jsonl"
    ledger_path = tmp_path / "state" / "orchestration" / "global_ledger.jsonl"
    _write_panel_state(state_path)
    _write_allow_metrics(allow_path)
    _write_cost_metrics(cost_path)
    _write_ledger(ledger_path)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = module.main(
            [
                "--json",
                "--state-path",
                str(state_path),
                "--allow-metrics-path",
                str(allow_path),
                "--cost-path",
                str(cost_path),
                "--ledger-path",
                str(ledger_path),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert "panels" in payload
    assert "queue_depths" in payload
    assert "session_cost" in payload
    assert "allow_rate" in payload


def test_repo_filter_only_returns_requested_repo(tmp_path: Path) -> None:
    module = _load_agent_dashboard_module()
    state_path = tmp_path / "panel_state.json"
    allow_path = tmp_path / "allow_metrics.jsonl"
    cost_path = tmp_path / "cost_metrics.jsonl"
    ledger_path = tmp_path / "state" / "orchestration" / "global_ledger.jsonl"
    _write_panel_state(state_path)
    _write_allow_metrics(allow_path)
    _write_cost_metrics(cost_path)
    _write_ledger(ledger_path)

    snapshot = module.build_dashboard_snapshot(
        state_path=state_path,
        allow_metrics_path=allow_path,
        cost_path=cost_path,
        ledger_path=ledger_path,
        repo="Trading",
    )

    assert snapshot["panels"]
    assert all(panel["repo"] == "Trading" for panel in snapshot["panels"])


def test_missing_panel_state_is_handled_gracefully(tmp_path: Path) -> None:
    module = _load_agent_dashboard_module()
    missing_state = tmp_path / "missing_panel_state.json"
    allow_path = tmp_path / "allow_metrics.jsonl"
    cost_path = tmp_path / "cost_metrics.jsonl"
    ledger_path = tmp_path / "state" / "orchestration" / "global_ledger.jsonl"
    _write_allow_metrics(allow_path)
    _write_cost_metrics(cost_path)
    _write_ledger(ledger_path)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = module.main(
            [
                "--json",
                "--state-path",
                str(missing_state),
                "--allow-metrics-path",
                str(allow_path),
                "--cost-path",
                str(cost_path),
                "--ledger-path",
                str(ledger_path),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["panels"] == []