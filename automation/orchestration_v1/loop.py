from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    WorkCategory,
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
        diagnostics: Dict[str, Any] = {
            "discovery": {
                "repos": {},
                "total_normalized_candidates": 0,
            },
            "selection": {
                "rejected_counts": {},
                "pilot_allowlist_reason_counts": {},
                "blocked_term_counts": {},
                "rejected_samples": {},
                "eligible_ranked": [],
            },
            "stop_reason": None,
        }

        guarded, guard_reason = self._check_global_safety()
        if not guarded:
            diagnostics["stop_reason"] = guard_reason
            self.ledger.append("run_stopped", {"reason": guard_reason})
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=guard_reason),
                report=None,
                notes=[guard_reason],
                diagnostics=diagnostics,
            )

        work_items, discovery_diag = self._collect_and_normalize(notes)
        diagnostics["discovery"] = discovery_diag
        if not work_items:
            reason = self._discovery_stop_reason(discovery_diag)
            diagnostics["stop_reason"] = reason
            discovery_note = self._human_discovery_summary(discovery_diag)
            if discovery_note:
                notes.append(discovery_note)
            self.ledger.append("cycle_diagnostics", diagnostics)
            self.ledger.append("run_stopped", {"reason": reason, "diagnostics": diagnostics})
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=reason),
                report=None,
                notes=notes,
                diagnostics=diagnostics,
            )

        selected, selection_diag = self._select_next_work_item(work_items)
        diagnostics["selection"] = selection_diag
        if selected is None:
            diagnostics["discovery_diagnostics"] = self._build_no_eligible_work_items_diagnostics(
                discovery_diag=discovery_diag,
                selection_diag=selection_diag,
            )
            reason = "No eligible work items after source-aware discovery"
            diagnostics["stop_reason"] = reason
            notes.append(self._human_selection_summary(selection_diag))
            notes.append(self._human_no_eligible_work_items_summary(diagnostics["discovery_diagnostics"]))
            self.ledger.append("cycle_diagnostics", diagnostics)
            self.ledger.append("run_stopped", {"reason": reason, "diagnostics": diagnostics})
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=reason),
                report=None,
                notes=notes,
                diagnostics=diagnostics,
            )

        allowlisted, allowlist_reason, allowlist_details = self._check_pilot_allowlist(selected)
        if not allowlisted:
            reason = f"Selected work item failed pilot allowlist: {allowlist_reason}"
            diagnostics["stop_reason"] = reason
            diagnostics.setdefault("selection", {})["dispatch_gate"] = {
                "allowlisted": False,
                "reason": allowlist_reason,
                "details": allowlist_details,
            }
            notes.append(reason)
            self.ledger.append("cycle_diagnostics", diagnostics)
            self.ledger.append(
                "run_stopped",
                {
                    "reason": reason,
                    "selected_work_item": selected.work_item_id,
                    "repo": selected.repo,
                    "diagnostics": diagnostics,
                },
            )
            return OrchestrationCycleResult(
                run_id=None,
                selected_work_item=None,
                decision=OrchestrationDecision(action="stop", reason=reason),
                report=None,
                notes=notes,
                diagnostics=diagnostics,
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
                "selection_diagnostics": selection_diag,
            },
        )
        self.ledger.append("cycle_diagnostics", diagnostics)

        if poll_seconds < 0:
            reason = "Dispatch completed; response polling deferred"
            notes.append(reason)
            return OrchestrationCycleResult(
                run_id=run_id,
                selected_work_item=selected,
                decision=OrchestrationDecision(action="wait", reason=reason),
                report=None,
                notes=notes,
                diagnostics=diagnostics,
            )

        report = self._poll_for_report(run_id, selected.repo, poll_seconds, poll_interval_seconds)
        if report is None:
            reason = "No structured worker report available before poll timeout"
            decision = self.record_stopped(
                run_id=run_id,
                selected=selected,
                reason_code="poll_timeout",
                decision_reason=reason,
                extra_payload={"mode": "file_poll"},
            )
            notes.append(reason)
            return OrchestrationCycleResult(
                run_id=run_id,
                selected_work_item=selected,
                decision=decision,
                report=None,
                notes=notes,
                diagnostics=diagnostics,
            )

        decision = self.record_report_and_decision(
            run_id=run_id,
            selected=selected,
            report=report,
            response_meta={"mode": "file_poll"},
        )

        return OrchestrationCycleResult(
            run_id=run_id,
            selected_work_item=selected,
            decision=decision,
            report=report,
            notes=notes,
            diagnostics=diagnostics,
        )

    def _check_global_safety(self) -> Tuple[bool, str]:
        active_runs = self.ledger.active_runs()
        total_active = len(active_runs)
        if total_active >= self.registry.global_constraints.max_active_workers_total:
            return False, (
                "Global concurrency cap reached: "
                f"{total_active}/{self.registry.global_constraints.max_active_workers_total}"
            )
        return True, "ok"

    def _discovery_stop_reason(self, discovery_diag: Dict[str, Any]) -> str:
        repo_gaps: List[str] = []
        repo_empty_candidates: List[str] = []
        for repo_id, repo_diag in (discovery_diag.get("repos") or {}).items():
            if not isinstance(repo_diag, dict):
                continue
            missing_sources: List[str] = []
            empty_candidate_sources: List[str] = []
            task_diag = repo_diag.get("sources", {}).get("task") if isinstance(repo_diag.get("sources"), dict) else None
            if isinstance(task_diag, dict):
                mismatch_reason = str(task_diag.get("mismatch_reason") or "").strip()
                if mismatch_reason == "no_matching_files":
                    unmatched_entries = task_diag.get("unmatched_entries") or []
                    preview = ", ".join(str(entry) for entry in unmatched_entries[:2])
                    if len(unmatched_entries) > 2:
                        preview += ", ..."
                    missing_sources.append(f"task=0 matches [{preview}]" if preview else "task=0 matches")
                elif mismatch_reason == "matched_files_without_extractable_items":
                    zero_files = task_diag.get("files_with_zero_items") or task_diag.get("matched_files") or []
                    preview = ", ".join(str(path) for path in zero_files[:2])
                    if len(zero_files) > 2:
                        preview += ", ..."
                    empty_candidate_sources.append(f"task({preview})" if preview else "task")
            mismatch_summary = repo_diag.get("source_mismatch_summary")
            if isinstance(mismatch_summary, list):
                for entry in mismatch_summary:
                    if isinstance(entry, str) and entry.strip():
                        if entry not in missing_sources:
                            missing_sources.append(entry)
            source_diag = repo_diag.get("sources") if isinstance(repo_diag.get("sources"), dict) else {}
            for source_name in ("task", "handover", "report"):
                source_info = source_diag.get(source_name)
                if not isinstance(source_info, dict):
                    continue
                matched_files = source_info.get("matched_files")
                extracted_count = int(source_info.get("extracted_candidate_count", 0) or 0)
                if source_name == "task" and isinstance(task_diag, dict):
                    mismatch_reason = str(task_diag.get("mismatch_reason") or "").strip()
                    if mismatch_reason == "matched_files_without_extractable_items":
                        continue
                if isinstance(matched_files, list) and matched_files and extracted_count == 0:
                    empty_candidate_sources.append(source_name)
            if missing_sources:
                repo_gaps.append(f"{repo_id}({', '.join(missing_sources)})")
            if empty_candidate_sources:
                repo_empty_candidates.append(f"{repo_id}({', '.join(empty_candidate_sources)})")
        if repo_empty_candidates:
            return (
                "No candidate work items discovered from structured sources; found structured files but extracted "
                "no task candidates for: " + "; ".join(repo_empty_candidates[:3])
            )
        if repo_gaps:
            return "No candidate work items discovered from structured sources; source mismatch summary: " + "; ".join(repo_gaps[:3])
        return "No candidate work items discovered from structured sources"

    def _human_discovery_summary(self, discovery_diag: Dict[str, Any]) -> str:
        repo_notes: List[str] = []
        for repo_id, repo_diag in (discovery_diag.get("repos") or {}).items():
            if not isinstance(repo_diag, dict):
                continue
            source_diag = repo_diag.get("sources") if isinstance(repo_diag.get("sources"), dict) else {}
            task_diag = source_diag.get("task") if isinstance(source_diag.get("task"), dict) else {}
            mismatch_reason = str(task_diag.get("mismatch_reason") or "").strip()
            if mismatch_reason == "no_matching_files":
                nearby = ", ".join(str(path) for path in (task_diag.get("nearby_candidate_files") or [])[:3]) or "none"
                repo_notes.append(f"{repo_id}: configured task sources matched no files; nearby candidates: {nearby}")
                continue
            if mismatch_reason == "matched_files_without_extractable_items":
                zero_files = ", ".join(str(path) for path in (task_diag.get("files_with_zero_items") or [])[:3])
                repo_notes.append(f"{repo_id}: task files matched but yielded zero extractable items in {zero_files}")
                continue
            empty_files: List[str] = []
            for source_name in ("task", "handover", "report"):
                source_info = source_diag.get(source_name)
                if not isinstance(source_info, dict):
                    continue
                for path in source_info.get("files_with_no_candidates", []) or []:
                    name = Path(str(path)).name
                    if name:
                        empty_files.append(name)
            if empty_files:
                unique = ", ".join(sorted(dict.fromkeys(empty_files)))
                repo_notes.append(f"{repo_id}: no extractable task lines in {unique}")
        if not repo_notes:
            return ""
        return "Discovery diagnostics: " + "; ".join(repo_notes)

    def _collect_and_normalize(self, notes: List[str]) -> Tuple[List[WorkItem], Dict[str, Any]]:
        items: List[WorkItem] = []
        self._paused_repo_ids = set()
        by_repo: Dict[str, Any] = {}
        source_mismatch_repos: Dict[str, List[str]] = {}
        source_counts: Counter[str] = Counter()
        for repo in self.registry.repos:
            bundle = collect_repo_context(repo)
            normalized = normalize_work_items(repo=repo, bundle=bundle)
            items.extend(normalized)
            for item in normalized:
                source_counts[item.source] += 1

            source_mismatch_summary: List[str] = []
            for source_name in ("task", "handover", "report"):
                source_info = bundle.source_diagnostics.get(source_name)
                if not isinstance(source_info, dict):
                    continue
                matched_files = source_info.get("matched_files")
                unmatched_entries = source_info.get("unmatched_entries")
                if not isinstance(matched_files, list) or not isinstance(unmatched_entries, list):
                    continue
                if matched_files or not unmatched_entries:
                    continue
                unmatched_preview = ", ".join(str(entry) for entry in unmatched_entries[:2])
                if len(unmatched_entries) > 2:
                    unmatched_preview += ", ..."
                source_mismatch_summary.append(f"{source_name}=0 matches [{unmatched_preview}]")

            if source_mismatch_summary:
                source_mismatch_repos[repo.repo_id] = source_mismatch_summary

            if self._repo_has_protected_activity(repo, bundle.protected_signals):
                self._paused_repo_ids.add(repo.repo_id.lower())
                notes.append(f"Protected activity detected for {repo.repo_id}; dispatch into this repo is paused")
            for warning in bundle.warnings:
                notes.append(warning)
            by_repo[repo.repo_id] = {
                "files_seen": len(bundle.files_seen),
                "instruction_blocks": len(bundle.instruction_texts),
                "task_blocks": len(bundle.task_texts),
                "handover_blocks": len(bundle.handover_texts),
                "report_blocks": len(bundle.report_texts),
                "protected_signal_blocks": len(bundle.protected_signals),
                "prebuilt_items": len(bundle.prebuilt_work_items),
                "normalized_items": len(normalized),
                "paused_by_protection": repo.repo_id.lower() in self._paused_repo_ids,
                "sources": bundle.source_diagnostics,
                "source_mismatch_summary": source_mismatch_summary,
                "warnings": list(bundle.warnings),
            }
        discovery_diag = {
            "repos": by_repo,
            "total_normalized_candidates": len(items),
            "normalized_by_source": dict(source_counts),
            "repos_with_source_mismatches": source_mismatch_repos,
        }
        return items, discovery_diag

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

    def _pilot_task_class(self, item: WorkItem) -> Optional[str]:
        title = item.title.lower()
        if item.severity != Severity.LOW:
            return None

        docs_terms = ["doc", "docs", "readme", "comment", "changelog", "format", "typo"]
        if item.category == WorkCategory.MAINTENANCE and any(term in title for term in docs_terms):
            return "docs_hygiene"

        test_terms = ["test", "pytest", "fixture", "assert", "mock", "flaky", "lint", "typing", "type"]
        if item.category in {WorkCategory.MAINTENANCE, WorkCategory.ANALYSIS, WorkCategory.BUG} and any(
            term in title for term in test_terms
        ):
            return "test_hardening"

        diagnostics_terms = ["investigate", "analyze", "analysis", "diagnostic", "logging", "triage", "trace"]
        if item.category == WorkCategory.ANALYSIS and any(term in title for term in diagnostics_terms):
            return "diagnostics_analysis"

        return None

    def _check_pilot_allowlist(self, item: WorkItem) -> Tuple[bool, str, Dict[str, Any]]:
        constraints = self.registry.global_constraints
        if not constraints.pilot_allowlist_enabled:
            return True, "disabled", {"pilot_allowlist_enabled": False}

        allowed_categories = {x.strip().lower() for x in constraints.pilot_allowed_categories if str(x).strip()}
        allowed_severities = {x.strip().lower() for x in constraints.pilot_allowed_severities if str(x).strip()}
        allowed_sources = {x.strip().lower() for x in constraints.pilot_allowed_sources if str(x).strip()}
        allowed_task_classes = {x.strip().lower() for x in constraints.pilot_allowed_task_classes if str(x).strip()}
        blocked_terms = [x.strip().lower() for x in constraints.pilot_blocked_title_terms if str(x).strip()]

        if allowed_categories and item.category.value.lower() not in allowed_categories:
            return False, "category_not_allowed", {"category": item.category.value}
        if allowed_severities and item.severity.value.lower() not in allowed_severities:
            return False, "severity_not_allowed", {"severity": item.severity.value}
        if allowed_sources and item.source.lower() not in allowed_sources:
            return False, "source_not_allowed", {"source": item.source}

        title = item.title.lower()
        matched_blocked_terms = [term for term in blocked_terms if term in title]
        if matched_blocked_terms:
            return False, "title_contains_blocked_term", {"matched_blocked_terms": matched_blocked_terms}

        task_class = self._pilot_task_class(item)
        if allowed_task_classes and (task_class is None or task_class.lower() not in allowed_task_classes):
            return False, "task_class_not_allowed", {"task_class": task_class}

        return True, "allowed", {"task_class": task_class, "pilot_allowlist_enabled": True}

    def _select_next_work_item(self, work_items: List[WorkItem]) -> Tuple[Optional[WorkItem], Dict[str, Any]]:
        active_runs = self.ledger.active_runs()
        active_by_repo: Dict[str, int] = {}
        for run in active_runs:
            repo = str(run.get("repo", "")).strip().lower()
            if not repo:
                continue
            active_by_repo[repo] = active_by_repo.get(repo, 0) + 1

        candidates: List[Tuple[float, WorkItem]] = []
        rejected_counts: Counter[str] = Counter()
        allowlist_reason_counts: Counter[str] = Counter()
        blocked_term_counts: Counter[str] = Counter()
        rejected_samples: Dict[str, List[Dict[str, Any]]] = {}
        rejected_items: List[Dict[str, Any]] = []

        def reject(reason: str, item: WorkItem, extra: Dict[str, Any] | None = None) -> None:
            rejected_counts[reason] += 1
            if reason == "pilot_allowlist" and extra:
                allowlist_reason = str(extra.get("allowlist_reason", "")).strip()
                if allowlist_reason:
                    allowlist_reason_counts[allowlist_reason] += 1
                matched_blocked_terms = extra.get("matched_blocked_terms")
                if isinstance(matched_blocked_terms, list):
                    for term in matched_blocked_terms:
                        normalized_term = str(term).strip().lower()
                        if normalized_term:
                            blocked_term_counts[normalized_term] += 1
            bucket = rejected_samples.setdefault(reason, [])
            if len(bucket) >= 3:
                return
            sample: Dict[str, Any] = {
                "work_item_id": item.work_item_id,
                "repo": item.repo,
                "title": item.title,
                "source": item.source,
                "status": item.status.value,
            }
            if extra:
                sample.update(extra)
            rejected_items.append({"reason": reason, **sample})
            bucket.append(sample)

        for item in work_items:
            if item.status == WorkStatus.RUNNING:
                reject("status_running", item)
                continue
            if item.status == WorkStatus.BLOCKED:
                reject("status_blocked", item, {"dependencies": list(item.dependencies)})
                continue
            if item.status not in {WorkStatus.NEW}:
                reject("status_not_dispatchable", item)
                continue

            repo = self.repo_index.get(item.repo.lower())
            if repo is None:
                reject("unknown_repo", item)
                continue
            if item.repo.lower() in self._paused_repo_ids:
                reject("paused_repo", item)
                continue

            repo_active = active_by_repo.get(item.repo.lower(), 0)
            if repo_active >= self.registry.global_constraints.max_active_workers_per_repo:
                reject(
                    "repo_concurrency_cap",
                    item,
                    {
                        "active": repo_active,
                        "limit": self.registry.global_constraints.max_active_workers_per_repo,
                    },
                )
                continue

            retries = self.ledger.retries_for_work_item(item.work_item_id)
            if retries >= self.registry.global_constraints.loop_retry_limit:
                reject(
                    "retry_limit",
                    item,
                    {
                        "retries": retries,
                        "limit": self.registry.global_constraints.loop_retry_limit,
                    },
                )
                continue

            allowlisted, allowlist_reason, allowlist_details = self._check_pilot_allowlist(item)
            if not allowlisted:
                reject(
                    "pilot_allowlist",
                    item,
                    {
                        "allowlist_reason": allowlist_reason,
                        **allowlist_details,
                    },
                )
                continue

            candidates.append((self._score(item), item))

        selection_diag: Dict[str, Any] = {
            "total_candidates": len(work_items),
            "eligible_count": len(candidates),
            "rejected_counts": dict(rejected_counts),
            "pilot_allowlist_reason_counts": dict(allowlist_reason_counts),
            "blocked_term_counts": dict(blocked_term_counts),
            "rejected_samples": rejected_samples,
            "rejected_items": rejected_items,
            "active_runs_by_repo": active_by_repo,
            "eligible_ranked": [],
        }

        if not candidates:
            return None, selection_diag
        candidates.sort(key=lambda entry: entry[0], reverse=True)
        selection_diag["eligible_ranked"] = [
            {
                "score": round(score, 3),
                "work_item_id": item.work_item_id,
                "repo": item.repo,
                "source": item.source,
                "severity": item.severity.value,
                "title": item.title,
            }
            for score, item in candidates[:5]
        ]
        return candidates[0][1], selection_diag

    def _human_selection_summary(self, selection_diag: Dict[str, Any]) -> str:
        rejected_counts = selection_diag.get("rejected_counts")
        if not isinstance(rejected_counts, dict):
            return "Selection diagnostics unavailable"
        if not rejected_counts:
            return "Selection diagnostics: no explicit rejections recorded"
        parts = [f"{reason}={count}" for reason, count in sorted(rejected_counts.items())]
        return "Selection filter breakdown: " + ", ".join(parts)

    def _build_no_eligible_work_items_diagnostics(
        self,
        *,
        discovery_diag: Dict[str, Any],
        selection_diag: Dict[str, Any],
    ) -> Dict[str, Any]:
        sources_checked: Dict[str, List[str]] = {}
        source_item_counts: Dict[str, Dict[str, int]] = {}
        repo_warnings: Dict[str, List[str]] = {}
        sources_with_candidates: Dict[str, List[str]] = {}
        for repo_id, repo_diag in (discovery_diag.get("repos") or {}).items():
            if not isinstance(repo_diag, dict):
                continue
            source_map = repo_diag.get("sources") if isinstance(repo_diag.get("sources"), dict) else {}
            sources_checked[repo_id] = list(source_map.keys())
            repo_counts = {
                source_name: int(source_info.get("extracted_candidate_count", 0) or 0)
                for source_name, source_info in source_map.items()
                if isinstance(source_info, dict)
            }
            source_item_counts[repo_id] = repo_counts
            active_sources = [source_name for source_name, count in repo_counts.items() if count > 0]
            if active_sources:
                sources_with_candidates[repo_id] = active_sources
            warnings = repo_diag.get("warnings")
            if isinstance(warnings, list) and warnings:
                repo_warnings[repo_id] = [str(entry) for entry in warnings if str(entry).strip()]

        rejected_counts = selection_diag.get("rejected_counts", {})
        rejected_candidates = selection_diag.get("rejected_items", [])
        total_discovered_candidates = sum(
            count
            for repo_counts in source_item_counts.values()
            for count in repo_counts.values()
        )
        status_rejection_counts = {
            name: int(count)
            for name, count in (rejected_counts.items() if isinstance(rejected_counts, dict) else [])
            if name in {"status_running", "status_blocked"} and int(count) > 0
        }
        all_rejections_are_running_or_blocked = bool(status_rejection_counts) and sum(status_rejection_counts.values()) == len(
            rejected_candidates
        )
        if total_discovered_candidates > 0 and all_rejections_are_running_or_blocked:
            explanation = (
                "No eligible work items were selected because every discovered candidate was already "
                "running or blocked."
            )
            reason_code = "all_candidates_running_or_blocked"
        else:
            explanation = "No eligible work items were selected because every discovered candidate was rejected during selection."
            reason_code = "all_candidates_rejected_during_selection"

        return {
            "reason_code": reason_code,
            "explanation": explanation,
            "details": {
                "total_discovered_candidates": total_discovered_candidates,
                "total_rejected_candidates": len(rejected_candidates),
                "sources_with_candidates": sources_with_candidates,
                "status_rejection_counts": status_rejection_counts,
            },
            "sources_checked": sources_checked,
            "item_counts_per_source": source_item_counts,
            "normalized_by_source": discovery_diag.get("normalized_by_source", {}),
            "repo_warnings": repo_warnings,
            "rejected_counts": rejected_counts,
            "rejected_candidates": rejected_candidates,
        }

    def _human_no_eligible_work_items_summary(self, discovery_diagnostics: Dict[str, Any]) -> str:
        repo_parts: List[str] = []
        for repo_id, counts in (discovery_diagnostics.get("item_counts_per_source") or {}).items():
            if not isinstance(counts, dict):
                continue
            counts_text = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
            repo_parts.append(f"{repo_id}[{counts_text}]")
        rejected = discovery_diagnostics.get("rejected_counts") or {}
        rejected_text = ", ".join(f"{name}={count}" for name, count in sorted(rejected.items())) if isinstance(rejected, dict) else ""
        summary = "Discovery diagnostics: checked " + "; ".join(repo_parts) if repo_parts else "Discovery diagnostics unavailable"
        if rejected_text:
            summary += f"; rejections: {rejected_text}"
        return summary

    def _new_run_id(self, repo_id: str) -> str:
        return f"{repo_id.lower()}-{uuid.uuid4().hex[:10]}"

    def _dispatch(self, item: WorkItem, run_id: str) -> Path:
        allowlisted, allowlist_reason, _ = self._check_pilot_allowlist(item)
        if not allowlisted:
            raise ValueError(f"Refusing dispatch for non-allowlisted task: {allowlist_reason}")

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

    def record_report_and_decision(
        self,
        *,
        run_id: str,
        selected: WorkItem,
        report: WorkerCompletionReport,
        response_meta: Optional[Dict[str, Any]] = None,
    ) -> OrchestrationDecision:
        decision = self._decide(selected, report)
        terminal_event = {
            WorkerOutcome.SUCCESS: "run_completed",
            WorkerOutcome.PARTIAL: "run_completed",
            WorkerOutcome.BLOCKED: "run_blocked",
            WorkerOutcome.FAILED: "run_failed",
        }[report.status]
        payload: Dict[str, Any] = {
            "run_id": run_id,
            "repo": selected.repo,
            "work_item_id": selected.work_item_id,
            "decision": asdict(decision),
            "report": report_to_jsonable(report),
        }
        if response_meta:
            payload["response_meta"] = response_meta
        self.ledger.append(terminal_event, payload)
        return decision

    def record_stopped(
        self,
        *,
        run_id: str,
        selected: WorkItem,
        reason_code: str,
        decision_reason: str,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> OrchestrationDecision:
        payload: Dict[str, Any] = {
            "run_id": run_id,
            "repo": selected.repo,
            "work_item_id": selected.work_item_id,
            "reason": reason_code,
        }
        if extra_payload:
            payload.update(extra_payload)
        self.ledger.append("run_stopped", payload)
        return OrchestrationDecision(action="stop", reason=decision_reason)


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
