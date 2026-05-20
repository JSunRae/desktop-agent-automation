from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from dotenv import dotenv_values

from automation.agent_selection_policy import AdaptiveAgentSelectionPolicy
from automation.config import (
    AGENT_SELECTION_MODE,
    COORDINATION_GUARD_BLOCK_OVERLAPS,
    COORDINATION_GUARD_ENABLED,
    CROSS_REPO_TODO_ENABLED,
    ENABLE_WSL_DOC_CACHE,
    MASTER_AGENT_REPO_CONFIGS,
    NORTH_STAR_ENABLED,
    WSL_PATH_PROBE_TIMEOUT_SECONDS,
)
from automation.cost_tracker import get_cost_tracker
from automation.cross_repo_todo_ingestion import (
    CrossRepoDependencyAnalysis,
    CrossRepoTodoIngestionService,
    TodoItem,
    get_cross_repo_todo_service,
)
from automation.feedback_analyzer import (
    FeedbackAnalyzer,
    FeedbackInsights,
    get_feedback_analyzer,
)
from automation.prompt_resolver import PROMPT_FEED_FILENAME
from automation.title_parsing import extract_repo_name_from_vscode_window_title
from automation.utils import probe_wsl_path

# North Star coordination (optional — degrades gracefully when repos are unreachable)
try:
    from automation.coordination_guard import CoordinationGuard, get_coordination_guard
    from automation.north_star import (
        REPO_DEPENDENCY_ORDER,
        NorthStarContext,
        get_north_star,
    )
    _NORTH_STAR_AVAILABLE = True
except ImportError:  # pragma: no cover
    _NORTH_STAR_AVAILABLE = False
    REPO_DEPENDENCY_ORDER = []

OpenAIClient: Any = None
OpenAIAuthenticationError: Any = ()
OpenAIAPIStatusError: Any = ()
try:
    from openai import APIStatusError as _OpenAIAPIStatusError
    from openai import AuthenticationError as _OpenAIAuthenticationError
    from openai import OpenAI as _OpenAIClient

    OpenAIClient = _OpenAIClient
    OpenAIAuthenticationError = _OpenAIAuthenticationError
    OpenAIAPIStatusError = _OpenAIAPIStatusError
except ImportError:  # pragma: no cover - openai is an optional dependency in tests
    pass

_COST_TRACKER = get_cost_tracker()
REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_DOTENV_PATH = REPO_ROOT / ".env"
OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"

DEFAULT_DOCS_ROOT = Path(
    os.environ.get(
        "MASTER_AGENT_DOCS_ROOT",
        r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\tf_1\docs",
    )
)
DEFAULT_OPEN_TASKS_ROOT = Path(
    os.environ.get(
        "MASTER_AGENT_OPEN_TASKS_ROOT",
        str(DEFAULT_DOCS_ROOT / "open_tasks"),
    )
)
DEFAULT_OUTPUT_DIR = Path(os.environ.get("MASTER_AGENT_PROMPT_DIR", "tasks/generated_prompts"))
DEFAULT_MODEL = os.environ.get("MASTER_AGENT_MODEL", "gpt-5.4")
DEFAULT_ALLOWED_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
}
DEFAULT_MAX_FILE_SIZE = int(os.environ.get("MASTER_AGENT_MAX_FILE_BYTES", "200000"))
DOCS_CACHE_ROOT = Path(
    os.environ.get(
        "MASTER_AGENT_DOCS_CACHE_ROOT",
        os.environ.get("DOCS_CACHE_ROOT", str(Path("state") / "docs_cache")),
    )
)


class OpenAICredentialError(RuntimeError):
    """Raised when OpenAI credentials are missing or rejected."""


@dataclass(frozen=True)
class OpenAICredentialState:
    source: str
    repo_dotenv_path: Path
    repo_dotenv_exists: bool


def _read_repo_openai_api_key() -> Optional[str]:
    if not REPO_DOTENV_PATH.exists():
        return None
    try:
        value = dotenv_values(REPO_DOTENV_PATH).get(OPENAI_API_KEY_ENV_VAR)
    except OSError:
        return None
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _resolve_openai_api_key() -> Tuple[Optional[str], OpenAICredentialState]:
    api_key = (os.environ.get(OPENAI_API_KEY_ENV_VAR) or "").strip() or None
    repo_api_key = _read_repo_openai_api_key()
    repo_dotenv_exists = REPO_DOTENV_PATH.exists()

    if api_key and repo_api_key and api_key == repo_api_key:
        source = f"process environment (matches {REPO_DOTENV_PATH})"
    elif api_key:
        source = "process environment"
    elif repo_api_key:
        source = str(REPO_DOTENV_PATH)
    else:
        source = "missing"

    return api_key, OpenAICredentialState(
        source=source,
        repo_dotenv_path=REPO_DOTENV_PATH,
        repo_dotenv_exists=repo_dotenv_exists,
    )


def _format_missing_openai_api_key_message(state: OpenAICredentialState) -> str:
    repo_hint = (
        f"Repo-root .env exists at {state.repo_dotenv_path} but does not define {OPENAI_API_KEY_ENV_VAR}."
        if state.repo_dotenv_exists
        else f"Repo-root .env was not found at {state.repo_dotenv_path}."
    )
    return (
        "OpenAI credentials are not ready for automation.master_prompt_orchestrator: "
        f"{OPENAI_API_KEY_ENV_VAR} is missing. Resolution order is process environment first, "
        f"then {state.repo_dotenv_path}. {repo_hint} "
        "The secret value is external to repository code; provide it in the process environment or add "
        f"{OPENAI_API_KEY_ENV_VAR}=... to the repo-root .env before running a live refresh."
    )


def _format_invalid_openai_api_key_message(
    state: OpenAICredentialState,
    exc: BaseException,
) -> str:
    return (
        "OpenAI credentials are not ready for automation.master_prompt_orchestrator: "
        f"authentication failed for {OPENAI_API_KEY_ENV_VAR} loaded from {state.source}. "
        f"OpenAI detail: {exc}. "
        "The secret value is external to repository code; replace it in the process environment or repo-root .env, "
        "then rerun `python -m automation.master_prompt_orchestrator --check-openai-credentials`."
    )


def _raise_for_openai_request_error(
    exc: BaseException,
    state: OpenAICredentialState,
) -> None:
    if OpenAIAuthenticationError and isinstance(exc, OpenAIAuthenticationError):
        raise OpenAICredentialError(_format_invalid_openai_api_key_message(state, exc)) from exc

    if OpenAIAPIStatusError and isinstance(exc, OpenAIAPIStatusError):
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            raise OpenAICredentialError(_format_invalid_openai_api_key_message(state, exc)) from exc
        raise RuntimeError(
            "OpenAI request failed for automation.master_prompt_orchestrator "
            f"using credentials from {state.source}: {exc}"
        ) from exc


def _is_wsl_unc_path(path: Path) -> bool:
    raw_path = str(path)
    return raw_path.startswith("\\\\wsl.") or raw_path.startswith("//wsl.")


def _safe_resolve(path: Path) -> Path:
    if _is_wsl_unc_path(path):
        if not probe_wsl_path(path, WSL_PATH_PROBE_TIMEOUT_SECONDS):
            return path
    try:
        return path.resolve()
    except OSError:
        return path


def _path_key(path: Path) -> str:
    return str(_safe_resolve(path))


def _extract_repo_name_from_window_title(window_title: str) -> Optional[str]:
    """
    Extract repository name from VS Code window title.
    
    VS Code window titles follow the format:
    "[filename/chat] - [repo-name] - Visual Studio Code"
    
    Examples:
        "test.py - Trading-Win - Visual Studio Code" -> "Trading-Win"
        "TASK: Review... - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code" -> "tf_1"
    
    Args:
        window_title: The window title string from VS Code
        
    Returns:
        Repository name if found, None otherwise
    """
    return extract_repo_name_from_vscode_window_title(window_title)


def _find_repo_docs_by_name(repo_name: str) -> List[Path]:
    """
    Find docs folder for a given repository name.
    
    Searches common locations:
    - Windows: C:/Users/[user]/Documents/Vs Code Projects/[repo]/docs
    - WSL: //wsl.localhost/[distro]/home/[user]/[projects]/[repo]/docs
    
    Args:
        repo_name: Repository name extracted from window title
        
    Returns:
        List of found docs paths (may be empty)
    """
    roots: List[Path] = []
    checked: set[str] = set()
    
    # Search Windows common locations
    user_home = Path.home()
    search_paths = [
        user_home / "Documents" / "Vs Code Projects" / repo_name,
        user_home / "Documents" / "Projects" / repo_name,
        user_home / "Projects" / repo_name,
        user_home / repo_name,
    ]
    
    # Search WSL locations
    wsl_base = Path(r"\\wsl.localhost")
    if probe_wsl_path(wsl_base, WSL_PATH_PROBE_TIMEOUT_SECONDS):
        for distro in ["Ubuntu-24.04", "Ubuntu", "Ubuntu-22.04", "Ubuntu-20.04"]:
            distro_path = wsl_base / distro
            if probe_wsl_path(distro_path, WSL_PATH_PROBE_TIMEOUT_SECONDS):
                try:
                    # Try common user directories
                    for home_dir in distro_path.glob("home/*"):
                        if probe_wsl_path(home_dir, WSL_PATH_PROBE_TIMEOUT_SECONDS) and home_dir.is_dir():
                            search_paths.extend([
                                home_dir / "wsl_projects" / repo_name,
                                home_dir / "projects" / repo_name,
                                home_dir / repo_name,
                            ])
                except Exception:
                    pass
    
    # Check each path for docs folder
    for base_path in search_paths:
        docs_path = base_path / "docs"
        if _is_wsl_unc_path(docs_path):
            if not probe_wsl_path(docs_path, WSL_PATH_PROBE_TIMEOUT_SECONDS):
                continue
        if docs_path.is_dir():
            key = _path_key(docs_path)
            if key not in checked:
                roots.append(docs_path)
                checked.add(key)
                
                # Also check for open_tasks subfolder
                open_tasks_path = docs_path / "open_tasks"
                if _is_wsl_unc_path(open_tasks_path):
                    if not probe_wsl_path(open_tasks_path, WSL_PATH_PROBE_TIMEOUT_SECONDS):
                        continue
                if open_tasks_path.is_dir():
                    key_ot = _path_key(open_tasks_path)
                    if key_ot not in checked:
                        roots.append(open_tasks_path)
                        checked.add(key_ot)
    
    # Conflict Detection: If we found docs in more than one unique base location (e.g. Windows AND WSL),
    # treating them as merged is dangerous. We should warn and default to Safe Mode (None)
    # unless user explicitly configured it.
    
    # Analyze unique roots (ignoring open_tasks subfolders)
    unique_bases = set()
    for root in roots:
        # If this is an 'open_tasks' folder, map it to its parent 'docs' folder for counting purposes
        if root.name == "open_tasks" and root.parent.name == "docs":
            unique_bases.add(_path_key(root.parent))
        else:
            unique_bases.add(_path_key(root))
            
    if len(unique_bases) > 1:
        # We found distinct 'docs' roots for the same repo name (e.g. one in WSL, one in Windows)
        print(f"\n[WARNING] AMBIGUOUS REPO LOCATION: found '{repo_name}' in multiple locations:")
        for b in unique_bases:
            print(f"  - {b}")
        print("To prevent mixing context from different environments, this repo will be SKIPPED.")
        print("Please rename one of the folders or explicitly configure paths in MASTER_AGENT_REPO_CONFIGS.\n")
        return []
    
    return roots


def _detect_repo_doc_roots() -> List[Path]:
    """Infer docs and open_tasks roots from the current working tree."""
    roots: List[Path] = []
    try:
        cwd = Path.cwd()
    except Exception:
        return roots
    checked: set[str] = set()
    for base in [cwd, *list(cwd.parents)[:4]]:
        docs_path = base / "docs"
        if docs_path.is_dir():
            key = _path_key(docs_path)
            if key not in checked:
                roots.append(docs_path)
                checked.add(key)
            open_tasks_path = docs_path / "open_tasks"
            if open_tasks_path.is_dir():
                key_ot = _path_key(open_tasks_path)
                if key_ot not in checked:
                    roots.append(open_tasks_path)
                    checked.add(key_ot)
    return roots


def get_foreground_window_title() -> Optional[str]:
    """
    Get the title of the foreground window.
    
    Returns:
        Window title string if successful, None otherwise
    """
    try:
        import ctypes
        # Get foreground window handle
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        
        if hwnd == 0:
            return None
        
        # Get window title length
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return None
        
        # Get window title
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        
        return buffer.value
    except Exception:
        return None


def detect_repo_from_foreground_window() -> List[Path]:
    """
    Detect repository docs folder from the foreground VS Code window.
    
    Returns:
        List of docs paths found for the foreground repo
    """
    window_title = get_foreground_window_title()
    if not window_title:
        return []
    
    # Check if it's a VS Code window
    if "Visual Studio Code" not in window_title:
        return []
    
    repo_name = _extract_repo_name_from_window_title(window_title)
    if not repo_name:
        return []
    
    return _find_repo_docs_by_name(repo_name)

