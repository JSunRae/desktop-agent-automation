from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automation.orchestration_v1.collector import (
    collect_repo_context,
    normalize_work_items,
)
from automation.orchestration_v1.ledger import OrchestrationLedger
from automation.orchestration_v1.models import (
    ManagedRepoConfig,
    ManagedWorkspaceRegistry,
    OrchestrationCycleResult,
    OrchestrationDecision,
    Severity,
    WorkerCompletionReport,
    WorkerOutcome,
    WorkItem,
    WorkStatus,
)
from automation.orchestration_v1.registry import index_repos, load_registry
from automation.orchestration_v1.worker_protocol import (
    compose_worker_prompt,
    parse_worker_completion_report,
    report_to_jsonable,
)


class OrchestrationV1Loop:
    def __init__(
        self,
        *,
        registry: ManagedWorkspaceRegistry,
        ledger_path: Path,
        dispatch_root: Path,
        report_root: Path,
    ) -> None:
        self.registry = registry
        self.repo_index = index_repos(registry)
        self.ledger = OrchestrationLedger(ledger_path)
        self.dispatch_root = dispatch_root
        self.report_root = report_root

        self.dispatch_root.mkdir(parents=True, exist_ok=True)
        self.report_root.mkdir(parents=True, exist_ok=True)
        self._paused_repo_ids: set[str] = set()

    def run_once(self, *, poll_seconds: int = 60, poll_interval_seconds: int = 5) -> OrchestrationCycleResult:
        notes: List[str] = []

        guarded, guard_reason = self._check_global_safety()
        if not guarded:
            self.ledger.append("run_stopped", {"reason": guard_reason})
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=guard_reason),
                report=None,
                notes=[guard_reason],
            )

        work_items = self._collect_and_normalize(notes)
        if not work_items:
            reason = "No candidate work items discovered from structured sources"
            self.ledger.append("run_stopped", {"reason": reason})
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=reason),
                report=None,
                notes=notes,
            )

        selected = self._select_next_work_item(work_items)
        if selected is None:
            reason = "All candidate work items filtered by safety/concurrency constraints"
            self.ledger.append("run_stopped", {"reason": reason})
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=reason),
                report=None,
                notes=notes,
            )

        run_id = self._new_run_id(selected.repo)
        selected.run_id = run_id
        selected.status = WorkStatus.DISPATCHED

        prompt_path = self._dispatch(selected, run_id)
        self.ledger.append(
            "run_dispatched",
            {
                "run_id": run_id,
                "repo": selected.repo,
                "work_item_id": selected.work_item_id,
                "title": selected.title,
                "dispatch_prompt_path": str(prompt_path),
            },
        )

        report = self._poll_for_report(run_id, selected.repo, poll_seconds, poll_interval_seconds)
        if report is None:
            reason = "No structured worker report available before poll timeout"
            decision = OrchestrationDecision(action="wait", reason=reason)
            self.ledger.append(
                "run_stopped",
                {
                    "run_id": run_id,
                    "repo": selected.repo,
                    "work_item_id": selected.work_item_id,
                    "reason": "poll_timeout",
                },
            )
            notes.append(reason)
            return OrchestrationCycleResult(
                run_id=run_id,
                selected_work_item=selected,
                decision=decision,
                report=None,
                notes=notes,
            )

        decision = self._decide(selected, report)
        terminal_event = {
            WorkerOutcome.SUCCESS: "run_completed",
            WorkerOutcome.PARTIAL: "run_completed",
            WorkerOutcome.BLOCKED: "run_blocked",
            WorkerOutcome.FAILED: "run_failed",
        }[report.status]
        self.ledger.append(
            terminal_event,
            {
                "run_id": run_id,
                "repo": selected.repo,
                "work_item_id": selected.work_item_id,
                "decision": asdict(decision),
                "report": report_to_jsonable(report),
            },
        )

        return OrchestrationCycleResult(
            run_id=run_id,
            selected_work_item=selected,
            decision=decision,
            report=report,
            notes=notes,
        )

    def _check_global_safety(self) -> Tuple[bool, str]:
        active_runs = self.ledger.active_runs()
        total_active = len(active_runs)
        if total_active >= self.registry.global_constraints.max_active_workers_total:
            return False, (
                "Global concurrency cap reached: "
                f"{total_active}/{self.registry.global_constraints.max_active_workers_total}"
            )

        by_repo: Dict[str, int] = {}
        for run in active_runs:
            repo = str(run.get("repo", "")).strip().lower()
            if not repo:
                continue
            by_repo[repo] = by_repo.get(repo, 0) + 1

        for repo_id, count in by_repo.items():
            if count >= self.registry.global_constraints.max_active_workers_per_repo:
                return False, (
                    f"Repo concurrency cap reached for {repo_id}: "
                    f"{count}/{self.registry.global_constraints.max_active_workers_per_repo}"
                )
        return True, "ok"

    def _collect_and_normalize(self, notes: List[str]) -> List[WorkItem]:
        items: List[WorkItem] = []
        self._paused_repo_ids = set()
        for repo in self.registry.repos:
            bundle = collect_repo_context(repo)
            items.extend(normalize_work_items(repo=repo, bundle=bundle))

            if self._repo_has_protected_activity(repo, bundle.protected_signals):
                self._paused_repo_ids.add(repo.repo_id.lower())
                notes.append(f"Protected activity detected for {repo.repo_id}; dispatch into this repo is paused")
        return items

    def _repo_has_protected_activity(self, repo: ManagedRepoConfig, protected_signals: List[str]) -> bool:
        if not protected_signals:
            return False
        signal_text = "\n".join(protected_signals).lower()
        if "do_not_interrupt" in signal_text:
            return True
        for token in repo.safety_rules.protected_process_patterns:
            if token.lower() in signal_text and any(k in signal_text for k in ["running", "active", "in_progress"]):
                return True
        return False

    def _score(self, item: WorkItem) -> float:
        severity_points = {
            Severity.BLOCKER: 1.0,
            Severity.HIGH: 0.8,
            Severity.MEDIUM: 0.5,
            Severity.LOW: 0.2,
        }[item.severity]

        dependency_penalty = 0.15 if item.dependencies else 0.0
        confidence_bonus = min(0.2, max(0.0, item.confidence * 0.2))
        blocker_bonus = 0.15 if item.source in {"report", "handover"} else 0.0
        return max(0.0, severity_points + confidence_bonus + blocker_bonus - dependency_penalty)

    def _select_next_work_item(self, work_items: List[WorkItem]) -> Optional[WorkItem]:
        candidates: List[Tuple[float, WorkItem]] = []
        for item in work_items:
            repo = self.repo_index.get(item.repo.lower())
            if repo is None:
                continue
            if item.repo.lower() in self._paused_repo_ids:
                continue

            retries = self.ledger.retries_for_work_item(item.work_item_id)
            if retries >= self.registry.global_constraints.loop_retry_limit:
                continue

            candidates.append((self._score(item), item))

        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry[0], reverse=True)
        return candidates[0][1]

    def _new_run_id(self, repo_id: str) -> str:
        return f"{repo_id.lower()}-{uuid.uuid4().hex[:10]}"

    def _dispatch(self, item: WorkItem, run_id: str) -> Path:
        repo_cfg = self.repo_index[item.repo.lower()]
        repo_queue_dir = self.dispatch_root / item.repo
        repo_queue_dir.mkdir(parents=True, exist_ok=True)

        prompt = compose_worker_prompt(
            run_id=run_id,
            work_item=item,
            repo_config=repo_cfg,
            context_excerpt=item.title,
            reason_selected="Highest V1 score from normalized queue with safety constraints",
        )

        prompt_path = repo_queue_dir / f"{run_id}.prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")

        envelope_path = repo_queue_dir / f"{run_id}.dispatch.json"
        envelope_payload = {
            "run_id": run_id,
            "repo": item.repo,
            "work_item": asdict(item),
            "prompt_path": str(prompt_path),
            "status": "dispatched",
        }
        envelope_path.write_text(json.dumps(envelope_payload, indent=2), encoding="utf-8")
        return prompt_path

    def _poll_for_report(
        self,
        run_id: str,
        repo: str,
        poll_seconds: int,
        poll_interval_seconds: int,
    ) -> Optional[WorkerCompletionReport]:
        deadline = time.time() + max(0, poll_seconds)
        candidates = [
            self.report_root / f"{run_id}.json",
            self.report_root / f"{run_id}.yaml",
            self.report_root / f"{run_id}.yml",
            self.report_root / f"{run_id}.md",
            self.report_root / f"{run_id}.txt",
            self.report_root / repo / f"{run_id}.json",
            self.report_root / repo / f"{run_id}.yaml",
            self.report_root / repo / f"{run_id}.md",
        ]

        while time.time() <= deadline:
            for path in candidates:
                if not path.is_file():
                    continue
                raw = path.read_text(encoding="utf-8", errors="ignore")
                report = parse_worker_completion_report(raw)
                if report is not None:
                    return report
            if poll_seconds <= 0:
                break
            time.sleep(max(1, poll_interval_seconds))
        return None

    def _decide(self, item: WorkItem, report: WorkerCompletionReport) -> OrchestrationDecision:
        if report.status == WorkerOutcome.SUCCESS:
            return OrchestrationDecision(action="accept", reason="Worker reported success")
        if report.status == WorkerOutcome.PARTIAL:
            follow_repo = None
            if item.dependencies:
                follow_repo = item.dependencies[0]
            return OrchestrationDecision(
                action="follow_up",
                reason="Worker reported partial completion",
                create_follow_up=True,
                follow_up_repo=follow_repo,
            )
        if report.status == WorkerOutcome.BLOCKED:
            return OrchestrationDecision(action="escalate", reason="Worker blocked")
        return OrchestrationDecision(action="stop", reason="Worker failed")


def build_default_loop(
    *,
    registry_path: Path | None = None,
    ledger_path: Path | None = None,
    dispatch_root: Path | None = None,
    report_root: Path | None = None,
) -> OrchestrationV1Loop:
    registry = load_registry(registry_path)
    base = Path(__file__).resolve().parents[2]
    return OrchestrationV1Loop(
        registry=registry,
        ledger_path=ledger_path or (base / "state" / "orchestration" / "global_ledger.jsonl"),
        dispatch_root=dispatch_root or (base / "state" / "orchestration" / "dispatch_queue"),
        report_root=report_root or (base / "state" / "orchestration" / "worker_reports"),
    )
