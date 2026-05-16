"""
Metrics tracking for desktop agent automation.

This module provides metrics collection and reporting for:
- Seeded prompts (which prompts were assigned to which panels)
- Model selections (which models were chosen for each prompt)
- Panel processing statistics
- Success/failure rates
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from automation.cost_tracker import get_cost_tracker

# Import response parser types
try:
    from automation.response_parser import ResponseCategory
except ImportError:  # pragma: no cover
    # Define fallback for tests
    from enum import Enum
    class ResponseCategory(Enum):  # type: ignore
        COMPLETED = "completed"
        ASKING_CLARIFICATION = "asking_clarification"
        ERROR = "error"
        WORKING = "working"
        SUGGESTING_NEXT_STEPS = "suggesting_next_steps"


@dataclass
class PromptMetric:
    """Metrics for a single prompt seeding event."""
    timestamp: datetime
    panel_title: str
    prompt_index: int
    prompt_preview: str  # First 100 chars of prompt
    model_requested: Optional[str]
    success: bool
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "panel_title": self.panel_title,
            "prompt_index": self.prompt_index,
            "prompt_preview": self.prompt_preview,
            "model_requested": self.model_requested,
            "success": self.success,
            "error_message": self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> PromptMetric:
        """Deserialize from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            panel_title=data["panel_title"],
            prompt_index=data["prompt_index"],
            prompt_preview=data["prompt_preview"],
            model_requested=data.get("model_requested"),
            success=data["success"],
            error_message=data.get("error_message"),
        )


@dataclass
class ModelSelectionMetric:
    """Metrics for model picker interactions."""
    timestamp: datetime
    panel_title: str
    model_label: str
    success: bool
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "panel_title": self.panel_title,
            "model_label": self.model_label,
            "success": self.success,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ModelSelectionMetric:
        """Deserialize from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            panel_title=data["panel_title"],
            model_label=data["model_label"],
            success=data["success"],
        )


@dataclass
class CostMetric:
    """Metrics for cost tracking integration."""
    timestamp: datetime
    total_cost: float
    token_cost: float
    vision_cost: float
    api_calls: int
    budget_alerts: List[str]
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_cost": self.total_cost,
            "token_cost": self.token_cost,
            "vision_cost": self.vision_cost,
            "api_calls": self.api_calls,
            "budget_alerts": self.budget_alerts,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CostMetric":
        """Deserialize from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            total_cost=data["total_cost"],
            token_cost=data["token_cost"],
            vision_cost=data["vision_cost"],
            api_calls=data["api_calls"],
            budget_alerts=data["budget_alerts"],
        )


@dataclass
class ResponseFeedbackMetric:
    """Metrics for agent response feedback and learning."""
    timestamp: datetime
    panel_title: str
    prompt_id: Optional[str]  # Hash of the prompt that led to this response
    prompt_preview: Optional[str]  # First 100 chars of prompt
    response_category: ResponseCategory
    response_confidence: float
    response_evidence: List[str]
    response_sample: str  # Last 200 chars of response text
    is_sensitive: bool  # Whether response contains potentially sensitive data
    processing_time_seconds: Optional[float]  # How long the agent worked on this
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "panel_title": self.panel_title,
            "prompt_id": self.prompt_id,
            "prompt_preview": self.prompt_preview,
            "response_category": self.response_category.value,
            "response_confidence": self.response_confidence,
            "response_evidence": self.response_evidence,
            "response_sample": self.response_sample,
            "is_sensitive": self.is_sensitive,
            "processing_time_seconds": self.processing_time_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ResponseFeedbackMetric:
        """Deserialize from dictionary."""
        try:
            category = ResponseCategory(data["response_category"])
        except (ValueError, KeyError):
            category = ResponseCategory.WORKING  # fallback
        
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            panel_title=data["panel_title"],
            prompt_id=data.get("prompt_id"),
            prompt_preview=data.get("prompt_preview"),
            response_category=category,
            response_confidence=data.get("response_confidence", 0.0),
            response_evidence=data.get("response_evidence", []),
            response_sample=data.get("response_sample", ""),
            is_sensitive=data.get("is_sensitive", False),
            processing_time_seconds=data.get("processing_time_seconds"),
        )


