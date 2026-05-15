from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from automation.orchestration_v1.models import now_iso


class OrchestrationLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, payload: Dict[str, object]) -> None:
        row = {
            "ts": now_iso(),
            "event": event_type,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def read_rows(self) -> List[Dict[str, object]]:
        if not self.path.is_file():
            return []
        rows: List[Dict[str, object]] = []
        for line in self.path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def active_runs(self) -> List[Dict[str, object]]:
        rows = self.read_rows()
        latest_by_run: Dict[str, str] = {}
        payload_by_run: Dict[str, Dict[str, object]] = {}
        for row in rows:
            event = str(row.get("event", ""))
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            run_id = str(payload.get("run_id", "")).strip()
            if not run_id:
                continue
            latest_by_run[run_id] = event
            payload_by_run[run_id] = payload

        terminal = {"run_completed", "run_failed", "run_blocked", "run_stopped"}
        results: List[Dict[str, object]] = []
        for run_id, event in latest_by_run.items():
            if event in terminal:
                continue
            payload = dict(payload_by_run.get(run_id, {}))
            payload.setdefault("run_id", run_id)
            results.append(payload)
        return results

    def retries_for_work_item(self, work_item_id: str) -> int:
        if not work_item_id:
            return 0
        attempts = 0
        for row in self.read_rows():
            if str(row.get("event", "")) != "run_dispatched":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if str(payload.get("work_item_id", "")) == work_item_id:
                attempts += 1
        return attempts

    def has_terminal_event(self, run_id: str) -> bool:
        if not run_id:
            return False
        terminal = {"run_completed", "run_failed", "run_blocked", "run_stopped"}
        latest_event = ""
        for row in self.read_rows():
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if str(payload.get("run_id", "")).strip() != run_id:
                continue
            latest_event = str(row.get("event", "")).strip()
        return latest_event in terminal