SYSTEM_PROMPT = dedent(
        """
        Review the Todo document and all .md files in the docs folder as a senior engineer coordinating a team of autonomous agents. Identify all open tasks, determine their priority, and check whether any tasks are blocked by incomplete dependencies or documents. No agents currently have active assignments, so select only the highest-priority tasks that can be executed now.

        Documentation rules:
        Agents often create .md documents while working. If a document describes work that is fully completed and is no longer needed for understanding or maintaining the repo, mark it for filing into the docs/completed folder. The root docs folder should contain only essential, high-level documents (e.g., Todo, Architecture, README-level references).

        Your responsibilities:
        Assign tasks to agents without conflicts or overlapping work. Only provide actionable prompts for unblocked tasks. If a task is blocked, notify me (Executive of the repo) rather than generating its prompt. When more agents become available, I will request additional prompts.

        Agent selection:
        Choose the most suitable agent for each task. Options: Grok – free, fast, low intelligence. GPT-5.1 Codex Mini – moderate cost, quick, moderately smart. Codex – higher capability. GPT-5.1-Codex-Max (Preview) – preferred for complex, long-running, high-value tasks.

        For each task assignment:
        State which agent you selected and why. Provide the full agent prompt in one clean, copy-and-paste block (no code fences). Up to 20 tasks total. Avoid Markdown code blocks so prompts paste cleanly.

        Priorities:
        Ensure we stay in scope of the project. Any complicated work is reviewed for errors, issues, or oversight. Keep the repo easy to use for agents, and document everything appropriately (Task assignments, Todo, ReadMe, architecture). Up to 20 tasks maximum.
        """
)


@dataclass
class RepoConfig:
    """Configuration for a single repository's prompt generation."""
    name: str
    docs_dirs: List[Path]
    role: Optional[str] = None
    repo_root: Optional[Path] = None
    config_source: str = "explicit"


@dataclass
class DocsSourceStatus:
    repo_name: str
    directory: Path
    repo_root: Optional[Path]
    config_source: str
    status: str
    issue_kind: Optional[str]
    cache_available: bool
    live_document_count: int
    expected_relative_dir: Optional[str]
    message: str
    next_steps: List[str]

    @property
    def live_ready(self) -> bool:
        return self.status == "live_ready"


@dataclass
class RepoReadinessReport:
    repo_name: str
    config_source: str
    repo_root: Optional[Path]
    docs_sources: List[DocsSourceStatus]
    cache_dir: Path
    cache_available: bool
    live_ready: bool
    seeding_ready: bool
    status: str
    next_steps: List[str]


@dataclass
class PromptMetadata:
    """Metadata for generated prompts to track quality and effectiveness."""
    prompt_id: str
    prompt_hash: str
    generated_at: str
    repo_name: str
    source_documents: List[str]
    rationale: str
    expected_difficulty: str  # "simple", "moderate", "complex"
    dependencies: List[str]  # List of blocking tasks/requirements
    task_type: str  # "bug_fix", "feature", "refactor", "testing", "documentation", "other"
    quality_score: float  # 0.0-1.0 score from validation
    template_used: Optional[str] = None
    adaptive_complexity_level: Optional[str] = None  # Adjusted based on agent success rates


@dataclass
class PromptTemplate:
    """Template for common task types with proven success patterns."""
    name: str
    task_type: str
    success_rate: float
    template_text: str
    context_requirements: List[str]  # What context is needed
    complexity_level: str  # "simple", "moderate", "complex"
    typical_dependencies: List[str]


@dataclass
class RepositoryAnalysis:
    """Analysis of repository structure and patterns."""
    repo_name: str
    primary_language: Optional[str]
    file_count: int
    architecture_style: Optional[str]  # e.g., "microservices", "monolithic", "layered"
    code_patterns: List[str]  # Common patterns found
    conventions: Dict[str, str]  # Naming conventions, style guides, etc.
    dependencies: List[str]  # External dependencies found
    test_coverage_estimate: Optional[float]


@dataclass
class DocumentSlice:
    path: Path
    content: str
    characters: int
    modified_epoch: float
    repo_name: str  # Track which repo this document belongs to


@dataclass
class PromptBatchResult:
    output_path: Path
    prompt_count: int
    raw_text: str
    documents: List[DocumentSlice]
    repo_name: str  # Track which repo this batch belongs to
    metadata_file: Optional[Path] = None  # Path to metadata JSON file
    prompts_with_metadata: List[Tuple[str, PromptMetadata]] = field(default_factory=list)


# Proven prompt templates for common task types
PROMPT_TEMPLATES = [
    PromptTemplate(
        name="bug_fix_template",
        task_type="bug_fix",
        success_rate=0.85,
        complexity_level="moderate",
        template_text=dedent("""
            Fix the following bug: {bug_description}
            
            Context:
            - Affected files: {affected_files}
            - Error symptoms: {symptoms}
            - Expected behavior: {expected_behavior}
            
            Requirements:
            1. Identify the root cause of the issue
            2. Implement a minimal fix that addresses the root cause
            3. Add test cases to prevent regression
            4. Update documentation if behavior changes
            
            Please provide:
            - Analysis of the root cause
            - The fix implementation
            - Test cases added
            - Any documentation updates needed
        """).strip(),
        context_requirements=["affected_files", "symptoms", "expected_behavior"],
        typical_dependencies=["related_modules", "test_framework"],
    ),
    PromptTemplate(
        name="feature_addition_template",
        task_type="feature",
        success_rate=0.78,
        complexity_level="complex",
        template_text=dedent("""
            Implement the following feature: {feature_description}
            
            Requirements:
            {requirements_list}
            
            Architecture considerations:
            - Follow existing code patterns in {related_modules}
            - Maintain consistency with {architectural_style}
            - Ensure proper error handling and validation
            
            Deliverables:
            1. Feature implementation following project conventions
            2. Comprehensive unit tests (aim for >80% coverage)
            3. Integration tests if applicable
            4. Documentation updates (README, docstrings, etc.)
            5. Usage examples
            
            Dependencies: {dependencies}
        """).strip(),
        context_requirements=["feature_description", "requirements_list", "related_modules"],
        typical_dependencies=["architectural_style", "testing_framework"],
    ),
    PromptTemplate(
        name="refactoring_template",
        task_type="refactor",
        success_rate=0.82,
        complexity_level="moderate",
        template_text=dedent("""
            Refactor: {target_component}
            
            Goal: {refactoring_goal}
            
            Constraints:
            - Maintain backward compatibility: {backward_compat_required}
            - Keep existing tests passing
            - Follow project style guide: {style_guide_ref}
            
            Approach:
            1. Analyze current implementation and identify issues
            2. Design improved structure
            3. Implement changes incrementally
            4. Ensure all tests still pass
            5. Update documentation to reflect changes
            
            Focus areas:
            - Code clarity and maintainability
            - Performance improvements where applicable
            - Better error handling
            - Reduced code duplication
        """).strip(),
        context_requirements=["target_component", "refactoring_goal"],
        typical_dependencies=["existing_tests", "style_guide"],
    ),
    PromptTemplate(
        name="testing_template",
        task_type="testing",
        success_rate=0.90,
        complexity_level="simple",
        template_text=dedent("""
            Add comprehensive tests for: {component_name}
            
            Test coverage requirements:
            - Unit tests for all public methods/functions
            - Edge cases and error conditions
            - Integration tests for component interactions
            - Target coverage: >80%
            
            Component details:
            {component_description}
            
            Test strategy:
            1. Identify all testable units
            2. Write unit tests with clear assertions
            3. Add integration tests for workflows
            4. Include edge cases and error scenarios
            5. Use appropriate fixtures and mocks
            
            Follow testing conventions in: {test_examples}
        """).strip(),
        context_requirements=["component_name", "component_description"],
        typical_dependencies=["test_framework", "test_examples"],
    ),
    PromptTemplate(
        name="documentation_template",
        task_type="documentation",
        success_rate=0.88,
        complexity_level="simple",
        template_text=dedent("""
            Document: {component_or_feature}
            
            Documentation scope:
            {documentation_scope}
            
            Requirements:
            1. Clear overview and purpose
            2. API reference with parameter descriptions
            3. Usage examples with code snippets
            4. Common pitfalls and troubleshooting
            5. Links to related documentation
            
            Format guidelines:
            - Use Markdown formatting
            - Include code examples with proper syntax highlighting
            - Add diagrams where helpful (mermaid, ASCII art, etc.)
            - Follow existing documentation style in {doc_style_ref}
            
            Target audience: {target_audience}
        """).strip(),
        context_requirements=["component_or_feature", "documentation_scope"],
        typical_dependencies=["doc_style_ref", "existing_docs"],
    ),
]


class PromptQualityScorer:
    """Score prompts based on quality criteria and historical feedback."""
    """Score prompts based on quality criteria and historical feedback."""
    
    def __init__(self, feedback_analyzer: Optional[FeedbackAnalyzer] = None):
        self.feedback_analyzer = feedback_analyzer or get_feedback_analyzer()
        
    def score_prompt(
        self,
        prompt_text: str,
        metadata: Optional[PromptMetadata] = None,
        repo_analysis: Optional[RepositoryAnalysis] = None,
    ) -> float:
        """
        Score a prompt from 0.0 to 1.0 based on quality criteria.
        
        Criteria:
        - Clarity and specificity (0-0.25)
        - Actionability and completeness (0-0.25)
        - Context richness (0-0.20)
        - Historical performance (0-0.30)
        """
        score = 0.0
        
        # Clarity and specificity (0-0.25)
        clarity_score = self._score_clarity(prompt_text)
        score += clarity_score * 0.25
        
        # Actionability (0-0.25)
        actionability_score = self._score_actionability(prompt_text)
        score += actionability_score * 0.25
        
        # Context richness (0-0.20)
        context_score = self._score_context(prompt_text, metadata)
        score += context_score * 0.20
        
        # Historical performance (0-0.30)
        if metadata and metadata.prompt_hash:
            historical_score = self._score_historical_performance(metadata.prompt_hash)
            score += historical_score * 0.30
        else:
            # Use template success rate if available
            if metadata and metadata.template_used:
                template_score = self._get_template_success_rate(metadata.template_used)
                score += template_score * 0.30
            else:
                # Default score for new prompts
                score += 0.15  # Neutral starting point
        
        return min(1.0, max(0.0, score))
    
    def _score_clarity(self, prompt_text: str) -> float:
        """Score clarity: specific language, clear goals, no ambiguity."""
        score = 0.5  # baseline
        
        # Check for specific action verbs
        action_verbs = ['implement', 'fix', 'refactor', 'add', 'update', 'create', 
                       'remove', 'modify', 'test', 'document', 'analyze']
        if any(verb in prompt_text.lower() for verb in action_verbs):
            score += 0.2
        
        # Check for clear structure (numbered lists, sections)
        if re.search(r'\d+\.', prompt_text):
            score += 0.1
        
        # Penalize vague language
        vague_terms = ['maybe', 'possibly', 'perhaps', 'might', 'could be']
        if any(term in prompt_text.lower() for term in vague_terms):
            score -= 0.2
        
        # Check length (too short or too long is bad)
        word_count = len(prompt_text.split())
        if 50 <= word_count <= 500:
            score += 0.2
        elif word_count < 20:
            score -= 0.3
        
        return min(1.0, max(0.0, score))
    
    def _score_actionability(self, prompt_text: str) -> float:
        """Score actionability: clear deliverables, success criteria."""
        score = 0.4  # baseline
        
        # Check for deliverables/requirements section
        if re.search(r'(deliverable|requirement|output|result|provide)', prompt_text.lower()):
            score += 0.3
        
        # Check for success criteria
        if re.search(r'(should|must|ensure|verify|test)', prompt_text.lower()):
            score += 0.2
        
        # Check for file/module references
        if re.search(r'\.py|\.js|\.md|`[a-zA-Z_][a-zA-Z0-9_]*`', prompt_text):
            score += 0.1
        
        return min(1.0, max(0.0, score))
    
    def _score_context(self, prompt_text: str, metadata: Optional[PromptMetadata]) -> float:
        """Score context richness: relevant background, constraints, examples."""
        score = 0.3  # baseline
        
        # Check for context sections
        if re.search(r'(context|background|constraint|example)', prompt_text.lower()):
            score += 0.3
        
        # Bonus if metadata includes source documents
        if metadata and metadata.source_documents:
            score += 0.2
        
        # Check for architectural references
        if re.search(r'(architecture|pattern|design|structure)', prompt_text.lower()):
            score += 0.2
        
        return min(1.0, max(0.0, score))
    
    def _score_historical_performance(self, prompt_hash: str) -> float:
        """Score based on historical performance of similar prompts."""
        # Get feedback insights
        insights = self.feedback_analyzer.analyze_feedback(min_responses=2)
        
        # Find similar prompts
        for perf in insights.prompt_performance:
            if perf.prompt_id and perf.prompt_id[:8] == prompt_hash[:8]:
                return perf.success_rate
        
        # No historical data
        return 0.5
    
    def _get_template_success_rate(self, template_name: str) -> float:
        """Get success rate for a specific template."""
        for template in PROMPT_TEMPLATES:
            if template.name == template_name:
                return template.success_rate
        return 0.5