@dataclass
class AssignmentMetric:
    """Metrics for prompt-panel assignments."""
    timestamp: datetime
    prompt_id: str
    panel_id: str
    panel_title: str
    repo: Optional[str]
    outcome: Optional[str] = None  # success/failure, determined later
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "prompt_id": self.prompt_id,
            "panel_id": self.panel_id,
            "panel_title": self.panel_title,
            "repo": self.repo,
            "outcome": self.outcome,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> AssignmentMetric:
        """Deserialize from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            prompt_id=data["prompt_id"],
            panel_id=data["panel_id"],
            panel_title=data["panel_title"],
            repo=data.get("repo"),
            outcome=data.get("outcome"),
        )


@dataclass
class WorkflowEventMetric:
    """Metrics for Keep → OK → New Chat workflow instrumentation."""
    timestamp: datetime
    panel_title: str
    panel_id: str
    step: str
    status: str
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "panel_title": self.panel_title,
            "panel_id": self.panel_id,
            "step": self.step,
            "status": self.status,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowEventMetric":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            panel_title=data.get("panel_title", ""),
            panel_id=data.get("panel_id", ""),
            step=data.get("step", "unknown"),
            status=data.get("status", "unknown"),
            detail=data.get("detail"),
        )


@dataclass
class SeedingAttemptMetric:
    """Metrics for prompt seeding attempts and retries."""

    timestamp: datetime
    panel_title: str
    panel_id: str
    attempt_number: int
    success: bool
    failure_reason: Optional[str] = None
    backoff_seconds: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "panel_title": self.panel_title,
            "panel_id": self.panel_id,
            "attempt_number": self.attempt_number,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "backoff_seconds": self.backoff_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeedingAttemptMetric":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            panel_title=data.get("panel_title", ""),
            panel_id=data.get("panel_id", ""),
            attempt_number=int(data.get("attempt_number", 0)),
            success=bool(data.get("success", False)),
            failure_reason=data.get("failure_reason"),
            backoff_seconds=data.get("backoff_seconds"),
        )


@dataclass
class TaskDiscoveryMetric:
    """Metrics for background task discovery daemon events."""

    timestamp: datetime
    event: str  # e.g., "refresh", "low_feed", "audit_success", "audit_failure"
    repos: List[str]
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event": self.event,
            "repos": self.repos,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskDiscoveryMetric":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            event=data.get("event", "unknown"),
            repos=list(data.get("repos", [])),
            detail=data.get("detail"),
        )


class MetricsTracker:
    """Tracks and persists automation metrics."""
    
    def __init__(self, metrics_path: Optional[Path] = None):
        """
        Initialize metrics tracker.
        
        Args:
            metrics_path: Path to metrics file (defaults to automation/metrics.json)
        """
        resolved_metrics_path = metrics_path
        if resolved_metrics_path is None:
            resolved_metrics_path = Path(
                os.environ.get(
                    "AUTOMATION_METRICS_PATH",
                    str(Path(__file__).parent / "metrics.json"),
                )
            )

        self.metrics_path = resolved_metrics_path
        assignment_override = (
            os.environ.get("AUTOMATION_ASSIGNMENT_METRICS_PATH")
            if metrics_path is None
            else None
        )
        self.assignment_metrics_path = Path(assignment_override) if assignment_override else (
            resolved_metrics_path.parent / "assignment_metrics.jsonl"
        )
        self.prompt_metrics: List[PromptMetric] = []
        self.model_metrics: List[ModelSelectionMetric] = []
        self.response_feedback_metrics: List[ResponseFeedbackMetric] = []
        self.assignment_metrics: List[AssignmentMetric] = []
        self.cost_metrics: List[CostMetric] = []
        self.workflow_metrics: List[WorkflowEventMetric] = []
        self.seeding_attempt_metrics: List[SeedingAttemptMetric] = []
        self.task_discovery_metrics: List[TaskDiscoveryMetric] = []
        self._load_metrics()
    
    def _load_metrics(self) -> None:
        """Load metrics from disk."""
        if self.metrics_path.exists():
            try:
                with self.metrics_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                
                self.prompt_metrics = [
                    PromptMetric.from_dict(m) 
                    for m in data.get("prompt_metrics", [])
                ]
                self.model_metrics = [
                    ModelSelectionMetric.from_dict(m)
                    for m in data.get("model_metrics", [])
                ]
                self.response_feedback_metrics = [
                    ResponseFeedbackMetric.from_dict(m)
                    for m in data.get("response_feedback_metrics", [])
                ]
                self.cost_metrics = [
                    CostMetric.from_dict(m)
                    for m in data.get("cost_metrics", [])
                ]
                self.workflow_metrics = [
                    WorkflowEventMetric.from_dict(m)
                    for m in data.get("workflow_metrics", [])
                ]
                self.seeding_attempt_metrics = [
                    SeedingAttemptMetric.from_dict(m)
                    for m in data.get("seeding_attempt_metrics", [])
                ]
                self.task_discovery_metrics = [
                    TaskDiscoveryMetric.from_dict(m)
                    for m in data.get("task_discovery_metrics", [])
                ]
            except Exception as e:
                print(f"[MetricsTracker] Warning: Could not load metrics: {e}")

        # Assignments are stored separately (JSONL) and should load even when metrics.json is absent.
        self._load_assignments()
    
    def _load_assignments(self) -> None:
        """Load assignment metrics from JSONL file."""
        if not self.assignment_metrics_path.exists():
            return

        try:
            loaded: List[AssignmentMetric] = []
            with self.assignment_metrics_path.open("r", encoding="utf-8") as f:
                content = f.read()
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        loaded.append(AssignmentMetric.from_dict(data))

            # Replace the list to make reloads idempotent (prevents duplication).
            self.assignment_metrics = loaded
        except Exception as e:
            print(f"[MetricsTracker] Warning: Could not load assignment metrics: {e}")
    
    def _save_metrics(self) -> None:
        """Persist metrics to disk."""
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "last_updated": datetime.now().isoformat(),
                "prompt_metrics": [m.to_dict() for m in self.prompt_metrics],
                "model_metrics": [m.to_dict() for m in self.model_metrics],
                "response_feedback_metrics": [m.to_dict() for m in self.response_feedback_metrics],
                "cost_metrics": [m.to_dict() for m in self.cost_metrics],
                "workflow_metrics": [m.to_dict() for m in self.workflow_metrics],
                "seeding_attempt_metrics": [m.to_dict() for m in self.seeding_attempt_metrics],
                "task_discovery_metrics": [m.to_dict() for m in self.task_discovery_metrics],
            }
            
            with self.metrics_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[MetricsTracker] Warning: Could not save metrics: {e}")
    
    def record_prompt_seeding(
        self,
        panel_title: str,
        prompt_index: int,
        prompt_text: str,
        model_requested: Optional[str],
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Record a prompt seeding event.
        
        Args:
            panel_title: VS Code window title
            prompt_index: Index of prompt in the batch
            prompt_text: Full prompt text
            model_requested: Model label requested (if any)
            success: Whether seeding succeeded
            error_message: Error message if failed
        """
        metric = PromptMetric(
            timestamp=datetime.now(),
            panel_title=panel_title,
            prompt_index=prompt_index,
            prompt_preview=prompt_text[:100],
            model_requested=model_requested,
            success=success,
            error_message=error_message,
        )
        
        self.prompt_metrics.append(metric)
        self._save_metrics()
        
        print(f"[MetricsTracker] Recorded prompt seeding: panel={panel_title[:40]}, "
              f"prompt_idx={prompt_index}, model={model_requested}, success={success}")
    
    def record_model_selection(
        self,
        panel_title: str,
        model_label: str,
        success: bool,
    ) -> None:
        """
        Record a model selection event.
        
        Args:
            panel_title: VS Code window title
            model_label: Model label selected
            success: Whether selection succeeded
        """
        metric = ModelSelectionMetric(
            timestamp=datetime.now(),
            panel_title=panel_title,
            model_label=model_label,
            success=success,
        )
        
        self.model_metrics.append(metric)
        self._save_metrics()
        
        print(f"[MetricsTracker] Recorded model selection: panel={panel_title[:40]}, "
              f"model={model_label}, success={success}")

    def record_task_discovery_event(
        self,
        event: str,
        repos: Optional[List[str]] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Record a task discovery daemon event."""
        metric = TaskDiscoveryMetric(
            timestamp=datetime.now(),
            event=event,
            repos=repos or [],
            detail=detail,
        )
        self.task_discovery_metrics.append(metric)
        self._save_metrics()
        if detail:
            print(f"[MetricsTracker] Task discovery event: {event} ({detail}) repos={metric.repos}")
        else:
            print(f"[MetricsTracker] Task discovery event: {event} repos={metric.repos}")

    def record_keep_new_chat_event(
        self,
        panel_title: str,
        panel_id: str,
        step: str,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        """Record a Keep → OK → New Chat workflow event."""
        metric = WorkflowEventMetric(
            timestamp=datetime.now(),
            panel_title=panel_title,
            panel_id=panel_id,
            step=step,
            status=status,
            detail=detail,
        )

        self.workflow_metrics.append(metric)
        self._save_metrics()

        if status != "success":
            detail_msg = detail or "no detail"
            print(
                f"[MetricsTracker] Workflow event issue: panel={panel_title[:40]}, "
                f"step={step}, status={status}, detail={detail_msg}"
            )
    
    def record_cost_snapshot(self) -> None:
        """
        Record a snapshot of current cost metrics.
        """
        cost_tracker = get_cost_tracker()
        session_totals = cost_tracker.get_session_totals()
        budget_alerts = cost_tracker.check_budget_alerts()
        
        metric = CostMetric(
            timestamp=datetime.now(),
            total_cost=session_totals.get("total_cost", 0.0),
            token_cost=session_totals.get("token_cost", 0.0),
            vision_cost=session_totals.get("vision_cost", 0.0),
            api_calls=int(session_totals.get("text_events", 0) + session_totals.get("vision_events", 0)),
            budget_alerts=budget_alerts,
        )
        
        self.cost_metrics.append(metric)
        self._save_metrics()
        
        if budget_alerts:
            print(f"[MetricsTracker] Cost snapshot recorded with {len(budget_alerts)} budget alerts")
        else:
            print(f"[MetricsTracker] Cost snapshot recorded: ${metric.total_cost:.4f} total")
    
    def record_assignment(
        self,
        prompt_id: str,
        panel_id: str,
        panel_title: str,
        repo: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> None:
        """
        Record a prompt-panel assignment.
        
        Args:
            prompt_id: Unique identifier for the prompt (hash)
            panel_id: Unique identifier for the panel
            panel_title: VS Code window title
            repo: Repository name if applicable
            outcome: Outcome of the assignment (success/failure), can be updated later
        """
        metric = AssignmentMetric(
            timestamp=datetime.now(),
            prompt_id=prompt_id,
            panel_id=panel_id,
            panel_title=panel_title,
            repo=repo,
            outcome=outcome,
        )
        
        self.assignment_metrics.append(metric)
        
        # Append to JSONL file
        try:
            self.assignment_metrics_path.parent.mkdir(parents=True, exist_ok=True)
            with self.assignment_metrics_path.open("a", encoding="utf-8") as f:
                json.dump(metric.to_dict(), f)
                f.write("\n")
        except Exception as e:
            print(f"[MetricsTracker] Warning: Could not save assignment metric: {e}")
        
        print(f"[MetricsTracker] Recorded assignment: prompt_id={prompt_id[:8]}, "
              f"panel_id={panel_id[:8]}, panel={panel_title[:40]}, repo={repo}")

    def record_seeding_attempt(
        self,
        panel_title: str,
        panel_id: str,
        attempt_number: int,
        success: bool,
        failure_reason: Optional[str] = None,
        backoff_seconds: Optional[int] = None,
    ) -> None:
        """Record a prompt seeding attempt and any retry backoff applied."""

        metric = SeedingAttemptMetric(
            timestamp=datetime.now(),
            panel_title=panel_title,
            panel_id=panel_id,
            attempt_number=attempt_number,
            success=success,
            failure_reason=failure_reason,
            backoff_seconds=backoff_seconds,
        )

        self.seeding_attempt_metrics.append(metric)
        self._save_metrics()

        if not success:
            detail_msg = failure_reason or "no detail"
            print(
                f"[MetricsTracker] Seeding attempt failed: panel={panel_title[:40]}, "
                f"attempt={attempt_number}, reason={detail_msg}, backoff={backoff_seconds}s"
            )
    
    def update_assignment_outcome(
        self,
        prompt_id: str,
        panel_id: str,
        outcome: str,
    ) -> None:
        """
        Update the outcome of an existing assignment.
        
        Args:
            prompt_id: Prompt identifier
            panel_id: Panel identifier
            outcome: New outcome value
        """
        for metric in self.assignment_metrics:
            if metric.prompt_id == prompt_id and metric.panel_id == panel_id:
                metric.outcome = outcome
                break
        
        # Note: For simplicity, we don't update the JSONL file, as it's append-only.
        # If needed, we could rewrite the file, but for now, keep in memory.
    
    def get_assignments_by_panel(self, panel_id: Optional[str] = None, panel_title: Optional[str] = None) -> List[AssignmentMetric]:
        """
        Get assignments filtered by panel.
        
        Args:
            panel_id: Filter by panel ID
            panel_title: Filter by panel title
            
        Returns:
            List of matching assignments
        """
        matches = []
        for metric in self.assignment_metrics:
            if panel_id and metric.panel_id != panel_id:
                continue
            if panel_title and metric.panel_title != panel_title:
                continue
            matches.append(metric)
        return matches
    
    def get_assignments_by_prompt(self, prompt_id: str) -> List[AssignmentMetric]:
        """
        Get assignments for a specific prompt.
        
        Args:
            prompt_id: Prompt identifier
            
        Returns:
            List of assignments for this prompt
        """
        return [m for m in self.assignment_metrics if m.prompt_id == prompt_id]
    
    def record_response_feedback(
        self,
        panel_title: str,
        response_category: ResponseCategory,
        response_confidence: float,
        response_evidence: List[str],
        response_sample: str,
        prompt_id: Optional[str] = None,
        prompt_preview: Optional[str] = None,
        is_sensitive: bool = False,
        processing_time_seconds: Optional[float] = None,
    ) -> None:
        """
        Record response feedback for learning and analysis.
        
        Args:
            panel_title: VS Code window title
            response_category: Parsed response category
            response_confidence: Confidence score (0.0-1.0)
            response_evidence: List of patterns that matched
            response_sample: Sample of response text (last 200 chars)
            prompt_id: Hash identifier of the prompt that led to this response
            prompt_preview: First 100 chars of the prompt
            is_sensitive: Whether response contains sensitive data
            processing_time_seconds: How long the agent worked on this task
        """
        if is_sensitive:
            # Don't store sensitive response content
            response_sample = "[REDACTED - SENSITIVE CONTENT]"
            response_evidence = ["[REDACTED]"]
        
        metric = ResponseFeedbackMetric(
            timestamp=datetime.now(),
            panel_title=panel_title,
            prompt_id=prompt_id,
            prompt_preview=prompt_preview,
            response_category=response_category,
            response_confidence=response_confidence,
            response_evidence=response_evidence,
            response_sample=response_sample,
            is_sensitive=is_sensitive,
            processing_time_seconds=processing_time_seconds,
        )
        
        self.response_feedback_metrics.append(metric)
        self._save_metrics()
        
        print(f"[MetricsTracker] Recorded response feedback: panel={panel_title[:40]}, "
              f"category={response_category.value}, confidence={response_confidence:.2f}")
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.
        
        Returns:
            Dictionary with summary statistics
        """
        total_prompts = len(self.prompt_metrics)
        successful_prompts = sum(1 for m in self.prompt_metrics if m.success)
        failed_prompts = total_prompts - successful_prompts
        
        total_model_selections = len(self.model_metrics)
        successful_models = sum(1 for m in self.model_metrics if m.success)
        failed_models = total_model_selections - successful_models
        
        # Count by model
        model_counts: Dict[str, int] = {}
        for metric in self.prompt_metrics:
            if metric.model_requested:
                model_counts[metric.model_requested] = model_counts.get(metric.model_requested, 0) + 1
        
        # Count by prompt index
        prompt_index_counts: Dict[int, int] = {}
        for metric in self.prompt_metrics:
            idx = metric.prompt_index
            prompt_index_counts[idx] = prompt_index_counts.get(idx, 0) + 1
        
        # Response feedback statistics
        total_responses = len(self.response_feedback_metrics)
        category_counts: Dict[str, int] = {}
        for response_metric in self.response_feedback_metrics:
            category = response_metric.response_category.value
            category_counts[category] = category_counts.get(category, 0) + 1
        
        avg_confidence = (
            sum(m.response_confidence for m in self.response_feedback_metrics) / total_responses
            if total_responses > 0 else 0
        )
        
        sensitive_responses = sum(1 for m in self.response_feedback_metrics if m.is_sensitive)
        
        # Assignment statistics
        total_assignments = len(self.assignment_metrics)
        repo_counts: Dict[str, int] = {}
        outcome_counts: Dict[str, int] = {}
        for assignment_metric in self.assignment_metrics:
            if assignment_metric.repo:
                repo_counts[assignment_metric.repo] = repo_counts.get(assignment_metric.repo, 0) + 1
            if assignment_metric.outcome:
                outcome_counts[assignment_metric.outcome] = outcome_counts.get(assignment_metric.outcome, 0) + 1
        
        # Cost statistics
        total_cost_snapshots = len(self.cost_metrics)
        if self.cost_metrics:
            latest_cost = self.cost_metrics[-1]
            total_budget_alerts = sum(len(m.budget_alerts) for m in self.cost_metrics)
        else:
            latest_cost = None
            total_budget_alerts = 0
        
        return {
            "total_prompts_seeded": total_prompts,
            "successful_prompts": successful_prompts,
            "failed_prompts": failed_prompts,
            "success_rate": successful_prompts / total_prompts if total_prompts > 0 else 0,
            "total_model_selections": total_model_selections,
            "successful_model_selections": successful_models,
            "failed_model_selections": failed_models,
            "model_usage": model_counts,
            "prompt_index_usage": prompt_index_counts,
            "total_response_feedback": total_responses,
            "response_categories": category_counts,
            "avg_response_confidence": avg_confidence,
            "sensitive_responses": sensitive_responses,
            "total_assignments": total_assignments,
            "assignments_by_repo": repo_counts,
            "assignment_outcomes": outcome_counts,
            "total_cost_snapshots": total_cost_snapshots,
            "latest_total_cost": latest_cost.total_cost if latest_cost else 0.0,
            "latest_token_cost": latest_cost.token_cost if latest_cost else 0.0,
            "latest_vision_cost": latest_cost.vision_cost if latest_cost else 0.0,
            "latest_api_calls": latest_cost.api_calls if latest_cost else 0,
            "total_budget_alerts": total_budget_alerts,
        }
    
    def print_summary(self) -> None:
        """Print a formatted summary of metrics."""
        summary = self.get_summary()
        
        print("\n" + "="*70)
        print("AUTOMATION METRICS SUMMARY")
        print("="*70 + "\n")
        
        print("📊 PROMPT SEEDING")
        print("-" * 70)
        print(f"Total attempts:     {summary['total_prompts_seeded']}")
        print(f"Successful:         {summary['successful_prompts']}")
        print(f"Failed:             {summary['failed_prompts']}")
        print(f"Success rate:       {summary['success_rate']:.1%}")
        print()
        
        if summary['model_usage']:
            print("🤖 MODEL USAGE")
            print("-" * 70)
            for model, count in sorted(summary['model_usage'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {model}: {count}")
            print()
        
        if summary['prompt_index_usage']:
            print("📝 PROMPT DISTRIBUTION")
            print("-" * 70)
            for idx, count in sorted(summary['prompt_index_usage'].items()):
                print(f"  Prompt {idx}: {count}")
            print()
        
        print("🎯 MODEL SELECTION")
        print("-" * 70)
        print(f"Total attempts:     {summary['total_model_selections']}")
        print(f"Successful:         {summary['successful_model_selections']}")
        print(f"Failed:             {summary['failed_model_selections']}")
        print()
        
        if summary.get('total_response_feedback', 0) > 0:
            print("🧠 RESPONSE FEEDBACK")
            print("-" * 70)
            print(f"Total responses:    {summary['total_response_feedback']}")
            print(f"Avg confidence:     {summary['avg_response_confidence']:.2f}")
            print(f"Sensitive:          {summary['sensitive_responses']}")
            print()
            
            if summary['response_categories']:
                print("Response Categories:")
                for category, count in sorted(summary['response_categories'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  {category}: {count}")
                print()
        
        if summary.get('total_assignments', 0) > 0:
            print("🔗 PROMPT-PANEL ASSIGNMENTS")
            print("-" * 70)
            print(f"Total assignments:  {summary['total_assignments']}")
            print()
            
            if summary['assignments_by_repo']:
                print("Assignments by Repo:")
                for repo, count in sorted(summary['assignments_by_repo'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  {repo}: {count}")
                print()
            
            if summary['assignment_outcomes']:
                print("Assignment Outcomes:")
                for outcome, count in sorted(summary['assignment_outcomes'].items(), key=lambda x: x[1], reverse=True):
                    print(f"  {outcome}: {count}")
                print()
        
        if summary.get('total_cost_snapshots', 0) > 0:
            print("💰 COST TRACKING")
            print("-" * 70)
            print(f"Cost snapshots:     {summary['total_cost_snapshots']}")
            print(f"Latest total cost:  ${summary['latest_total_cost']:.4f}")
            print(f"Latest token cost:  ${summary['latest_token_cost']:.4f}")
            print(f"Latest vision cost: ${summary['latest_vision_cost']:.4f}")
            print(f"Latest API calls:   {summary['latest_api_calls']}")
            print(f"Budget alerts:      {summary['total_budget_alerts']}")
            print()
        
        print("="*70 + "\n")


# Global singleton instance
_tracker_instance: Optional[MetricsTracker] = None


def get_metrics_tracker() -> MetricsTracker:
    """Get the global metrics tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = MetricsTracker()
    return _tracker_instance
