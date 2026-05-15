from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_reset_runtime_state_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "reset_runtime_state.py"
    spec = importlib.util.spec_from_file_location("reset_runtime_state", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_execute_resets_selected_runtime_state_files(tmp_path: Path, monkeypatch) -> None:
    module = _load_reset_runtime_state_module()
    panel_state = tmp_path / "automation" / "panel_state.json"
    metrics = tmp_path / "automation" / "metrics.json"
    assignment_metrics = tmp_path / "automation" / "assignment_metrics.jsonl"
    allow_metrics = tmp_path / "automation" / "allow_metrics.jsonl"

    panel_state.parent.mkdir(parents=True, exist_ok=True)
    panel_state.write_text(
        json.dumps(
            {
                "saved_at": "2026-02-01T12:00:07",
                "next_prompt_index": 3,
                "repo_prompt_indices": {"default": 3},
                "panels": {"panel-1": {"last_scanned": "2026-02-01T11:59:23"}},
            }
        ),
        encoding="utf-8",
    )
    metrics.write_text(
        json.dumps(
            {
                "last_updated": "2026-05-14T19:54:52",
                "prompt_metrics": [{"prompt_index": 1}],
                "response_feedback_metrics": [{"response_category": "completed"}],
            }
        ),
        encoding="utf-8",
    )
    assignment_metrics.write_text('{"prompt_id":"p1"}\n', encoding="utf-8")
    allow_metrics.write_text('{"allows_last_window": 5}\n', encoding="utf-8")

    monkeypatch.setattr(
        module,
        "TARGETS",
        (
            module.ResetTarget("panel-state", "Panel state", panel_state, module._write_panel_state),
            module.ResetTarget("metrics", "Metrics snapshot", metrics, module._write_metrics),
            module.ResetTarget("assignment-metrics", "Assignment metrics log", assignment_metrics, module._write_empty_jsonl),
            module.ResetTarget("allow-metrics", "Allow metrics log", allow_metrics, module._write_empty_jsonl),
        ),
    )
    monkeypatch.setattr(module, "DEFAULT_BACKUP_ROOT", tmp_path / "backups")

    rc = module.main(["--execute"])

    assert rc == 0
    reset_panel_state = json.loads(panel_state.read_text(encoding="utf-8"))
    reset_metrics = json.loads(metrics.read_text(encoding="utf-8"))
    assert reset_panel_state["panels"] == {}
    assert reset_panel_state["next_prompt_index"] == 0
    assert reset_metrics["prompt_metrics"] == []
    assert reset_metrics["response_feedback_metrics"] == []
    assert assignment_metrics.read_text(encoding="utf-8") == ""
    assert allow_metrics.read_text(encoding="utf-8") == ""
    assert list((tmp_path / "backups").rglob("panel_state.json"))
