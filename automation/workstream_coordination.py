"""Workstream-aware chat lifecycle policy and persisted coordination state."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from automation.config import (
    ENABLE_WORKSTREAM_COORDINATION,
    WORKSTREAM_CONDENSED_CONTEXT_CHARS,
    WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT,
    WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT,
    WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT,
)
from automation.panel_state import PanelState, PanelStatus, extract_repo_name_from_title

DEFAULT_WORKSTREAM_STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "workstream_coordination.json"
_WORKSTREAM_COORDINATOR: Optional["WorkstreamCoordinator"] = None
_SEVERE_ISSUE_TAGS = {"merge_conflict", "test_failure", "error_output"}


class ChatLifecycleAction(str, Enum):
    REUSE_EXISTING = "reuse_existing"
    CONDENSE_TO_FRESH = "condense_to_fresh"
    START_FRESH = "start_fresh"


@dataclass
class ChatLifecycleDecision:
    workstream_id: str
    action: ChatLifecycleAction
    reason: str
    estimated_context_tokens: int
    rendered_prompt: str
    condensed_context: str = ""


@dataclass
class WorkstreamRecord:
    workstream_id: str
    repo_name: str
    task_name: str
    active_panel_ids: List[str] = field(default_factory=list)
    panel_titles: List[str] = field(default_factory=list)
    statuses: List[str] = field(default_factory=list)
    issue_tags: List[str] = field(default_factory=list)
    summary: str = ""
    latest_output_preview: str = ""
    latest_prompt_preview: str = ""
    estimated_context_tokens: int = 0
    active_panel_count: int = 0
    last_updated: str = ""
    last_action: Optional[str] = None
    last_action_reason: Optional[str] = None
    condensation_count: int = 0
    fresh_chat_count: int = 0
    reuse_count: int = 0
    last_condensed_context: str = ""

    def to_dict(self) -> dict:
        return {
            "workstream_id": self.workstream_id,
            "repo_name": self.repo_name,
            "task_name": self.task_name,
            "active_panel_ids": list(self.active_panel_ids),
            "panel_titles": list(self.panel_titles),
            "statuses": list(self.statuses),
            "issue_tags": list(self.issue_tags),
            "summary": self.summary,
            "latest_output_preview": self.latest_output_preview,
            "latest_prompt_preview": self.latest_prompt_preview,
            "estimated_context_tokens": self.estimated_context_tokens,
            "active_panel_count": self.active_panel_count,
            "last_updated": self.last_updated,
            "last_action": self.last_action,
            "last_action_reason": self.last_action_reason,
            "condensation_count": self.condensation_count,
            "fresh_chat_count": self.fresh_chat_count,
            "reuse_count": self.reuse_count,
            "last_condensed_context": self.last_condensed_context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkstreamRecord":
        return cls(
            workstream_id=str(data.get("workstream_id", "")),
            repo_name=str(data.get("repo_name", "")),
            task_name=str(data.get("task_name", "")),
            active_panel_ids=list(data.get("active_panel_ids", [])),
            panel_titles=list(data.get("panel_titles", [])),
            statuses=list(data.get("statuses", [])),
            issue_tags=list(data.get("issue_tags", [])),
            summary=str(data.get("summary", "")),
            latest_output_preview=str(data.get("latest_output_preview", "")),
            latest_prompt_preview=str(data.get("latest_prompt_preview", "")),
            estimated_context_tokens=int(data.get("estimated_context_tokens", 0) or 0),
            active_panel_count=int(data.get("active_panel_count", 0) or 0),
            last_updated=str(data.get("last_updated", "")),
            last_action=data.get("last_action"),
            last_action_reason=data.get("last_action_reason"),
            condensation_count=int(data.get("condensation_count", 0) or 0),
            fresh_chat_count=int(data.get("fresh_chat_count", 0) or 0),
            reuse_count=int(data.get("reuse_count", 0) or 0),
            last_condensed_context=str(data.get("last_condensed_context", "")),
        )


def get_workstream_coordinator() -> "WorkstreamCoordinator":
    global _WORKSTREAM_COORDINATOR
    if _WORKSTREAM_COORDINATOR is None:
        _WORKSTREAM_COORDINATOR = WorkstreamCoordinator()
    return _WORKSTREAM_COORDINATOR


def _estimate_tokens(text: str) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


def _preview(text: Optional[str], limit: int = 180) -> str:
    cleaned = (text or "").strip().replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."


def _task_name_for_panel(panel: PanelState, assignment_prompt: str = "") -> str:
    for candidate in (
        panel.assigned_task_name,
        panel.assigned_task_id,
        panel.assigned_prompt_text,
        assignment_prompt,
        panel.window_title,
    ):
        value = _preview(candidate, limit=120)
        if value:
            return value
    return "unassigned-workstream"


def _workstream_id_for_panel(panel: PanelState, assignment_prompt: str = "") -> str:
    repo_name = panel.repo_name or extract_repo_name_from_title(panel.window_title) or "unknown-repo"
    task_name = _task_name_for_panel(panel, assignment_prompt)
    normalized_repo = re.sub(r"[^a-z0-9]+", "-", repo_name.lower()).strip("-") or "repo"
    normalized_task = re.sub(r"[^a-z0-9]+", "-", task_name.lower()).strip("-") or "task"
    digest = hashlib.sha256(f"{normalized_repo}::{task_name}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{normalized_repo}:{normalized_task[:48]}:{digest}"


def _panel_context_tokens(panel: PanelState) -> int:
    token_total = 0
    token_total += _estimate_tokens(panel.assigned_prompt_text or "")
    token_total += _estimate_tokens(panel.last_seed_prompt_text or "")
    token_total += _estimate_tokens(panel.last_output_sample or "")
    token_total += _estimate_tokens(panel.last_review_message or "")
    for snapshot in panel.transcript_snapshots or []:
        if snapshot.length > 0:
            token_total += max(1, (snapshot.length + 3) // 4)
        else:
            token_total += _estimate_tokens(snapshot.preview or "")
    return token_total


class WorkstreamCoordinator:
    def __init__(self, *, state_path: Path = DEFAULT_WORKSTREAM_STATE_PATH) -> None:
        self.state_path = state_path
        self.workstreams: Dict[str, WorkstreamRecord] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        records = payload.get("workstreams", {}) if isinstance(payload, dict) else {}
        if not isinstance(records, dict):
            return
        for workstream_id, raw in records.items():
            try:
                record = WorkstreamRecord.from_dict(raw)
            except Exception:
                continue
            if record.workstream_id:
                self.workstreams[workstream_id] = record

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now().isoformat(),
            "workstreams": {key: record.to_dict() for key, record in self.workstreams.items()},
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def sync_panels(self, panels: Iterable[PanelState]) -> Dict[str, WorkstreamRecord]:
        if not ENABLE_WORKSTREAM_COORDINATION:
            return self.workstreams

        grouped: Dict[str, List[PanelState]] = {}
        for panel in panels:
            if not panel.window_title:
                continue
            workstream_id = _workstream_id_for_panel(panel)
            grouped.setdefault(workstream_id, []).append(panel)

        updated: Dict[str, WorkstreamRecord] = {}
        for workstream_id, group in grouped.items():
            group = sorted(group, key=lambda item: item.last_scanned)
            previous = self.workstreams.get(workstream_id)
            newest = group[-1]
            repo_name = newest.repo_name or extract_repo_name_from_title(newest.window_title) or "unknown-repo"
            task_name = _task_name_for_panel(newest)
            panel_titles = [panel.window_title for panel in group if panel.window_title]
            issue_tags = sorted({tag for panel in group for tag in (panel.transcript_issue_tags or [])})
            summaries = [panel.transcript_issue_summary for panel in group if panel.transcript_issue_summary]
            estimated_tokens = sum(_panel_context_tokens(panel) for panel in group)
            latest_output_panel = max(group, key=lambda item: item.last_output_change)
            active_panel_count = sum(1 for panel in group if panel.status not in {PanelStatus.COMPLETED, PanelStatus.STALE})
            record = WorkstreamRecord(
                workstream_id=workstream_id,
                repo_name=repo_name,
                task_name=task_name,
                active_panel_ids=[panel.panel_id for panel in group if panel.panel_id],
                panel_titles=panel_titles[:6],
                statuses=[panel.status.value for panel in group],
                issue_tags=issue_tags,
                summary=_preview("; ".join(summaries[:3]), limit=260),
                latest_output_preview=_preview(latest_output_panel.last_output_sample, limit=220),
                latest_prompt_preview=_preview(newest.assigned_prompt_text or newest.last_seed_prompt_text, limit=220),
                estimated_context_tokens=estimated_tokens,
                active_panel_count=active_panel_count,
                last_updated=max(panel.last_scanned for panel in group).isoformat(),
                last_action=previous.last_action if previous else None,
                last_action_reason=previous.last_action_reason if previous else None,
                condensation_count=previous.condensation_count if previous else 0,
                fresh_chat_count=previous.fresh_chat_count if previous else 0,
                reuse_count=previous.reuse_count if previous else 0,
                last_condensed_context=previous.last_condensed_context if previous else "",
            )
            updated[workstream_id] = record

        self.workstreams = updated
        self._save_state()
        return self.workstreams

    def _build_condensed_context(self, record: WorkstreamRecord, assignment_prompt: str, reason: str) -> str:
        lines = [
            "Workstream handoff summary",
            "Use this condensed summary as the authoritative prior context for this workstream.",
            f"Repo: {record.repo_name}",
            f"Workstream: {record.task_name}",
            f"Why condensed: {reason}",
            f"Estimated retained context: {record.estimated_context_tokens} tokens",
        ]
        if record.panel_titles:
            lines.append("Panels contributing context: " + "; ".join(_preview(title, limit=60) for title in record.panel_titles[:4]))
        if record.summary:
            lines.append(f"Recent summary: {record.summary}")
        if record.latest_prompt_preview:
            lines.append(f"Last prompt preview: {record.latest_prompt_preview}")
        if record.latest_output_preview:
            lines.append(f"Latest visible output: {record.latest_output_preview}")
        if record.issue_tags:
            lines.append("Issue tags: " + ", ".join(record.issue_tags[:6]))
        lines.append("Do not assume any unstated earlier chat history beyond this summary.")
        condensed = "\n".join(lines).strip()
        if len(condensed) > WORKSTREAM_CONDENSED_CONTEXT_CHARS:
            condensed = condensed[: WORKSTREAM_CONDENSED_CONTEXT_CHARS - 3].rstrip() + "..."
        return f"{condensed}\n\nCurrent assignment:\n{assignment_prompt.strip()}".strip()

    def decide_for_panel(self, panel: PanelState, assignment_prompt: str, panels: Iterable[PanelState]) -> ChatLifecycleDecision:
        if not ENABLE_WORKSTREAM_COORDINATION:
            workstream_id = _workstream_id_for_panel(panel, assignment_prompt)
            return ChatLifecycleDecision(
                workstream_id=workstream_id,
                action=ChatLifecycleAction.START_FRESH,
                reason="workstream_coordination_disabled",
                estimated_context_tokens=0,
                rendered_prompt=assignment_prompt,
            )

        workstreams = self.sync_panels(panels)
        workstream_id = _workstream_id_for_panel(panel, assignment_prompt)
        record = workstreams.get(workstream_id)
        if record is None:
            record = WorkstreamRecord(
                workstream_id=workstream_id,
                repo_name=panel.repo_name or extract_repo_name_from_title(panel.window_title) or "unknown-repo",
                task_name=_task_name_for_panel(panel, assignment_prompt),
            )

        total_tokens = record.estimated_context_tokens + _estimate_tokens(assignment_prompt)

        if not record.estimated_context_tokens:
            action = ChatLifecycleAction.START_FRESH
            reason = "No retained workstream context yet"
            rendered_prompt = assignment_prompt
            condensed_context = ""
        elif any(tag in _SEVERE_ISSUE_TAGS for tag in record.issue_tags):
            action = ChatLifecycleAction.START_FRESH
            reason = "Severe transcript issues detected; reset instead of carrying forward chat state"
            rendered_prompt = assignment_prompt
            condensed_context = ""
        elif total_tokens >= WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT:
            action = ChatLifecycleAction.CONDENSE_TO_FRESH
            reason = f"Estimated context {total_tokens} exceeds hard limit {WORKSTREAM_CONTEXT_HARD_TOKEN_LIMIT}"
            rendered_prompt = self._build_condensed_context(record, assignment_prompt, reason)
            condensed_context = rendered_prompt
        elif record.active_panel_count > 1 and record.estimated_context_tokens >= WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT:
            action = ChatLifecycleAction.CONDENSE_TO_FRESH
            reason = (
                f"Multiple panels contributed context and retained estimate {record.estimated_context_tokens} "
                f"exceeds {WORKSTREAM_MULTI_PANEL_TOKEN_LIMIT}"
            )
            rendered_prompt = self._build_condensed_context(record, assignment_prompt, reason)
            condensed_context = rendered_prompt
        elif total_tokens >= WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT:
            action = ChatLifecycleAction.CONDENSE_TO_FRESH
            reason = f"Estimated context {total_tokens} exceeds soft limit {WORKSTREAM_CONTEXT_SOFT_TOKEN_LIMIT}"
            rendered_prompt = self._build_condensed_context(record, assignment_prompt, reason)
            condensed_context = rendered_prompt
        else:
            action = ChatLifecycleAction.REUSE_EXISTING
            reason = f"Estimated context {total_tokens} remains within budget"
            rendered_prompt = assignment_prompt
            condensed_context = ""

        record.last_action = action.value
        record.last_action_reason = reason
        if condensed_context:
            record.last_condensed_context = condensed_context
        self.workstreams[workstream_id] = record
        self._save_state()
        return ChatLifecycleDecision(
            workstream_id=workstream_id,
            action=action,
            reason=reason,
            estimated_context_tokens=record.estimated_context_tokens,
            rendered_prompt=rendered_prompt,
            condensed_context=condensed_context,
        )

    def record_dispatch_result(self, panel: PanelState, decision: ChatLifecycleDecision, *, success: bool) -> None:
        if not ENABLE_WORKSTREAM_COORDINATION:
            return
        record = self.workstreams.get(decision.workstream_id)
        if record is None:
            return
        if success:
            if decision.action == ChatLifecycleAction.CONDENSE_TO_FRESH:
                record.condensation_count += 1
            elif decision.action == ChatLifecycleAction.START_FRESH:
                record.fresh_chat_count += 1
            else:
                record.reuse_count += 1
        record.last_action = decision.action.value
        record.last_action_reason = decision.reason if success else f"dispatch_failed: {decision.reason}"
        self.workstreams[decision.workstream_id] = record
        self._save_state()


def apply_workstream_chat_policy(*, tracker, panel: PanelState, assignment_prompt: str) -> ChatLifecycleDecision:
    coordinator = get_workstream_coordinator()
    return coordinator.decide_for_panel(panel, assignment_prompt, tracker.panels.values())


__all__ = [
    "ChatLifecycleAction",
    "ChatLifecycleDecision",
    "DEFAULT_WORKSTREAM_STATE_PATH",
    "WorkstreamCoordinator",
    "WorkstreamRecord",
    "apply_workstream_chat_policy",
    "get_workstream_coordinator",
]