class RepositoryAnalyzer:
    """Analyze repository structure and patterns to guide prompt generation."""
    
    def __init__(self):
        self._analysis_cache: Dict[str, RepositoryAnalysis] = {}
    
    def analyze_repository(
        self,
        repo_name: str,
        docs: List[DocumentSlice],
        repo_dirs: List[Path],
    ) -> RepositoryAnalysis:
        """
        Analyze repository to understand structure, patterns, and conventions.
        """
        # Check cache first
        if repo_name in self._analysis_cache:
            return self._analysis_cache[repo_name]
        
        # Count files and detect primary language
        file_count = 0
        language_counts: Dict[str, int] = defaultdict(int)
        
        for doc_dir in repo_dirs:
            if not doc_dir.exists():
                continue
            for path in doc_dir.rglob("*"):
                if path.is_file():
                    file_count += 1
                    suffix = path.suffix.lower()
                    if suffix in ['.py', '.js', '.ts', '.java', '.go', '.rs', '.cpp']:
                        language_counts[suffix] += 1
        
        primary_language = None
        if language_counts:
            primary_language = max(language_counts.items(), key=lambda x: x[1])[0].replace('.', '')
        
        # Analyze architecture style from docs
        architecture_style = self._detect_architecture_style(docs)
        
        # Extract code patterns
        code_patterns = self._extract_code_patterns(docs)
        
        # Extract conventions
        conventions = self._extract_conventions(docs)
        
        # Extract dependencies
        dependencies = self._extract_dependencies(docs, repo_dirs)
        
        analysis = RepositoryAnalysis(
            repo_name=repo_name,
            primary_language=primary_language,
            file_count=file_count,
            architecture_style=architecture_style,
            code_patterns=code_patterns,
            conventions=conventions,
            dependencies=dependencies,
            test_coverage_estimate=None,  # Could be enhanced later
        )
        
        self._analysis_cache[repo_name] = analysis
        return analysis
    
    def _detect_architecture_style(self, docs: List[DocumentSlice]) -> Optional[str]:
        """Detect architectural style from documentation."""
        all_content = " ".join(doc.content.lower() for doc in docs)
        
        patterns = {
            "microservices": ["microservice", "service mesh", "api gateway"],
            "monolithic": ["monolith", "single application"],
            "layered": ["layer", "tier", "presentation layer", "data layer"],
            "event-driven": ["event", "message queue", "pub/sub", "kafka"],
            "serverless": ["lambda", "serverless", "function as a service"],
        }
        
        for style, keywords in patterns.items():
            if any(keyword in all_content for keyword in keywords):
                return style
        
        return None
    
    def _extract_code_patterns(self, docs: List[DocumentSlice]) -> List[str]:
        """Extract common code patterns mentioned in documentation."""
        patterns = []
        all_content = " ".join(doc.content.lower() for doc in docs)
        
        pattern_keywords = {
            "singleton": ["singleton"],
            "factory": ["factory pattern", "factory method"],
            "observer": ["observer", "event listener"],
            "dependency injection": ["dependency injection", "di container"],
            "repository": ["repository pattern"],
            "mvc": ["model-view-controller", "mvc"],
            "async/await": ["async", "await", "asyncio"],
        }
        
        for pattern_name, keywords in pattern_keywords.items():
            if any(keyword in all_content for keyword in keywords):
                patterns.append(pattern_name)
        
        return patterns
    
    def _extract_conventions(self, docs: List[DocumentSlice]) -> Dict[str, str]:
        """Extract naming conventions and style guides from documentation."""
        conventions = {}
        
        for doc in docs:
            content_lower = doc.content.lower()
            
            # Look for style guide references
            if "pep 8" in content_lower or "pep8" in content_lower:
                conventions["style_guide"] = "PEP 8"
            elif "google style" in content_lower:
                conventions["style_guide"] = "Google Style"
            elif "airbnb" in content_lower:
                conventions["style_guide"] = "Airbnb Style"
            
            # Look for naming conventions
            if "snake_case" in content_lower:
                conventions["naming"] = "snake_case"
            elif "camelCase" in content_lower:
                conventions["naming"] = "camelCase"
            
            # Look for docstring format
            if "numpy" in content_lower and "docstring" in content_lower:
                conventions["docstring"] = "NumPy"
            elif "google" in content_lower and "docstring" in content_lower:
                conventions["docstring"] = "Google"
        
        return conventions
    
    def _extract_dependencies(self, docs: List[DocumentSlice], repo_dirs: List[Path]) -> List[str]:
        """Extract external dependencies from repository."""
        dependencies = set()
        
        # Check for requirements.txt or pyproject.toml
        for repo_dir in repo_dirs:
            if not repo_dir.exists():
                continue
            
            req_file = repo_dir.parent / "requirements.txt"
            if req_file.exists():
                try:
                    content = req_file.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # Extract package name (before ==, >=, etc.)
                            pkg = re.split(r'[=><\[]', line)[0].strip()
                            if pkg:
                                dependencies.add(pkg)
                except Exception:
                    pass
        
        return sorted(list(dependencies))


