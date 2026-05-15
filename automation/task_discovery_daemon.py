import logging
import threading
from typing import Optional

from automation.config import (
    CROSS_REPO_TODO_ENABLED,
    TASK_DISCOVERY_INTERVAL_SECONDS,
    TASK_DISCOVERY_LOW_TASK_THRESHOLD,
)
from automation.cross_repo_todo_ingestion import get_cross_repo_todo_service
from automation.master_prompt_orchestrator import MasterPromptOrchestrator
from automation.metrics import get_metrics_tracker
from automation.panel_task_dispatcher import get_task_panel_dispatcher

logger = logging.getLogger(__name__)

class TaskDiscoveryDaemon:
    """
    Background daemon that periodically checks for low task feeds and 
    triggers prompt generation and Todo ingestion.
    """
    def __init__(
        self, 
        interval_seconds: int = TASK_DISCOVERY_INTERVAL_SECONDS,
        low_task_threshold: int = TASK_DISCOVERY_LOW_TASK_THRESHOLD,
        orchestrator: Optional[MasterPromptOrchestrator] = None
    ):
        self.interval_seconds = interval_seconds
        self.low_task_threshold = low_task_threshold
        self._orchestrator = orchestrator
        self._stop_event = threading.Event()
        self._refresh_requested = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._metrics = get_metrics_tracker()

    @property
    def orchestrator(self) -> MasterPromptOrchestrator:
        if self._orchestrator is None:
            # Initialize with default settings; it will auto-discover repos
            self._orchestrator = MasterPromptOrchestrator()
        return self._orchestrator

    def start(self) -> None:
        """Start the daemon in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._refresh_requested.clear()
        get_task_panel_dispatcher().register_feed_empty_callback(self.trigger_immediate_refresh)
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TaskDiscoveryDaemon")
        self._thread.start()
        logger.info("TaskDiscoveryDaemon started.")

    def stop(self) -> None:
        """Stop the daemon."""
        self._stop_event.set()
        self._refresh_requested.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("TaskDiscoveryDaemon stopped.")

    def trigger_immediate_refresh(self) -> None:
        """Wake the daemon so the next iteration refreshes immediately."""
        self._refresh_requested.set()
        logger.info("Immediate task discovery refresh requested.")

    def _run_loop(self):
        force_refresh = False
        while not self._stop_event.is_set():
            try:
                force_refresh = force_refresh or self._consume_refresh_request()
                self.check_and_audit(force_refresh=force_refresh)
                force_refresh = False
            except Exception as e:
                logger.error(f"Error in TaskDiscoveryDaemon: {e}", exc_info=True)

            if self._stop_event.is_set():
                break

            if self._refresh_requested.wait(timeout=self.interval_seconds):
                self._refresh_requested.clear()
                force_refresh = True

    def _consume_refresh_request(self) -> bool:
        if not self._refresh_requested.is_set():
            return False
        self._refresh_requested.clear()
        return True

    def check_and_audit(self, *, force_refresh: bool = False):
        """Perform the task check and trigger audit if needed."""
        dispatcher = get_task_panel_dispatcher()
        todo_service = get_cross_repo_todo_service()
        orchestrator = self.orchestrator

        # 1. Refresh Todo ingestion
        if CROSS_REPO_TODO_ENABLED:
            logger.info("Refreshing CrossRepoTodoIngestionService...")
            try:
                todo_service.refresh()
                self._metrics.record_task_discovery_event("refresh", detail="todo_refresh_success")
            except Exception as e:
                logger.error(f"Failed to refresh Todo ingestion: {e}")
                self._metrics.record_task_discovery_event("refresh_failure", detail=str(e))

        # 2. Check for low task feeds
        # We check repos that the orchestrator is configured for
        repo_names = [config.name for config in orchestrator.refresh_repo_configs()]
        low_repos = dispatcher.get_low_task_repos(repo_names=repo_names, threshold=self.low_task_threshold)

        if force_refresh or low_repos:
            refresh_reason = "on_demand_refresh" if force_refresh and not low_repos else "triggering_audit"
            if force_refresh and not low_repos:
                logger.info("Immediate refresh requested. Triggering MasterPromptOrchestrator audit...")
            else:
                logger.info(f"Low tasks detected for repos: {low_repos}. Triggering MasterPromptOrchestrator audit...")
            self._metrics.record_task_discovery_event("low_feed", repos=low_repos, detail=refresh_reason)
            # Programmatically invoke MasterPromptOrchestrator to generate new prompt batches
            try:
                orchestrator.refresh_all_feeds()
                # After generating, we reset the dispatcher cache so it picks up the new files
                dispatcher.reset_cache()
                logger.info("MasterPromptOrchestrator audit complete and dispatcher cache reset.")
                self._metrics.record_task_discovery_event("audit_success", repos=low_repos)
            except Exception as e:
                logger.error(f"Failed to generate prompt batches: {e}")
                self._metrics.record_task_discovery_event("audit_failure", repos=low_repos, detail=str(e))
        else:
            logger.info("All repository feeds have sufficient tasks.")
            self._metrics.record_task_discovery_event("healthy_feeds", repos=repo_names)

_daemon_instance: Optional[TaskDiscoveryDaemon] = None

def get_task_discovery_daemon(**kwargs) -> TaskDiscoveryDaemon:
    """Return the singleton daemon instance."""
    global _daemon_instance
    if _daemon_instance is None:
        _daemon_instance = TaskDiscoveryDaemon(**kwargs)
    return _daemon_instance

def start_task_discovery_daemon(**kwargs) -> None:
    """Convenience function to start the daemon."""
    daemon = get_task_discovery_daemon(**kwargs)
    daemon.start()

def stop_task_discovery_daemon() -> None:
    """Convenience function to stop the daemon."""
    global _daemon_instance
    if _daemon_instance is not None:
        _daemon_instance.stop()

def trigger_immediate_refresh() -> None:
    """Convenience function to request an immediate discovery refresh."""
    get_task_discovery_daemon().trigger_immediate_refresh()
