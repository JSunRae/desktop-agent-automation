from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _load_launch_preflight_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "launch_preflight.py"
    spec = importlib.util.spec_from_file_location("launch_preflight", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_panel_state(path: Path, *, saved_at: datetime, last_scanned: datetime | None, panel_count: int) -> None:
    panels = {}
    for idx in range(panel_count):
        panels[f"panel-{idx}"] = {
            "window_title": f"Panel {idx}",
            "panel_id": str(idx),
            "first_seen": saved_at.isoformat(),
            "last_allow_click": saved_at.isoformat(),
            "last_output_change": saved_at.isoformat(),
            "last_scanned": (last_scanned or saved_at).isoformat(),
            "last_allow_check": saved_at.isoformat(),
            "status": "running",
            "is_running": True,
        }
    path.write_text(
        json.dumps(
            {
                "saved_at": saved_at.isoformat(),
                "next_prompt_index": 0,
                "repo_prompt_indices": {},
                "panels": panels,
            }
        ),
        encoding="utf-8",
    )


def test_inspect_panel_state_accepts_clean_baseline(tmp_path: Path) -> None:
    module = _load_launch_preflight_module()
    state_path = tmp_path / "panel_state.json"
    _write_panel_state(
        state_path,
        saved_at=datetime(2026, 5, 15, 10, 0, 0),
        last_scanned=None,
        panel_count=0,
    )

    result = module.inspect_panel_state(state_path, max_age_days=14)

    assert result.ok is True
    assert result.details["panel_count"] == 0


def test_inspect_panel_state_rejects_stale_tracked_panels(tmp_path: Path) -> None:
    module = _load_launch_preflight_module()
    stale = datetime.now() - timedelta(days=30)
    state_path = tmp_path / "panel_state.json"
    _write_panel_state(
        state_path,
        saved_at=stale,
        last_scanned=stale,
        panel_count=2,
    )

    result = module.inspect_panel_state(state_path, max_age_days=14)

    assert result.ok is False
    assert result.details["panel_count"] == 2
    assert "stale" in result.summary


def test_build_isolated_env_redirects_mutable_outputs(tmp_path: Path) -> None:
    module = _load_launch_preflight_module()

    env = module._build_isolated_env(tmp_path)

    assert env["AUTOMATION_METRICS_PATH"] == str(tmp_path / "automation" / "metrics.json")
    assert env["AUTOMATION_ASSIGNMENT_METRICS_PATH"] == str(tmp_path / "automation" / "assignment_metrics.jsonl")
    assert env["CROSS_REPO_TODO_CACHE_PATH"] == str(tmp_path / "automation" / "cross_repo_todo_cache.json")
    assert env["NORTH_STAR_CACHE_PATH"] == str(tmp_path / "state" / "north_star_cache.json")
    assert env["WORKSTREAM_COORDINATION_STATE_PATH"] == str(tmp_path / "state" / "workstream_coordination.json")