class MasterPromptOrchestrator:
    """Collects repository context and asks OpenAI for orchestration prompts."""

    def __init__(
        self,
        *,
        repo_configs: Optional[Sequence[RepoConfig]] = None,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        allowed_extensions: Iterable[str] = DEFAULT_ALLOWED_EXTENSIONS,
        max_docs: int = 20,
        max_chars: int = 4000,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        model: str = DEFAULT_MODEL,
        agent_selection_mode: Optional[str] = None,
        temperature: float = 0.35,
        max_output_tokens: int = 2000,
        logger: Optional[Callable[[str], None]] = None,
        client: Optional[Any] = None,
        cross_repo_todo_service: Optional[CrossRepoTodoIngestionService] = None,
        enable_quality_validation: bool = True,
        quality_threshold: float = 0.4,
        enable_adaptive_complexity: bool = True,
        enable_prompt_templates: bool = True,
        enable_human_review: bool = False,
    ) -> None:
        self._explicit_repo_configs = repo_configs is not None
        self.output_dir = Path(output_dir)
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self.max_docs = max_docs
        self.max_chars = max_chars
        self.max_file_size = max_file_size
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.logger = logger or (lambda msg: None)
        self.client = client
        self._credential_state: Optional[OpenAICredentialState] = None
        self._openai_credentials_validated = False
        if client is not None:
            self._credential_state = OpenAICredentialState(
                source="injected client",
                repo_dotenv_path=REPO_DOTENV_PATH,
                repo_dotenv_exists=REPO_DOTENV_PATH.exists(),
            )
        
        # Enhanced features
        self.enable_quality_validation = enable_quality_validation
        self.quality_threshold = quality_threshold
        self.enable_adaptive_complexity = enable_adaptive_complexity
        self.enable_prompt_templates = enable_prompt_templates
        self.enable_human_review = enable_human_review
        
        # Initialize analyzers and scorers
        self.feedback_analyzer = get_feedback_analyzer()
        self.quality_scorer = PromptQualityScorer(self.feedback_analyzer)
        self.repo_analyzer = RepositoryAnalyzer()
        
        # Track generated prompts for deduplication
        self._generated_prompt_hashes: Set[str] = set()
        self._prompt_metadata_log: List[PromptMetadata] = []

        self.cross_repo_todo_service: Optional[CrossRepoTodoIngestionService] = None
        if CROSS_REPO_TODO_ENABLED:
            self.cross_repo_todo_service = cross_repo_todo_service or get_cross_repo_todo_service(
                logger=self.logger
            )

        self._explicit_repo_configs = repo_configs is not None
        if repo_configs is not None:
            self.repo_configs = self._dedupe_repo_configs(list(repo_configs))
        else:
            self.repo_configs = self._discover_repo_configs()

        selection_mode = agent_selection_mode or AGENT_SELECTION_MODE
        self.agent_selection_policy = AdaptiveAgentSelectionPolicy(mode=selection_mode)

        # North Star coordination guard
        self._coordination_guard: Optional["CoordinationGuard"] = None
        if NORTH_STAR_ENABLED and COORDINATION_GUARD_ENABLED and _NORTH_STAR_AVAILABLE:
            try:
                self._coordination_guard = CoordinationGuard(
                    overlap_block_on_in_progress=COORDINATION_GUARD_BLOCK_OVERLAPS,
                )
            except Exception as exc:  # pragma: no cover
                self._log(f"CoordinationGuard init failed (continuing without it): {exc}")

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _discover_repo_configs(self) -> List[RepoConfig]:
        """Resolve repo configs via env, cross-repo snapshot, then legacy heuristics."""
        env_configs = self._configs_from_env()
        if env_configs:
            self._log(f"Using {len(env_configs)} repo config(s) from MASTER_AGENT_REPO_CONFIGS")
            return env_configs

        snapshot_configs = self._configs_from_cross_repo_snapshot()
        if snapshot_configs:
            self._log(
                f"Auto-discovered {len(snapshot_configs)} repo config(s) via cross-repo Todo snapshot"
            )
            return snapshot_configs

        legacy = self._legacy_repo_configs()
        if legacy:
            self._log(
                "Falling back to legacy repo detection (foreground/CWD/default)"
            )
        return legacy

    def _configs_from_env(self) -> List[RepoConfig]:
        configs: List[RepoConfig] = []
        if not MASTER_AGENT_REPO_CONFIGS:
            return configs

        for config_dict in MASTER_AGENT_REPO_CONFIGS:
            name = str(config_dict.get("name", "")).strip()
            role = str(config_dict.get("role", "")).strip() or None
            raw_dirs = config_dict.get("docs_dirs", []) or []
            docs_dirs = self._normalize_doc_dirs(raw_dirs)
            repo_root = config_dict.get("repo_root")
            if isinstance(repo_root, str) and repo_root.strip():
                repo_root = Path(repo_root).expanduser()
            elif not isinstance(repo_root, Path):
                repo_root = None
            if name and docs_dirs:
                configs.append(
                    RepoConfig(
                        name=name,
                        docs_dirs=docs_dirs,
                        role=role,
                        repo_root=repo_root,
                        config_source="env_config",
                    )
                )
        return self._dedupe_repo_configs(configs)

    def _configs_from_cross_repo_snapshot(self) -> List[RepoConfig]:
        service = self.cross_repo_todo_service
        if service is None:
            return []

        try:
            snapshot = service.get_snapshot()
        except Exception as exc:  # pragma: no cover - defensive logging only
            self._log(f"Cross-repo Todo snapshot unavailable: {exc}")
            return []

        configs: List[RepoConfig] = []
        for repo in snapshot.repos:
            repo_name = repo.repo_name.strip() or "default"
            docs_dirs = self._doc_dirs_from_todo_paths(repo.todo_paths)
            if docs_dirs:
                configs.append(
                    RepoConfig(
                        name=repo_name,
                        docs_dirs=docs_dirs,
                        repo_root=self._infer_repo_root_from_docs_dirs(docs_dirs),
                        config_source="cross_repo_snapshot",
                    )
                )
        return self._dedupe_repo_configs(configs)

    @staticmethod
    def _legacy_repo_configs() -> List[RepoConfig]:
        """Legacy single-repo heuristics (foreground window, cwd, fallback)."""
        roots: List[RepoConfig] = []
        foreground_roots = detect_repo_from_foreground_window()
        if foreground_roots:
            repo_name = _extract_repo_name_from_window_title(get_foreground_window_title() or "")
            if repo_name:
                roots.append(
                    RepoConfig(
                        name=repo_name,
                        docs_dirs=foreground_roots,
                        repo_root=MasterPromptOrchestrator._infer_repo_root_from_docs_dirs(foreground_roots),
                        config_source="legacy_foreground",
                    )
                )

        inferred_roots = _detect_repo_doc_roots()
        if inferred_roots:
            roots.append(
                RepoConfig(
                    name="default",
                    docs_dirs=inferred_roots,
                    repo_root=MasterPromptOrchestrator._infer_repo_root_from_docs_dirs(inferred_roots),
                    config_source="legacy_cwd",
                )
            )

        if not roots:
            roots.append(
                RepoConfig(
                    name="default",
                    docs_dirs=[DEFAULT_DOCS_ROOT, DEFAULT_OPEN_TASKS_ROOT],
                    repo_root=MasterPromptOrchestrator._infer_repo_root_from_docs_dirs(
                        [DEFAULT_DOCS_ROOT, DEFAULT_OPEN_TASKS_ROOT]
                    ),
                    config_source="legacy_default",
                )
            )

        return MasterPromptOrchestrator._dedupe_repo_configs(roots)

    def _doc_dirs_from_todo_paths(self, todo_paths: Sequence[str]) -> List[Path]:
        doc_dirs: List[Path] = []
        for raw_path in todo_paths:
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            doc_dir = self._infer_docs_dir_from_todo_path(path)
            doc_dirs.append(doc_dir)
            open_tasks_dir = doc_dir / "open_tasks"
            try:
                if open_tasks_dir.is_dir():
                    doc_dirs.append(open_tasks_dir)
            except OSError:
                continue
        return self._normalize_doc_dirs(doc_dirs)

    def _infer_docs_dir_from_todo_path(self, todo_path: Path) -> Path:
        resolved = _safe_resolve(todo_path)

        for ancestor in resolved.parents:
            if ancestor.name.lower() == "docs":
                return ancestor

        candidate = resolved.parent / "docs"
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            pass
        return resolved.parent

    @staticmethod
    def _normalize_doc_dirs(doc_dirs: Iterable[Path]) -> List[Path]:
        normalized: List[Path] = []
        seen: set[str] = set()
        for raw_dir in doc_dirs:
            path = Path(raw_dir).expanduser()
            key = str(path)
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(path)
        return normalized

    @staticmethod
    def _infer_repo_root_from_docs_dir(doc_dir: Path) -> Optional[Path]:
        path = Path(doc_dir).expanduser()
        if path.name == "open_tasks" and path.parent.name == "docs":
            return path.parent.parent
        if path.name == "docs":
            return path.parent
        return None

    @classmethod
    def _infer_repo_root_from_docs_dirs(cls, doc_dirs: Iterable[Path]) -> Optional[Path]:
        for doc_dir in doc_dirs:
            repo_root = cls._infer_repo_root_from_docs_dir(doc_dir)
            if repo_root is not None:
                return repo_root
        return None

    @staticmethod
    def _dedupe_repo_configs(configs: Iterable[RepoConfig]) -> List[RepoConfig]:
        unique: List[RepoConfig] = []
        seen: set[str] = set()
        for config in configs:
            docs_dirs = MasterPromptOrchestrator._normalize_doc_dirs(config.docs_dirs)
            if not docs_dirs:
                continue
            key_parts = sorted(_path_key(Path(d)) for d in docs_dirs)
            key = f"{config.name.strip().lower()}:{'|'.join(key_parts)}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(
                RepoConfig(
                    name=config.name,
                    docs_dirs=docs_dirs,
                    role=config.role,
                    repo_root=config.repo_root or MasterPromptOrchestrator._infer_repo_root_from_docs_dirs(docs_dirs),
                    config_source=config.config_source,
                )
            )
        return unique

    @staticmethod
    def _normalized_repo_name(repo_name: str) -> str:
        return repo_name.strip().lower()

    def _order_repo_configs(self, configs: Sequence[RepoConfig]) -> List[RepoConfig]:
        if not configs:
            return []

        dependency_order = list(REPO_DEPENDENCY_ORDER)
        north_star = self._load_north_star_context()
        if north_star is not None:
            dependency_order = list(north_star.dependency_order) or dependency_order

        order_map = {
            self._normalized_repo_name(repo_name): index
            for index, repo_name in enumerate(dependency_order)
        }
        indexed_configs = list(enumerate(configs))
        indexed_configs.sort(
            key=lambda item: (
                order_map.get(self._normalized_repo_name(item[1].name), len(order_map)),
                item[0],
            )
        )
        return [config for _, config in indexed_configs]

    def _load_north_star_context(self) -> Optional[NorthStarContext]:
        if not (NORTH_STAR_ENABLED and _NORTH_STAR_AVAILABLE):
            return None
        try:
            return get_north_star()
        except Exception as exc:  # pragma: no cover
            self._log(f"North Star context unavailable: {exc}")
            return None

    def _north_star_role_for_repo(
        self,
        north_star: Optional[NorthStarContext],
        repo_name: str,
    ) -> Optional[Any]:
        if north_star is None:
            return None

        exact_role = north_star.role_for_repo(repo_name)
        if exact_role is not None:
            return exact_role

        normalized_name = self._normalized_repo_name(repo_name)
        for role_name, role in north_star.repo_roles.items():
            if self._normalized_repo_name(role_name) == normalized_name:
                return role
        return None

    def _north_star_tasks_for_repo(
        self,
        north_star: Optional[NorthStarContext],
        repo_name: str,
        *,
        priorities: Optional[Set[str]] = None,
    ) -> List[Any]:
        if north_star is None:
            return []

        normalized_name = self._normalized_repo_name(repo_name)
        tasks = [
            task for task in north_star.active_tasks
            if self._normalized_repo_name(task.repo) == normalized_name and task.is_active
        ]
        if priorities is not None:
            tasks = [task for task in tasks if task.priority in priorities]
        return tasks

    def _build_repo_role_section(
        self,
        repo_config: RepoConfig,
        north_star: Optional[NorthStarContext],
    ) -> str:
        repo_role = self._north_star_role_for_repo(north_star, repo_config.name)
        role_label = repo_config.role or (repo_role.name if repo_role is not None else "")
        priority_tasks = self._north_star_tasks_for_repo(
            north_star,
            repo_config.name,
            priorities={"P0", "P1"},
        )

        role_lines: List[str] = []
        role_lines.append("\n\nRepo-specific North Star context:")
        role_lines.append(f"- Target repo: {repo_config.name}")
        if role_label:
            role_lines.append(f"- Role: {role_label}")

        if repo_role is not None:
            if repo_role.owns:
                role_lines.append(f"- Owns: {'; '.join(repo_role.owns[:4])}")
            if repo_role.must_not_do:
                role_lines.append(f"- Must not do: {'; '.join(repo_role.must_not_do[:4])}")
            if repo_role.depends_on:
                role_lines.append(f"- Depends on: {', '.join(repo_role.depends_on)}")
            if repo_role.depended_on_by:
                role_lines.append(f"- Downstream consumers: {', '.join(repo_role.depended_on_by)}")

        if priority_tasks:
            role_lines.append("- Current repo P0/P1 North Star tasks:")
            for task in priority_tasks[:6]:
                role_lines.append(
                    f"  - [{task.priority}][{task.status}] {task.task_id}: {task.title}"
                )
        else:
            role_lines.append("- Current repo P0/P1 North Star tasks: none active")

        role_lines.append(
            "- Prompting directive: generate tasks that respect this repo boundary, advance the listed P0/P1 work, and avoid assigning downstream work before upstream dependencies are ready."
        )
        return "\n".join(role_lines)

    def _repo_docs_cache_dir(self, repo_name: str) -> Path:
        return DOCS_CACHE_ROOT / repo_name

    def _repo_cache_has_documents(self, repo_name: str) -> bool:
        cache_root = self._repo_docs_cache_dir(repo_name)
        if not cache_root.is_dir():
            return False
        for path in cache_root.rglob("*"):
            if path.is_file() and self._is_allowed_file(path):
                return True
        return False

    def _expected_relative_dir(self, repo_config: RepoConfig, directory: Path) -> Optional[str]:
        repo_root = repo_config.repo_root
        if repo_root is None:
            return None
        try:
            relative = Path(directory).expanduser().relative_to(repo_root)
        except ValueError:
            return None
        return str(relative).replace("\\", "/")

    def _probe_path_available(self, path: Optional[Path]) -> bool:
        if path is None:
            return False
        if _is_wsl_unc_path(path):
            return probe_wsl_path(path, WSL_PATH_PROBE_TIMEOUT_SECONDS)
        try:
            return path.exists()
        except OSError:
            return False

    def _readable_document_content(self, path: Path) -> Optional[str]:
        if not path.is_file() or not self._is_allowed_file(path):
            return None
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size > self.max_file_size:
            return None
        content = self._read_text(path)
        if not content.strip():
            return None
        return content

    @staticmethod
    def _docs_source_kind(path: Path) -> str:
        return "file" if path.suffix else "directory"

    def _count_live_documents(self, directory: Path) -> int:
        content = self._readable_document_content(directory)
        if content is not None:
            return 1

        count = 0
        try:
            iterator = directory.rglob("*")
            for path in iterator:
                if self._readable_document_content(path) is not None:
                    count += 1
        except OSError:
            return 0
        return count

    def _build_docs_next_steps(
        self,
        repo_config: RepoConfig,
        directory: Path,
        status: str,
        cache_available: bool,
    ) -> List[str]:
        steps: List[str] = []
        source_kind = self._docs_source_kind(directory)
        if status == "external_docs_missing":
            steps.append(f"Create or restore the upstream docs {source_kind} at {directory}.")
            steps.append(
                "If the repo moved, update TRADING_SYSTEM_ROOT_WIN / MASTER_AGENT_REPO_CONFIGS to the correct repo root/docs path."
            )
        elif status == "repo_misconfiguration":
            steps.append(
                f"Fix the configured docs path for repo '{repo_config.name}' so it points at the real upstream docs directory."
            )
            steps.append("Update MASTER_AGENT_REPO_CONFIGS or the CLI --repos argument, then rerun the readiness check.")
        elif status == "upstream_unreachable":
            target = repo_config.repo_root or directory.parent
            steps.append(f"Restore access to the upstream WSL path at {target}.")
            steps.append("Verify the WSL distro/share is online, then rerun the readiness check.")
        elif status == "live_docs_empty":
            steps.append(f"Add at least one supported document under {directory} so live cache seeding has source content.")
        if cache_available:
            steps.append(f"Cached fallback remains available at {self._repo_docs_cache_dir(repo_config.name)}.")
        else:
            steps.append(f"No cache is available yet at {self._repo_docs_cache_dir(repo_config.name)}.")
        return steps

    def _assess_docs_source(self, repo_config: RepoConfig, directory: Path) -> DocsSourceStatus:
        cache_available = ENABLE_WSL_DOC_CACHE and self._repo_cache_has_documents(repo_config.name)
        repo_root = repo_config.repo_root or self._infer_repo_root_from_docs_dir(directory)
        expected_relative_dir = self._expected_relative_dir(repo_config, directory)
        directory_available = self._probe_path_available(directory)
        issue_kind: Optional[str] = None
        live_document_count = 0

        if directory_available:
            live_document_count = self._count_live_documents(directory)
            if live_document_count > 0:
                status = "live_ready"
                message = f"Live docs ready at {directory} ({live_document_count} readable file(s))."
            else:
                status = "live_docs_empty"
                issue_kind = "empty"
                message = (
                    f"Docs {self._docs_source_kind(directory)} exists but contains no readable source documents at {directory}."
                )
            next_steps = self._build_docs_next_steps(repo_config, directory, status, cache_available)
            return DocsSourceStatus(
                repo_name=repo_config.name,
                directory=directory,
                repo_root=repo_root,
                config_source=repo_config.config_source,
                status=status,
                issue_kind=issue_kind,
                cache_available=cache_available,
                live_document_count=live_document_count,
                expected_relative_dir=expected_relative_dir,
                message=message,
                next_steps=next_steps,
            )

        repo_root_available = self._probe_path_available(repo_root)
        parent = directory.parent if directory.parent != directory else None
        parent_available = self._probe_path_available(parent)
        source_kind = self._docs_source_kind(directory)

        if repo_root is not None and repo_root_available:
            status = "external_docs_missing"
            issue_kind = "missing"
            message = (
                f"Configured repo root is reachable at {repo_root}, but the expected docs {source_kind} is missing at {directory}."
            )
        elif repo_root is None and repo_config.config_source in {"env_config", "cli"}:
            status = "repo_misconfiguration"
            issue_kind = "missing"
            message = (
                f"Configured docs path is missing and no repo_root was supplied for repo '{repo_config.name}'."
            )
        elif repo_root is not None and not repo_root_available:
            status = "upstream_unreachable"
            issue_kind = "unreachable"
            message = f"Configured repo root is not reachable at {repo_root}."
        elif parent_available:
            status = "external_docs_missing"
            issue_kind = "missing"
            message = f"Parent path is reachable, but the docs {source_kind} is missing at {directory}."
        else:
            status = "upstream_unreachable"
            issue_kind = "unreachable"
            message = f"Configured docs path is not reachable at {directory}."

        next_steps = self._build_docs_next_steps(repo_config, directory, status, cache_available)
        return DocsSourceStatus(
            repo_name=repo_config.name,
            directory=directory,
            repo_root=repo_root,
            config_source=repo_config.config_source,
            status=status,
            issue_kind=issue_kind,
            cache_available=cache_available,
            live_document_count=0,
            expected_relative_dir=expected_relative_dir,
            message=message,
            next_steps=next_steps,
        )

    def build_repo_readiness_report(self, repo_config: RepoConfig) -> RepoReadinessReport:
        docs_sources = [self._assess_docs_source(repo_config, directory) for directory in repo_config.docs_dirs]
        live_ready = any(source.live_ready for source in docs_sources)
        cache_dir = self._repo_docs_cache_dir(repo_config.name)
        cache_available = any(source.cache_available for source in docs_sources)
        seeding_ready = live_ready
        failing_sources = [source for source in docs_sources if not source.live_ready]
        if live_ready:
            status = "live_ready"
        elif failing_sources:
            status = failing_sources[0].status
        else:
            status = "no_docs_configured"

        next_steps: List[str] = []
        seen_steps: set[str] = set()
        for source in docs_sources:
            for step in source.next_steps:
                if step not in seen_steps:
                    seen_steps.add(step)
                    next_steps.append(step)

        return RepoReadinessReport(
            repo_name=repo_config.name,
            config_source=repo_config.config_source,
            repo_root=repo_config.repo_root,
            docs_sources=docs_sources,
            cache_dir=cache_dir,
            cache_available=cache_available,
            live_ready=live_ready,
            seeding_ready=seeding_ready,
            status=status,
            next_steps=next_steps,
        )

    def build_readiness_report(self) -> List[RepoReadinessReport]:
        return [self.build_repo_readiness_report(repo_config) for repo_config in self.repo_configs]

    def _log_docs_source_issue(
        self,
        repo_name: str,
        directory: Path,
        *,
        issue_status: DocsSourceStatus,
    ) -> None:
        cache_root = self._repo_docs_cache_dir(repo_name)
        if issue_status.cache_available:
            cache_state = f"using cached docs from {cache_root}"
        else:
            cache_state = f"no cached docs available at {cache_root}"
        manual_action = " ".join(issue_status.next_steps)
        repo_root_fragment = f" Repo root: {issue_status.repo_root}." if issue_status.repo_root else ""
        expected_fragment = (
            f" Expected relative path: {issue_status.expected_relative_dir}."
            if issue_status.expected_relative_dir
            else ""
        )

        self._log(
            f"WARNING: [ORCHESTRATOR] Repo '{repo_name}' docs source {issue_status.status}. "
            f"Path: {directory}.{repo_root_fragment}{expected_fragment} "
            f"Cache fallback: {cache_state}. Detail: {issue_status.message} Manual action: {manual_action}"
        )

    def _cache_relative_path(self, source_dir: Path, source_file: Path) -> Path:
        if source_dir == source_file:
            return Path(source_file.name)
        try:
            return source_file.relative_to(source_dir)
        except ValueError:
            return Path(source_file.name)

    def _write_doc_snapshot(self, repo_name: str, source_dir: Path, source_file: Path, content: str) -> None:
        if not ENABLE_WSL_DOC_CACHE:
            return
        cache_root = self._repo_docs_cache_dir(repo_name)
        relative_path = self._cache_relative_path(source_dir, source_file)
        cache_path = cache_root / relative_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(content, encoding="utf-8")

    def _load_documents_from_cache(self, repo_name: str) -> List[DocumentSlice]:
        cache_root = self._repo_docs_cache_dir(repo_name)
        if not cache_root.is_dir():
            self._log(
                f"ERROR: [ORCHESTRATOR] No cached docs found for repo '{repo_name}' at {cache_root}"
            )
            return []

        candidates: List[DocumentSlice] = []
        for path in cache_root.rglob("*"):
            if not path.is_file() or not self._is_allowed_file(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self.max_file_size:
                continue
            content = self._read_text(path)
            if not content.strip():
                continue
            truncated = content.strip()[: self.max_chars]
            candidates.append(
                DocumentSlice(
                    path=path,
                    content=truncated,
                    characters=len(truncated),
                    modified_epoch=path.stat().st_mtime,
                    repo_name=repo_name,
                )
            )
        if not candidates:
            self._log(
                f"ERROR: [ORCHESTRATOR] No cached docs found for repo '{repo_name}' at {cache_root}"
            )
        return candidates

    def _collect_documents_from_directory(self, repo_name: str, directory: Path) -> List[DocumentSlice]:
        candidates: List[DocumentSlice] = []
        content = self._readable_document_content(directory)
        if content is not None:
            truncated = content.strip()[: self.max_chars]
            candidates.append(
                DocumentSlice(
                    path=directory,
                    content=truncated,
                    characters=len(truncated),
                    modified_epoch=directory.stat().st_mtime,
                    repo_name=repo_name,
                )
            )
            if _is_wsl_unc_path(directory):
                self._write_doc_snapshot(repo_name, directory, directory, content)
            return candidates

        try:
            iterator = directory.rglob("*")
            for path in iterator:
                content = self._readable_document_content(path)
                if content is None:
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = None
                    if size is not None and size > self.max_file_size:
                        self._log(f"Skipping {path} (>{self.max_file_size} bytes)")
                    continue
                truncated = content.strip()[: self.max_chars]
                candidates.append(
                    DocumentSlice(
                        path=path,
                        content=truncated,
                        characters=len(truncated),
                        modified_epoch=path.stat().st_mtime,
                        repo_name=repo_name,
                    )
                )
                if _is_wsl_unc_path(directory):
                    self._write_doc_snapshot(repo_name, directory, path, content)
        except OSError as exc:
            self._log(f"Docs directory read failed: {directory} ({exc})")
            return []
        return candidates

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def refresh_all_feeds(self, *, dry_run: bool = False, force_discovery: bool = True) -> List[Optional[PromptBatchResult]]:
        """
        Perform a full audit (discovery -> analysis -> generation) and update prompt feeds.
        
        This is the primary entry point for library-based automation. It re-discovers
        repository configurations and generates fresh prompt batches for each.
        
        Args:
            dry_run: If True, collect documents but do not call OpenAI or write files.
            force_discovery: If True (default), re-scan for repositories even if configs 
                           were provided at initialization.
            
        Returns:
            List of results for each repository processed.
        """
        self._log("Refreshing all prompt feeds (full audit)...")
        
        # 1. Discovery: Re-scan for repositories to ensure we have the latest state
        if force_discovery or not self._explicit_repo_configs:
            self.repo_configs = self._discover_repo_configs()
            self._log(f"Discovered {len(self.repo_configs)} repositories.")
        else:
            self._log(f"Using {len(self.repo_configs)} explicitly configured repositories.")

        self.repo_configs = self._order_repo_configs(self.repo_configs)
        if self.repo_configs:
            self._log(
                "Repository processing order: "
                + ", ".join(repo.name for repo in self.repo_configs)
            )
        
        # 2 & 3. Analysis & Generation: Handled by generate_prompt_batches
        results = self.generate_prompt_batches(dry_run=dry_run)
        
        self._log("Prompt feed refresh complete.")
        return results

    def generate_prompt_batches(self, *, dry_run: bool = False) -> List[Optional[PromptBatchResult]]:
        """Generate prompt batches for all configured repos."""
        if not dry_run and not self._openai_credentials_validated:
            self.validate_openai_credentials()
        self.repo_configs = self._order_repo_configs(self.repo_configs)
        results = []
        for repo_config in self.repo_configs:
            result = self.generate_prompt_batch_for_repo(repo_config, dry_run=dry_run)
            results.append(result)
        return results

    def refresh_repo_configs(self, *, force: bool = False) -> List[RepoConfig]:
        """Refresh repo configs when auto-discovery is in use."""
        if self._explicit_repo_configs and not force:
            return list(self.repo_configs)

        if self.cross_repo_todo_service is not None:
            try:
                self.cross_repo_todo_service.refresh()
            except Exception as exc:  # pragma: no cover - defensive logging only
                self._log(f"Cross-repo Todo refresh failed: {exc}")

        refreshed = self._discover_repo_configs()
        if refreshed:
            self.repo_configs = refreshed
        return list(self.repo_configs)

    def generate_prompt_batch_for_repo(self, repo_config: RepoConfig, *, dry_run: bool = False) -> Optional[PromptBatchResult]:
        """Generate prompt batch for a specific repo with enhanced quality control."""
        if not dry_run and not self._openai_credentials_validated:
            self.validate_openai_credentials()

        docs = self.collect_documents(repo_config)
        if not docs:
            self._log(f"No documents found for repo '{repo_config.name}'.")
            return None

        # Perform repository analysis
        repo_analysis = self.repo_analyzer.analyze_repository(
            repo_config.name, docs, repo_config.docs_dirs
        )
        self._log(f"Repository analysis for '{repo_config.name}': {repo_analysis.primary_language}, "
                 f"{repo_analysis.file_count} files, architecture: {repo_analysis.architecture_style}")

        if dry_run:
            self._log(f"[DRY RUN] Collected {len(docs)} documents for repo '{repo_config.name}'; skipping OpenAI call.")
            return PromptBatchResult(
                output_path=self.output_dir / repo_config.name / "dry_run.txt",
                prompt_count=0,
                raw_text="",
                documents=docs,
                repo_name=repo_config.name,
            )

        # Get cross-repo todo items for dependency analysis
        todo_dependencies = self._extract_todo_dependencies(repo_config.name)

        # Request prompts from LLM with enhanced context
        response_text = self._request_prompts_with_context(
            docs,
            repo_analysis,
            todo_dependencies,
            repo_config,
        )
        if not response_text:
            self._log(f"OpenAI response was empty for repo '{repo_config.name}'; skipping file write.")
            return None

        # Split and parse prompts
        prompts = self._split_prompts(response_text)
        
        # Apply feedback-based filtering
        prompts = self._filter_prompts_with_feedback(prompts)
        
        # Generate metadata for each prompt
        prompts_with_metadata = self._generate_prompt_metadata(
            prompts, repo_config.name, docs, repo_analysis, todo_dependencies
        )
        
        # Validate prompt quality and filter low-quality prompts
        if self.enable_quality_validation:
            prompts_with_metadata = self._validate_and_filter_prompts(
                prompts_with_metadata, repo_analysis
            )
        
        # Apply adaptive complexity adjustments
        if self.enable_adaptive_complexity:
            prompts_with_metadata = self._adjust_prompt_complexity(prompts_with_metadata)
        
        # Deduplicate prompts
        prompts_with_metadata = self._deduplicate_prompts(prompts_with_metadata)
        
        # Apply diversity mechanisms
        prompts_with_metadata = self._ensure_prompt_diversity(prompts_with_metadata)
        
        # Human review if enabled
        if self.enable_human_review:
            prompts_with_metadata = self._request_human_review(prompts_with_metadata)
        
        # Extract final prompts
        final_prompts = [p for p, _ in prompts_with_metadata]
        
        # Annotate with agent selection
        final_prompts = self.agent_selection_policy.annotate_prompts(final_prompts)

        # Apply coordination guard: log overlap/drift warnings per prompt, and
        # optionally block prompts that would duplicate in-flight cross-repo work.
        if self._coordination_guard is not None:
            guarded_prompts: List[str] = []
            for prompt in final_prompts:
                try:
                    decision = self._coordination_guard.evaluate(
                        prompt, target_repo=repo_config.name
                    )
                    if decision.should_block:
                        self._log(
                            f"[COORDINATION GUARD] Blocked prompt for '{repo_config.name}': "
                            f"{decision.block_reason}"
                        )
                        continue  # drop this prompt
                    if decision.cautions:
                        for c in decision.cautions:
                            self._log(f"[COORDINATION GUARD] Caution ({repo_config.name}): {c}")
                    # Prepend the North Star context block to the prompt
                    if decision.context_prefix:
                        prompt = decision.context_prefix + "\n\n---\n\n" + prompt
                    guarded_prompts.append(prompt)
                except Exception as exc:  # pragma: no cover
                    self._log(f"[COORDINATION GUARD] Error evaluating prompt: {exc}")
                    guarded_prompts.append(prompt)
            final_prompts = guarded_prompts
        
        # Write prompt file with metadata
        output_path, metadata_file = self._write_prompt_file_with_metadata(
            repo_config, docs, final_prompts, response_text, prompts_with_metadata
        )
        
        return PromptBatchResult(
            output_path=output_path,
            prompt_count=len(final_prompts),
            raw_text=response_text,
            documents=docs,
            repo_name=repo_config.name,
            metadata_file=metadata_file,
            prompts_with_metadata=prompts_with_metadata,
        )

    # Backward compatibility method
    def generate_prompt_batch(self, *, dry_run: bool = False) -> Optional[PromptBatchResult]:
        """Generate prompt batch for the first configured repo (backward compatibility)."""
        if not self.repo_configs:
            return None
        return self.generate_prompt_batch_for_repo(self.repo_configs[0], dry_run=dry_run)

    def collect_documents(self, repo_config: RepoConfig) -> List[DocumentSlice]:
        """Gather most-relevant text files from the configured directories for a specific repo."""
        candidates: List[DocumentSlice] = []
        cache_loaded = False
        for directory in repo_config.docs_dirs:
            source_status = self._assess_docs_source(repo_config, directory)
            if not source_status.live_ready:
                self._log_docs_source_issue(
                    repo_config.name,
                    directory,
                    issue_status=source_status,
                )
                if source_status.cache_available and not cache_loaded:
                    candidates.extend(self._load_documents_from_cache(repo_config.name))
                    cache_loaded = True
                continue
            directory_candidates = self._collect_documents_from_directory(repo_config.name, directory)
            if not directory_candidates and _is_wsl_unc_path(directory) and ENABLE_WSL_DOC_CACHE and not cache_loaded:
                self._log(
                    f"WARNING: [ORCHESTRATOR] Repo '{repo_config.name}' returned no live docs from {directory}. "
                    f"Cache fallback: using cached docs from {self._repo_docs_cache_dir(repo_config.name)}."
                )
                candidates.extend(self._load_documents_from_cache(repo_config.name))
                cache_loaded = True
                continue
            candidates.extend(directory_candidates)

        if self.cross_repo_todo_service is not None:
            try:
                summary = self.cross_repo_todo_service.render_summary_markdown(
                    max_items_per_repo=25
                ).strip()
            except Exception as exc:
                self._log(f"Cross-repo Todo summary unavailable: {exc}")
                summary = ""

            if summary:
                truncated_summary = summary[: self.max_chars]
                candidates.append(
                    DocumentSlice(
                        path=Path("cross_repo_todos_summary.md"),
                        content=truncated_summary,
                        characters=len(truncated_summary),
                        modified_epoch=datetime.now(timezone.utc).timestamp(),
                        repo_name="cross-repo",
                    )
                )

        # Sort by recent modification time and keep the top N
        candidates.sort(key=lambda d: d.modified_epoch, reverse=True)
        return candidates[: self.max_docs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    
    def _extract_todo_dependencies(self, repo_name: str) -> List[TodoItem]:
        """Extract todo items from cross-repo service to identify dependencies."""
        if not self.cross_repo_todo_service:
            return []
        
        try:
            snapshot = self.cross_repo_todo_service.get_snapshot()
            for repo in snapshot.repos:
                if repo.repo_name == repo_name:
                    return list(repo.items)
        except Exception as e:
            self._log(f"Failed to extract todo dependencies: {e}")
        
        return []

    def _build_dependency_graph_section(self, repo_name: str) -> str:
        """Render a compact cross-repo dependency graph view for a repo.

        This leverages the cross-repo Todo dependency analysis to show:
        - an approximate critical path across repos, and
        - suggested execution order for tasks touching this repo.
        """

        if not self.cross_repo_todo_service:
            return ""

        try:
            analysis: CrossRepoDependencyAnalysis = self.cross_repo_todo_service.analyze_dependencies()
        except Exception as exc:  # pragma: no cover - defensive logging
            self._log(f"Cross-repo dependency analysis unavailable: {exc}")
            return ""

        tasks_for_repo = analysis.tasks_for_repo(repo_name)
        if not tasks_for_repo:
            return ""

        lines: List[str] = []
        lines.append("## Cross-Repo Dependency Graph (summary)")

        critical_path = analysis.iter_critical_path()
        if critical_path:
            path_str = " -> ".join(f"{t.repo_name}:{t.title}" for t in critical_path)
            lines.append("")
            lines.append("**Critical path across repos:**")
            lines.append(f"- {path_str}")

        # Suggested execution order for tasks in this repo, respecting cross-repo deps.
        ordered_for_repo = [t for t in analysis.iter_ordered() if t.repo_name == repo_name]
        if ordered_for_repo:
            lines.append("")
            lines.append(f"**Suggested execution order for {repo_name}:**")
            for task in ordered_for_repo[:10]:
                prio = f"[{task.priority}] " if task.priority else ""
                status_note = " (BLOCKED)" if task.is_blocked or analysis.dependencies.get(task.key) else ""
                lines.append(f"- {prio}{task.repo_name}:{task.title}{status_note}")

        # Highlight any cycles that touch this repo.
        cycles_for_repo: List[str] = []
        for cycle in analysis.cycles:
            labels = [
                f"{analysis.tasks[k].repo_name}:{analysis.tasks[k].title}"
                for k in cycle
                if k in analysis.tasks
            ]
            if not labels:
                continue
            if not any(label.startswith(f"{repo_name}:") for label in labels):
                continue
            cycles_for_repo.append(" -> ".join(labels))

        if cycles_for_repo:
            lines.append("")
            lines.append("**Detected circular dependencies touching this repo:**")
            for desc in cycles_for_repo[:5]:
                lines.append(f"- {desc}")

        return "\n".join(lines).strip()
    
    def _request_prompts_with_context(
        self,
        docs: List[DocumentSlice],
        repo_analysis: RepositoryAnalysis,
        todo_dependencies: List[TodoItem],
        repo_config: RepoConfig,
    ) -> str:
        """Request prompts from LLM with enhanced context including repo analysis."""
        compiled_docs = self._format_documents(docs)
        
        # Build enhanced user prompt with repo context
        user_prompt = self._build_enhanced_user_prompt(
            compiled_docs, repo_analysis, todo_dependencies
        )
        
        # Get feedback insights to include in system prompt
        feedback_insights = self.feedback_analyzer.analyze_feedback(min_responses=3)
        enhanced_system_prompt = self._build_system_prompt(
            feedback_insights,
            repo_analysis,
            repo_config,
        )
        
        self._log(
            f"Requesting prompts from {self.model} using {len(docs)} documents "
            f"({sum(d.characters for d in docs)} chars) with repo analysis."
        )

        response = self._responses_create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": enhanced_system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        usage = getattr(response, "usage", None)
        _COST_TRACKER.record_text_usage(
            source="master_prompt_orchestrator",
            event="prompt_generation",
            model=self.model,
            usage=usage,
            details={
                "document_count": len(docs),
                "characters": sum(doc.characters for doc in docs),
                "repo_name": repo_analysis.repo_name,
            },
        )
        return self._merge_text_outputs(response)
    
    def _build_system_prompt(
        self,
        feedback_insights: FeedbackInsights,
        repo_analysis: RepositoryAnalysis,
        repo_config: RepoConfig,
    ) -> str:
        """Build system prompt enhanced with feedback insights and repo North Star context."""
        base_prompt = SYSTEM_PROMPT
        north_star = self._load_north_star_context()

        # Prepend North Star context so the LLM understands the top-level goal and
        # in-flight work across all repos before it generates any task prompts.
        north_star_section = ""
        if north_star is not None:
            north_star_section = (
                "\n\n## COORDINATION CONTEXT — READ BEFORE ASSIGNING TASKS\n\n"
                + north_star.prompt_header()
                + "\n"
                + self._build_repo_role_section(repo_config, north_star)
                + "\n"
            )

        base_prompt = north_star_section + base_prompt
        
        # Add feedback insights
        feedback_section = ""
        if feedback_insights.successful_patterns:
            feedback_section += "\n\nSuccessful prompt patterns (use these as guidance):\n"
            for pattern in feedback_insights.successful_patterns[:5]:
                feedback_section += f"- {pattern}\n"
        
        if feedback_insights.problematic_patterns:
            feedback_section += "\n\nPatterns to avoid (these have led to errors):\n"
            for pattern in feedback_insights.problematic_patterns[:5]:
                feedback_section += f"- {pattern}\n"
        
        # Add repository context
        repo_section = "\n\nRepository context for prompt generation:"
        repo_section += f"\n- Repository: {repo_analysis.repo_name}"
        repo_section += f"\n- Primary language: {repo_analysis.primary_language or 'unknown'}"
        repo_section += f"\n- Architecture: {repo_analysis.architecture_style or 'unknown'}"
        
        if repo_analysis.code_patterns:
            repo_section += f"\n- Common patterns: {', '.join(repo_analysis.code_patterns[:5])}"
        
        if repo_analysis.conventions:
            repo_section += "\n- Code conventions:"
            for key, value in repo_analysis.conventions.items():
                repo_section += f"\n  - {key}: {value}"
        
        # Add template guidance if enabled
        template_section = ""
        if self.enable_prompt_templates:
            template_section = "\n\nAvailable prompt templates (use these for common task types):\n"
            for template in PROMPT_TEMPLATES:
                template_section += f"- {template.name} ({template.task_type}): {template.success_rate:.0%} success rate\n"
            template_section += "\nWhen generating prompts, structure them according to proven templates for better results."
        
        return base_prompt + feedback_section + repo_section + template_section

    def _build_enhanced_system_prompt(
        self,
        feedback_insights: FeedbackInsights,
        repo_analysis: RepositoryAnalysis,
        repo_config: Optional[RepoConfig] = None,
    ) -> str:
        effective_repo_config = repo_config or RepoConfig(name=repo_analysis.repo_name, docs_dirs=[])
        return self._build_system_prompt(feedback_insights, repo_analysis, effective_repo_config)
    
    def _build_enhanced_user_prompt(
        self,
        compiled_docs: str,
        repo_analysis: RepositoryAnalysis,
        todo_dependencies: List[TodoItem],
    ) -> str:
        """Build user prompt with dependency information and architectural context."""
        base_prompt = dedent(
            f"""\
            Review the following repository documents and outstanding tasks. Use them to craft the
            required prompt batch described earlier. Always include citations to the doc names when
            clarifying context.

            Repository: {repo_analysis.repo_name}
            Primary Language: {repo_analysis.primary_language or 'unknown'}
            Architecture: {repo_analysis.architecture_style or 'generic'}
            
            Repository context:
            {compiled_docs}
            """
        ).strip()
        
        # Add dependency information
        if todo_dependencies:
            blocked_items = [item for item in todo_dependencies if item.is_blocked]
            unblocked_items = [item for item in todo_dependencies if not item.is_blocked]
            
            dep_section = "\n\n## Task Dependencies\n"
            if unblocked_items:
                dep_section += f"\n**Ready to work on ({len(unblocked_items)} unblocked tasks):**\n"
                for item in unblocked_items[:10]:
                    priority = f"[{item.priority}] " if item.priority else ""
                    dep_section += f"- {priority}{item.title}\n"
            
            if blocked_items:
                dep_section += f"\n**Blocked tasks ({len(blocked_items)}) - DO NOT generate prompts for these:**\n"
                for item in blocked_items[:5]:
                    priority = f"[{item.priority}] " if item.priority else ""
                    blockers = f" (blocked by: {', '.join(item.blocked_by[:3])})" if item.blocked_by else ""
                    dep_section += f"- {priority}{item.title}{blockers}\n"
            
            base_prompt += dep_section

            # Add a compact visualisation of cross-repo dependency structure.
            graph_section = self._build_dependency_graph_section(repo_analysis.repo_name)
            if graph_section:
                base_prompt += "\n\n" + graph_section
        
        # Add guidance on task prioritization
        base_prompt += dedent("""
            
            ## Task Selection Guidance
            - Prioritize unblocked, high-priority tasks
            - Consider dependencies between tasks
            - Generate prompts that align with the repository's architecture and patterns
            - Ensure tasks are properly scoped (not too large or too small)
            - Reference specific files and modules from the documentation
        """).strip()
        
        return base_prompt
    
    def _generate_prompt_metadata(
        self,
        prompts: List[str],
        repo_name: str,
        docs: List[DocumentSlice],
        repo_analysis: RepositoryAnalysis,
        todo_dependencies: List[TodoItem],
    ) -> List[Tuple[str, PromptMetadata]]:
        """Generate metadata for each prompt."""
        prompts_with_metadata = []
        
        for prompt_text in prompts:
            prompt_hash = self._compute_prompt_hash(prompt_text)
            prompt_id = self._compute_prompt_identifier(prompt_text)
            
            # Classify task type
            task_type = self._classify_task_type(prompt_text)
            
            # Determine difficulty
            difficulty = self._estimate_difficulty(prompt_text)
            
            # Extract dependencies from prompt
            dependencies = self._extract_prompt_dependencies(prompt_text, todo_dependencies)
            
            # Generate rationale
            rationale = self._generate_prompt_rationale(
                prompt_text, task_type, repo_analysis
            )
            
            # Determine template used (if any)
            template_used = self._identify_template_match(prompt_text)
            
            metadata = PromptMetadata(
                prompt_id=prompt_id,
                prompt_hash=prompt_hash,
                generated_at=datetime.now(timezone.utc).isoformat(),
                repo_name=repo_name,
                source_documents=[self._pretty_path(doc.path) for doc in docs],
                rationale=rationale,
                expected_difficulty=difficulty,
                dependencies=dependencies,
                task_type=task_type,
                quality_score=0.0,  # Will be set during validation
                template_used=template_used,
            )
            
            prompts_with_metadata.append((prompt_text, metadata))
        
        return prompts_with_metadata
    
    def _classify_task_type(self, prompt_text: str) -> str:
        """Classify the task type based on prompt content."""
        lower_text = prompt_text.lower()
        
        if any(word in lower_text for word in ['fix', 'bug', 'error', 'issue', 'broken']):
            return "bug_fix"
        elif any(word in lower_text for word in ['implement', 'add feature', 'new feature', 'enhance']):
            return "feature"
        elif any(word in lower_text for word in ['refactor', 'restructure', 'reorganize', 'clean up']):
            return "refactor"
        elif any(word in lower_text for word in ['test', 'coverage', 'unit test', 'integration test']):
            return "testing"
        elif any(word in lower_text for word in ['document', 'documentation', 'docstring', 'readme']):
            return "documentation"
        else:
            return "other"
    
    def _estimate_difficulty(self, prompt_text: str) -> str:
        """Estimate task difficulty based on prompt complexity."""
        word_count = len(prompt_text.split())
        
        # Count complexity indicators
        complexity_indicators = [
            'architecture', 'design', 'refactor', 'migrate', 'optimize',
            'performance', 'scalability', 'integration', 'complex'
        ]
        
        indicator_count = sum(
            1 for indicator in complexity_indicators
            if indicator in prompt_text.lower()
        )
        
        # Estimate based on length and complexity indicators
        if word_count < 100 and indicator_count == 0:
            return "simple"
        elif word_count > 300 or indicator_count >= 3:
            return "complex"
        else:
            return "moderate"
    
    def _extract_prompt_dependencies(
        self,
        prompt_text: str,
        todo_dependencies: List[TodoItem],
    ) -> List[str]:
        """Extract dependencies mentioned in the prompt."""
        dependencies = []
        
        # Look for explicit dependency mentions
        dep_patterns = [
            r'depends on ([^.]+)',
            r'requires ([^.]+)',
            r'blocked by ([^.]+)',
            r'needs ([^.]+) to be completed',
        ]
        
        for pattern in dep_patterns:
            matches = re.findall(pattern, prompt_text, re.IGNORECASE)
            dependencies.extend(matches)
        
        # Cross-reference with todo items
        for item in todo_dependencies:
            if item.is_blocked and item.title.lower() in prompt_text.lower():
                dependencies.extend(item.blocked_by)
        
        return list(set(dependencies))  # Deduplicate
    
    def _generate_prompt_rationale(
        self,
        prompt_text: str,
        task_type: str,
        repo_analysis: RepositoryAnalysis,
    ) -> str:
        """Generate a rationale explaining why this prompt was created."""
        rationale_parts = [f"Task type: {task_type}"]
        
        # Add context from repository analysis
        if repo_analysis.architecture_style:
            rationale_parts.append(
                f"Aligns with {repo_analysis.architecture_style} architecture"
            )
        
        # Extract first sentence or key phrase from prompt
        first_sentence = prompt_text.split('.')[0].strip()
        if first_sentence:
            rationale_parts.append(f"Objective: {first_sentence[:100]}")
        
        return "; ".join(rationale_parts)
    
    def _identify_template_match(self, prompt_text: str) -> Optional[str]:
        """Identify which template (if any) this prompt most closely matches."""
        if not self.enable_prompt_templates:
            return None
        
        task_type = self._classify_task_type(prompt_text)
        
        # Find matching template by task type
        for template in PROMPT_TEMPLATES:
            if template.task_type == task_type:
                return template.name
        
        return None
    
    def _validate_and_filter_prompts(
        self,
        prompts_with_metadata: List[Tuple[str, PromptMetadata]],
        repo_analysis: RepositoryAnalysis,
    ) -> List[Tuple[str, PromptMetadata]]:
        """Validate prompt quality and filter out low-quality prompts."""
        validated_prompts = []
        filtered_count = 0
        
        for prompt_text, metadata in prompts_with_metadata:
            # Score the prompt
            quality_score = self.quality_scorer.score_prompt(
                prompt_text, metadata, repo_analysis
            )
            
            # Update metadata with score
            metadata_dict = asdict(metadata)
            metadata_dict['quality_score'] = quality_score
            updated_metadata = PromptMetadata(**metadata_dict)
            
            # Filter based on threshold
            if quality_score >= self.quality_threshold:
                validated_prompts.append((prompt_text, updated_metadata))
                self._log(f"Prompt validated with score {quality_score:.2f}: {prompt_text[:60]}...")
            else:
                filtered_count += 1
                self._log(f"Filtered low-quality prompt (score {quality_score:.2f}): {prompt_text[:60]}...")
        
        if filtered_count > 0:
            self._log(f"Filtered {filtered_count} low-quality prompts (threshold: {self.quality_threshold})")
        
        return validated_prompts
    
    def _adjust_prompt_complexity(
        self,
        prompts_with_metadata: List[Tuple[str, PromptMetadata]],
    ) -> List[Tuple[str, PromptMetadata]]:
        """Adjust prompt complexity based on recent agent success rates."""
        insights = self.feedback_analyzer.analyze_feedback(min_responses=5)
        
        if not insights.prompt_performance:
            self._log("No feedback data available for adaptive complexity adjustment")
            return prompts_with_metadata
        
        # Calculate overall success rate
        total_responses = sum(p.total_responses for p in insights.prompt_performance)
        total_successes = sum(p.successful_responses for p in insights.prompt_performance)
        overall_success_rate = total_successes / total_responses if total_responses > 0 else 0.5
        
        self._log(f"Overall agent success rate: {overall_success_rate:.1%}")
        
        # Determine complexity adjustment strategy
        if overall_success_rate < 0.5:
            # Agents struggling - simplify tasks
            adjustment = "simplify"
            self._log("Agents struggling - adjusting complexity down")
        elif overall_success_rate > 0.8:
            # Agents succeeding - can handle more complex tasks
            adjustment = "increase"
            self._log("Agents succeeding - maintaining/increasing complexity")
        else:
            # Balanced - no adjustment
            adjustment = "maintain"
        
        adjusted_prompts = []
        for prompt_text, metadata in prompts_with_metadata:
            if adjustment == "simplify" and metadata.expected_difficulty == "complex":
                # Add guidance to break down complex tasks
                adjusted_text = self._simplify_prompt(prompt_text)
                metadata_dict = asdict(metadata)
                metadata_dict['adaptive_complexity_level'] = "simplified"
                metadata_dict['expected_difficulty'] = "moderate"
                adjusted_metadata = PromptMetadata(**metadata_dict)
                adjusted_prompts.append((adjusted_text, adjusted_metadata))
                self._log(f"Simplified complex prompt: {prompt_text[:60]}...")
            else:
                metadata_dict = asdict(metadata)
                metadata_dict['adaptive_complexity_level'] = adjustment
                adjusted_metadata = PromptMetadata(**metadata_dict)
                adjusted_prompts.append((prompt_text, adjusted_metadata))
        
        return adjusted_prompts
    
    def _simplify_prompt(self, prompt_text: str) -> str:
        """Simplify a complex prompt by adding step-by-step guidance."""
        simplification_note = dedent("""
            
            **Note**: Break this task into smaller, manageable steps:
            1. Start with the core functionality
            2. Test thoroughly before moving to the next step
            3. Document your progress
            4. Ask for clarification if any requirements are unclear
        """).strip()
        
        return prompt_text + "\n\n" + simplification_note
    
    def _deduplicate_prompts(
        self,
        prompts_with_metadata: List[Tuple[str, PromptMetadata]],
    ) -> List[Tuple[str, PromptMetadata]]:
        """Remove duplicate or very similar prompts."""
        unique_prompts: List[Tuple[str, PromptMetadata]] = []
        seen_hashes: Set[str] = set()
        
        for prompt_text, metadata in prompts_with_metadata:
            prompt_hash = metadata.prompt_hash
            
            # Check for exact duplicates
            if prompt_hash in seen_hashes:
                self._log(f"Filtered duplicate prompt: {prompt_text[:60]}...")
                continue
            
            # Check for semantic similarity (simple word overlap for now)
            is_similar = self._is_similar_to_existing(prompt_text, unique_prompts)
            if is_similar:
                self._log(f"Filtered similar prompt: {prompt_text[:60]}...")
                continue
            
            seen_hashes.add(prompt_hash)
            unique_prompts.append((prompt_text, metadata))
        
        duplicate_count = len(prompts_with_metadata) - len(unique_prompts)
        if duplicate_count > 0:
            self._log(f"Removed {duplicate_count} duplicate/similar prompts")
        
        return unique_prompts
    
    def _is_similar_to_existing(
        self,
        prompt_text: str,
        existing_prompts: List[Tuple[str, PromptMetadata]],
        similarity_threshold: float = 0.7,
    ) -> bool:
        """Check if prompt is too similar to existing prompts."""
        prompt_words = set(prompt_text.lower().split())
        
        for existing_text, _ in existing_prompts:
            existing_words = set(existing_text.lower().split())
            
            # Calculate Jaccard similarity
            intersection = len(prompt_words & existing_words)
            union = len(prompt_words | existing_words)
            
            if union == 0:
                continue
            
            similarity = intersection / union
            if similarity >= similarity_threshold:
                return True
        
        return False
    
    def _ensure_prompt_diversity(
        self,
        prompts_with_metadata: List[Tuple[str, PromptMetadata]],
    ) -> List[Tuple[str, PromptMetadata]]:
        """Ensure diversity in task types and difficulty levels."""
        # Group by task type
        by_task_type: Dict[str, List[Tuple[str, PromptMetadata]]] = defaultdict(list)
        for prompt_text, metadata in prompts_with_metadata:
            by_task_type[metadata.task_type].append((prompt_text, metadata))
        
        # Limit per task type to ensure diversity
        max_per_type = max(3, len(prompts_with_metadata) // len(by_task_type)) if by_task_type else 3
        
        diverse_prompts = []
        for task_type, prompts in by_task_type.items():
            # Take highest quality prompts of each type
            sorted_prompts = sorted(prompts, key=lambda x: x[1].quality_score, reverse=True)
            diverse_prompts.extend(sorted_prompts[:max_per_type])
            
            if len(prompts) > max_per_type:
                self._log(f"Limited {task_type} tasks to {max_per_type} for diversity")
        
        # Sort by quality and return
        diverse_prompts.sort(key=lambda x: x[1].quality_score, reverse=True)
        return diverse_prompts
    
    def _request_human_review(
        self,
        prompts_with_metadata: List[Tuple[str, PromptMetadata]],
    ) -> List[Tuple[str, PromptMetadata]]:
        """Request human review of generated prompts (placeholder for UI integration)."""
        # This is a placeholder - in a real implementation, this would:
        # 1. Save prompts to a review queue
        # 2. Present them in a UI for approval
        # 3. Wait for human feedback
        # 4. Return approved prompts
        
        review_file = self.output_dir / "pending_review.json"
        review_file.parent.mkdir(parents=True, exist_ok=True)
        
        review_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompts": [
                {
                    "text": text,
                    "metadata": asdict(metadata),
                }
                for text, metadata in prompts_with_metadata
            ],
        }
        
        review_file.write_text(json.dumps(review_data, indent=2), encoding="utf-8")
        self._log(f"Saved {len(prompts_with_metadata)} prompts for human review: {review_file}")
        
        # For now, return all prompts (assuming auto-approval)
        # In production, this would wait for actual review
        return prompts_with_metadata
    
    def _compute_prompt_hash(self, prompt_text: str) -> str:
        """Compute a full hash of the prompt text."""
        if not prompt_text:
            return ""
        return hashlib.sha256(prompt_text.encode("utf-8", errors="ignore")).hexdigest()
    
    def _request_prompts(self, docs: List[DocumentSlice]) -> str:
        compiled_docs = self._format_documents(docs)
        user_prompt = self._build_user_prompt(compiled_docs)
        self._log(
            f"Requesting prompts from {self.model} using {len(docs)} documents "
            f"({sum(d.characters for d in docs)} chars)."
        )

        response = self._responses_create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        usage = getattr(response, "usage", None)
        _COST_TRACKER.record_text_usage(
            source="master_prompt_orchestrator",
            event="prompt_generation",
            model=self.model,
            usage=usage,
            details={
                "document_count": len(docs),
                "characters": sum(doc.characters for doc in docs),
            },
        )
        return self._merge_text_outputs(response)

    def _build_user_prompt(self, compiled_docs: str) -> str:
        return dedent(
            f"""\
            Review the following repository documents and outstanding tasks. Use them to craft the
            required prompt batch described earlier. Always include citations to the doc names when
            clarifying context.

            Repository context:
            {compiled_docs}
            """
        ).strip()

    def _format_documents(self, docs: List[DocumentSlice]) -> str:
        formatted_chunks = []
        for doc in docs:
            rel_path = self._pretty_path(doc.path)
            timestamp = datetime.fromtimestamp(doc.modified_epoch).strftime("%Y-%m-%d %H:%M")
            formatted_chunks.append(
                f"[{timestamp}] {rel_path}\n{doc.content}\n--"
            )
        return "\n\n".join(formatted_chunks)

    @staticmethod
    def _split_prompts(response_text: str) -> List[str]:
        prompts: List[str] = []
        current: List[str] = []
        numbered_heading = re.compile(r"^\s*\d+\.\s*")
        for line in response_text.splitlines():
            stripped = line.strip()
            if numbered_heading.match(stripped):
                if current:
                    prompts.append("\n".join(current).strip())
                current = [stripped]
                continue
            if stripped.lower().startswith("prompt") and "(" in stripped:
                if current:
                    prompts.append("\n".join(current).strip())
                current = [stripped]
                continue
            current.append(line)
        if current:
            prompts.append("\n".join(current).strip())
        return [p for p in prompts if p]

    def _filter_prompts_with_feedback(self, prompts: List[str]) -> List[str]:
        """Filter out prompts that have poor performance based on feedback data."""
        if not prompts:
            return prompts
            
        analyzer = get_feedback_analyzer()
        guidance = analyzer.get_guidance()
        filtered_prompts = []
        
        for prompt in prompts:
            # Generate prompt ID (same as panel tracker)
            prompt_id = self._compute_prompt_identifier(prompt)
            
            # Check if this prompt should be filtered
            should_filter, reason = analyzer.should_filter_prompt(prompt, prompt_id)
            
            if should_filter:
                self._log(f"Filtering out prompt due to feedback: {reason}")
                self._log(f"Filtered prompt preview: {prompt[:100]}...")
            else:
                filtered_prompts.append(prompt)
        
        filtered_count = len(prompts) - len(filtered_prompts)
        if filtered_count > 0:
            self._log(f"Filtered {filtered_count} prompts based on feedback analysis")

        if guidance.prompt_whitelist:
            filtered_prompts.sort(
                key=lambda text: self._pattern_bonus(text, guidance.prompt_whitelist),
                reverse=True,
            )

        if guidance.panel_flags:
            flagged = guidance.panel_flags[:3]
            summaries = ", ".join(f"{flag.window_title[:30]} ({', '.join(flag.issues)})" for flag in flagged if flag.issues)
            if summaries:
                self._log(f"Panels needing review detected: {summaries}")
        
        return filtered_prompts

    def _pattern_bonus(self, prompt_text: str, whitelist: List[str]) -> float:
        lowered = (prompt_text or "").lower()
        matches = sum(1 for pattern in whitelist if pattern and pattern.lower() in lowered)
        return matches

    def _compute_prompt_identifier(self, prompt_text: str) -> str:
        """Compute prompt identifier hash (same as panel tracker)."""
        import hashlib
        if not prompt_text:
            return ""
        digest = hashlib.sha256(prompt_text.encode("utf-8", errors="ignore")).hexdigest()
        return digest[:12]  # ASSIGNED_PROMPT_ID_LEN = 12

    def _write_prompt_file(
        self,
        repo_config: RepoConfig,
        docs: List[DocumentSlice],
        prompts: List[str],
        raw_text: str,
    ) -> Path:
        """Write prompt batch to file in repo-specific subdirectory."""
        repo_output_dir = self.output_dir / repo_config.name
        repo_output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%SZ")
        output_path = repo_output_dir / f"master_prompts_{timestamp}.txt"
        header_lines = [
            f"Master Agent Prompt Batch (UTC {timestamp})",
            f"Repository: {repo_config.name}",
            f"Model: {self.model}",
            f"Documents used: {len(docs)}",
            "",
        ]
        body_lines: List[str] = []
        if prompts:
            for idx, prompt in enumerate(prompts, 1):
                body_lines.append(f"{idx}. {prompt}")
                body_lines.append("")
        else:
            body_lines.append(raw_text)

        manifest = {
            "generated_at": timestamp,
            "repo_name": repo_config.name,
            "model": self.model,
            "prompt_count": len(prompts),
            "documents": [
                {"path": self._pretty_path(doc.path), "chars": doc.characters}
                for doc in docs
            ],
        }
        (repo_output_dir / "manifest.jsonl").parent.mkdir(parents=True, exist_ok=True)
        manifest_path = repo_output_dir / "manifest.jsonl"
        with manifest_path.open("a", encoding="utf-8") as manifest_file:
            manifest_file.write(json.dumps(manifest) + "\n")

        with output_path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(header_lines + body_lines).strip() + "\n")

        latest_path = repo_output_dir / "latest.txt"
        latest_path.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
        self._log(f"Saved prompt batch for repo '{repo_config.name}' to {output_path}")
        return output_path
    
    def _write_prompt_file_with_metadata(
        self,
        repo_config: RepoConfig,
        docs: List[DocumentSlice],
        prompts: List[str],
        raw_text: str,
        prompts_with_metadata: List[Tuple[str, PromptMetadata]],
    ) -> Tuple[Path, Path]:
        """Write prompt batch and metadata to files in repo-specific subdirectory."""
        repo_output_dir = self.output_dir / repo_config.name
        repo_output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%SZ")
        output_path = repo_output_dir / f"master_prompts_{timestamp}.txt"
        metadata_path = repo_output_dir / f"prompt_metadata_{timestamp}.json"
        
        # Build header with quality statistics
        avg_quality = sum(m.quality_score for _, m in prompts_with_metadata) / len(prompts_with_metadata) if prompts_with_metadata else 0.0
        task_type_counts: Dict[str, int] = {}
        for _, metadata in prompts_with_metadata:
            task_type_counts[metadata.task_type] = task_type_counts.get(metadata.task_type, 0) + 1
        
        header_lines = [
            f"Master Agent Prompt Batch (UTC {timestamp})",
            f"Repository: {repo_config.name}",
            f"Model: {self.model}",
            f"Documents used: {len(docs)}",
            f"Prompts generated: {len(prompts)}",
            f"Average quality score: {avg_quality:.2f}",
            f"Task types: {dict(task_type_counts)}",
            f"Quality validation: {'enabled' if self.enable_quality_validation else 'disabled'}",
            f"Quality threshold: {self.quality_threshold}",
            "",
        ]
        
        body_lines: List[str] = []
        if prompts:
            for idx, prompt in enumerate(prompts, 1):
                # Add quality score if we have metadata
                if idx <= len(prompts_with_metadata):
                    _, metadata = prompts_with_metadata[idx - 1]
                    quality_note = f" [Quality: {metadata.quality_score:.2f}, Type: {metadata.task_type}, Difficulty: {metadata.expected_difficulty}]"
                else:
                    quality_note = ""
                
                body_lines.append(f"{idx}. {prompt}{quality_note}")
                body_lines.append("")
        else:
            body_lines.append(raw_text)

        # Write prompt file
        with output_path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(header_lines + body_lines).strip() + "\n")

        # Write metadata file
        metadata_output = {
            "generated_at": timestamp,
            "repo_name": repo_config.name,
            "model": self.model,
            "prompt_count": len(prompts),
            "average_quality_score": avg_quality,
            "quality_threshold": self.quality_threshold,
            "features_enabled": {
                "quality_validation": self.enable_quality_validation,
                "adaptive_complexity": self.enable_adaptive_complexity,
                "prompt_templates": self.enable_prompt_templates,
                "human_review": self.enable_human_review,
            },
            "prompts": [
                {
                    "index": idx,
                    "metadata": asdict(metadata),
                }
                for idx, (_, metadata) in enumerate(prompts_with_metadata, 1)
            ],
        }
        
        metadata_path.write_text(json.dumps(metadata_output, indent=2), encoding="utf-8")
        
        # Update manifest
        manifest = {
            "generated_at": timestamp,
            "repo_name": repo_config.name,
            "model": self.model,
            "prompt_count": len(prompts),
            "average_quality_score": avg_quality,
            "metadata_file": str(metadata_path.name),
            "documents": [
                {"path": self._pretty_path(doc.path), "chars": doc.characters}
                for doc in docs
            ],
        }
        
        manifest_path = repo_output_dir / "manifest.jsonl"
        with manifest_path.open("a", encoding="utf-8") as manifest_file:
            manifest_file.write(json.dumps(manifest) + "\n")

        # Update latest feed files for the dispatcher
        latest_path = repo_output_dir / PROMPT_FEED_FILENAME
        latest_path.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
        
        # If this is the default repo, also update the root latest file for backward compatibility
        if repo_config.name == "default" or not repo_config.name:
            root_latest = self.output_dir / PROMPT_FEED_FILENAME
            root_latest.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")

        latest_metadata_path = repo_output_dir / "latest_metadata.json"
        latest_metadata_path.write_text(metadata_path.read_text(encoding="utf-8"), encoding="utf-8")
        
        self._log(f"Saved prompt batch for repo '{repo_config.name}' to {output_path}")
        self._log(f"Saved prompt metadata to {metadata_path}")
        
        return output_path, metadata_path

    def generate_cross_repo_coordination_prompt(self) -> Optional[Path]:
        """Write a coordination prompt summarizing active work across repos."""
        north_star = self._load_north_star_context()
        if north_star is None:
            return None

        active_tasks = [task for task in north_star.active_tasks if task.is_active]
        if not active_tasks:
            return None

        dependency_order = list(north_star.dependency_order or REPO_DEPENDENCY_ORDER)
        dependency_rank = {
            self._normalized_repo_name(repo_name): index
            for index, repo_name in enumerate(dependency_order)
        }
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        status_rank = {"in_progress": 0, "review": 1, "planned": 2, "blocked": 3}

        grouped_tasks: Dict[str, List[Any]] = defaultdict(list)
        for task in active_tasks:
            grouped_tasks[task.repo].append(task)

        ordered_repo_names = sorted(
            grouped_tasks,
            key=lambda repo_name: (
                dependency_rank.get(self._normalized_repo_name(repo_name), len(dependency_rank)),
                self._normalized_repo_name(repo_name),
            ),
        )

        leverage_task = min(
            active_tasks,
            key=lambda task: (
                dependency_rank.get(self._normalized_repo_name(task.repo), len(dependency_rank)),
                priority_rank.get(task.priority, 9),
                status_rank.get(task.status, 9),
            ),
        )
        leverage_role = self._north_star_role_for_repo(north_star, leverage_task.repo)
        downstream_note = ""
        if leverage_role is not None and leverage_role.depended_on_by:
            downstream_note = (
                f" before {', '.join(leverage_role.depended_on_by)} can safely advance dependent work"
            )

        lines: List[str] = []
        lines.append("# Cross-Repo Coordination Prompt")
        lines.append("")
        lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
        lines.append("")
        lines.append("## North Star")
        lines.append("")
        lines.append(f"- Primary goal: {north_star.primary_goal}")
        if north_star.primary_task_id:
            lines.append(f"- Primary task id: {north_star.primary_task_id}")
        lines.append(f"- Dependency order: {' -> '.join(dependency_order)}")
        lines.append("")
        lines.append("## In-Flight Tasks")
        lines.append("")
        for repo_name in ordered_repo_names:
            lines.append(f"### {repo_name}")
            for task in grouped_tasks[repo_name]:
                lines.append(f"- [{task.priority}][{task.status}] {task.task_id}: {task.title}")
            lines.append("")

        lines.append("## Highest-Leverage Next Cross-Repo Action")
        lines.append("")
        lines.append(
            f"Advance {leverage_task.repo} task {leverage_task.task_id}: {leverage_task.title}{downstream_note}."
        )
        lines.append("")
        lines.append("## Suggested Coordination Prompt")
        lines.append("")
        lines.append(
            "Review the in-flight tasks above, confirm the dependency order is being honored, and assign the next cross-repo action to the repo that unlocks the most downstream progress without crossing ownership boundaries."
        )

        output_path = self.output_dir / "cross_repo_coordination.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        self._log(f"Saved cross-repo coordination prompt to {output_path}")
        return output_path

    def _ensure_client(self) -> Any:
        if self.client:
            return self.client
        if OpenAIClient is None:
            raise RuntimeError(
                "openai package is not installed. Install dependencies from requirements.txt."
            )
        api_key, state = _resolve_openai_api_key()
        if not api_key:
            raise OpenAICredentialError(_format_missing_openai_api_key_message(state))
        self.client = OpenAIClient(api_key=api_key)
        self._credential_state = state
        return self.client

    def validate_openai_credentials(self) -> Dict[str, str]:
        self._ensure_client()
        credential_state = self._credential_state or OpenAICredentialState(
            source="unknown",
            repo_dotenv_path=REPO_DOTENV_PATH,
            repo_dotenv_exists=REPO_DOTENV_PATH.exists(),
        )
        self._log(
            f"Validating OpenAI credentials for model '{self.model}' using {credential_state.source}."
        )
        # Keep the probe as small as possible while honoring the Responses API minimum.
        self._responses_create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Reply with the single word READY."}],
                }
            ],
            max_output_tokens=16,
        )
        self._openai_credentials_validated = True
        return {
            "model": self.model,
            "credential_source": credential_state.source,
        }

    def _responses_create(self, **kwargs):
        client = self._ensure_client()
        credential_state = self._credential_state or OpenAICredentialState(
            source="unknown",
            repo_dotenv_path=REPO_DOTENV_PATH,
            repo_dotenv_exists=REPO_DOTENV_PATH.exists(),
        )
        try:
            return client.responses.create(**kwargs)
        except Exception as exc:
            _raise_for_openai_request_error(exc, credential_state)
            raise

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def _is_allowed_file(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        return suffix in self.allowed_extensions or suffix == ""

    def _pretty_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)

    def _merge_text_outputs(self, response) -> str:
        chunks: List[str] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", "") == "text":
                chunks.append(getattr(item, "text", ""))
        return "\n".join(chunks).strip()

    def _log(self, message: str) -> None:
        self.logger(message)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate master-agent prompts on demand")
    parser.add_argument(
        "--repos",
        nargs="*",
        help="Repository configurations in format 'name=path1,path2'. Can be specified multiple times.",
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        help="Override the document directories for default repo (backward compatibility)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Where to store generated prompt batches",
    )
    parser.add_argument("--max-docs", type=int, default=20, help="Max documents to include")
    parser.add_argument("--max-chars", type=int, default=4000, help="Max characters per document")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the OpenAI call and just list which files would be sent",
    )
    parser.add_argument(
        "--readiness-check",
        action="store_true",
        help="Run a deterministic docs-source readiness check for cache seeding and exit non-zero when any repo is not live-ready.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output for readiness checks.",
    )
    parser.add_argument(
        "--check-openai-credentials",
        action="store_true",
        help="Validate OpenAI credential readiness before a live prompt refresh",
    )
    parser.add_argument(
        "--agent-mode",
        choices=["normal", "maximise", "maximize"],
        help="Override the adaptive agent selection mode used to tag prompts",
    )
    
    # Enhanced feature flags
    parser.add_argument(
        "--disable-quality-validation",
        action="store_true",
        help="Disable prompt quality validation and filtering",
    )
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=0.4,
        help="Minimum quality score for prompts (0.0-1.0, default: 0.4)",
    )
    parser.add_argument(
        "--disable-adaptive-complexity",
        action="store_true",
        help="Disable adaptive complexity adjustment based on agent performance",
    )
    parser.add_argument(
        "--disable-templates",
        action="store_true",
        help="Disable prompt templates for common task types",
    )
    parser.add_argument(
        "--enable-human-review",
        action="store_true",
        help="Enable human review queue for generated prompts",
    )
    
    return parser


def _parse_repo_configs(args_repos: List[str], args_docs: List[str]) -> List[RepoConfig]:
    """Parse repo configurations from CLI arguments."""
    configs = []
    
    # Parse --repos arguments
    if args_repos:
        for repo_spec in args_repos:
            if '=' not in repo_spec:
                continue
            name, paths_str = repo_spec.split('=', 1)
            paths = [Path(p.strip()) for p in paths_str.split(',') if p.strip()]
            if name and paths:
                configs.append(
                    RepoConfig(
                        name=name.strip(),
                        docs_dirs=paths,
                        repo_root=MasterPromptOrchestrator._infer_repo_root_from_docs_dirs(paths),
                        config_source="cli",
                    )
                )
    
    # Backward compatibility: use --docs for default repo
    if args_docs and not configs:
        doc_paths = [Path(p) for p in args_docs]
        configs.append(
            RepoConfig(
                name="default",
                docs_dirs=doc_paths,
                repo_root=MasterPromptOrchestrator._infer_repo_root_from_docs_dirs(doc_paths),
                config_source="cli",
            )
        )
    
    return configs


def _serialize_readiness_reports(reports: Sequence[RepoReadinessReport]) -> Dict[str, Any]:
    repos_payload: List[Dict[str, Any]] = []
    all_ready = True
    for report in reports:
        all_ready = all_ready and report.seeding_ready
        repos_payload.append(
            {
                "repo_name": report.repo_name,
                "config_source": report.config_source,
                "repo_root": str(report.repo_root) if report.repo_root else None,
                "status": report.status,
                "live_ready": report.live_ready,
                "seeding_ready": report.seeding_ready,
                "cache_available": report.cache_available,
                "cache_dir": str(report.cache_dir),
                "next_steps": report.next_steps,
                "docs_sources": [
                    {
                        "path": str(source.directory),
                        "repo_root": str(source.repo_root) if source.repo_root else None,
                        "status": source.status,
                        "issue_kind": source.issue_kind,
                        "config_source": source.config_source,
                        "cache_available": source.cache_available,
                        "live_document_count": source.live_document_count,
                        "expected_relative_dir": source.expected_relative_dir,
                        "message": source.message,
                        "next_steps": source.next_steps,
                    }
                    for source in report.docs_sources
                ],
            }
        )
    return {"all_repos_ready": all_ready, "repos": repos_payload}


def _print_readiness_plain(reports: Sequence[RepoReadinessReport]) -> None:
    print("Master prompt orchestrator readiness")
    for report in reports:
        print(f"Repo '{report.repo_name}': {report.status}")
        print(f"  Live ready: {report.live_ready}")
        print(f"  Cache available: {report.cache_available}")
        if report.repo_root:
            print(f"  Repo root: {report.repo_root}")
        for source in report.docs_sources:
            print(f"  - {source.directory}: {source.status}")
            print(f"    {source.message}")
            if source.expected_relative_dir:
                print(f"    Expected relative dir: {source.expected_relative_dir}")
        for step in report.next_steps:
            print(f"  Next step: {step}")


def main() -> None:
    parser = _build_cli_parser()
    args = parser.parse_args()
    parsed_repo_configs = _parse_repo_configs(args.repos or [], args.docs or [])
    repo_configs = parsed_repo_configs or None

    try:
        if args.check_openai_credentials:
            orchestrator = MasterPromptOrchestrator(
                repo_configs=[],
                output_dir=Path(args.output_dir),
                max_docs=args.max_docs,
                max_chars=args.max_chars,
                agent_selection_mode=args.agent_mode,
                enable_quality_validation=not args.disable_quality_validation,
                quality_threshold=args.quality_threshold,
                enable_adaptive_complexity=not args.disable_adaptive_complexity,
                enable_prompt_templates=not args.disable_templates,
                enable_human_review=args.enable_human_review,
            )
            result = orchestrator.validate_openai_credentials()
            print(
                "OPENAI READY: "
                f"model={result['model']} credential_source={result['credential_source']}"
            )
            return

        orchestrator = MasterPromptOrchestrator(
            repo_configs=repo_configs,
            output_dir=Path(args.output_dir),
            max_docs=args.max_docs,
            max_chars=args.max_chars,
            agent_selection_mode=args.agent_mode,
            enable_quality_validation=not args.disable_quality_validation,
            quality_threshold=args.quality_threshold,
            enable_adaptive_complexity=not args.disable_adaptive_complexity,
            enable_prompt_templates=not args.disable_templates,
            enable_human_review=args.enable_human_review,
        )

        if args.readiness_check:
            reports = orchestrator.build_readiness_report()
            payload = _serialize_readiness_reports(reports)
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                _print_readiness_plain(reports)
            raise SystemExit(0 if payload["all_repos_ready"] else 1)

        if args.dry_run:
            # For dry run, show documents for each repo
            for repo_config in orchestrator.repo_configs:
                docs = orchestrator.collect_documents(repo_config)
                print(f"Repo '{repo_config.name}': Collected {len(docs)} documents")
                for doc in docs:
                    print(f"  - {orchestrator._pretty_path(doc.path)} ({doc.characters} chars)")
            return

        results = orchestrator.generate_prompt_batches()
        for result in results:
            if result:
                print(f"\nPrompts for repo '{result.repo_name}':")
                print(f"  Generated: {result.prompt_count} prompts")
                print(f"  Saved to: {result.output_path}")
                if result.metadata_file:
                    print(f"  Metadata: {result.metadata_file}")
                if result.prompts_with_metadata:
                    avg_quality = sum(m.quality_score for _, m in result.prompts_with_metadata) / len(result.prompts_with_metadata)
                    print(f"  Average quality score: {avg_quality:.2f}")
            else:
                print("No prompts were generated for some repos.")
    except OpenAICredentialError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":  # pragma: no cover
    main()
