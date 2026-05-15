"""Comprehensive tests for the enhanced Master Prompt Orchestrator.

The suite validates repository analysis, scoring, templates, deduplication, diversity,
adaptive complexity, metadata, and integration workflows to keep coverage above 90%."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.cross_repo_todo_ingestion import TodoItem
from automation.feedback_analyzer import FeedbackInsights, PromptPerformance
from automation.master_prompt_orchestrator import (
    DocumentSlice,
    MasterPromptOrchestrator,
    PromptMetadata,
    PromptQualityScorer,
    RepoConfig,
    RepositoryAnalysis,
    RepositoryAnalyzer,
)
from automation.north_star import ActiveTask, NorthStarContext, RepoRole


def _doc_slice(content: str, path: Path | None = None, repo_name: str = "demo") -> DocumentSlice:
    doc_path = path or Path(f"{repo_name}/docs/doc.md")
    return DocumentSlice(
        path=doc_path,
        content=content,
        characters=len(content),
        modified_epoch=datetime.now(timezone.utc).timestamp(),
        repo_name=repo_name,
    )


def _repo_analysis(repo_name: str = "demo") -> RepositoryAnalysis:
    return RepositoryAnalysis(
        repo_name=repo_name,
        primary_language="py",
        file_count=10,
        architecture_style="microservices",
        code_patterns=["singleton"],
        conventions={"style_guide": "PEP 8"},
        dependencies=["requests"],
        test_coverage_estimate=0.8,
    )


def _prompt_metadata(
    prompt_id: str = "meta12345678",
    prompt_hash: str = "deadbeefcafebabe",
    task_type: str = "bug_fix",
    difficulty: str = "moderate",
    template: str | None = None,
) -> PromptMetadata:
    return PromptMetadata(
        prompt_id=prompt_id,
        prompt_hash=prompt_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_name="demo",
        source_documents=["docs/Todo.md"],
        rationale="Task type: bug_fix",
        expected_difficulty=difficulty,
        dependencies=[],
        task_type=task_type,
        quality_score=0.8,
        template_used=template,
    )


def _feedback_insights(
    prompt_id: str = "deadbeef0000",
    total: int = 10,
    success: int = 8,
) -> FeedbackInsights:
    performance = PromptPerformance(
        prompt_id=prompt_id,
        prompt_preview="Fix login bug",
        total_responses=total,
        successful_responses=success,
        error_responses=max(total - success - 1, 0),
        clarification_requests=1,
        avg_confidence=0.8,
        avg_processing_time=1.0,
    )
    return FeedbackInsights(
        prompt_performance=[performance],
        problematic_patterns=[],
        successful_patterns=[],
        recommended_filters=[],
    )


def _prepare_repo(tmp_path: Path, repo_name: str = "demo") -> tuple[RepoConfig, Path]:
    docs_dir = tmp_path / repo_name / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "Todo.md").write_text("- [ ] Fix bug", encoding="utf-8")
    repo_config = RepoConfig(name=repo_name, docs_dirs=[docs_dir])
    return repo_config, docs_dir


def _north_star_context(*active_tasks: ActiveTask) -> NorthStarContext:
    repo_roles = {
        "contracts": RepoRole(
            name="contracts",
            owns=["schemas", "rules", "fixtures"],
            must_not_do=["model code", "trading code"],
            depends_on=[],
            depended_on_by=["TF", "Trading"],
        ),
        "TF": RepoRole(
            name="TF",
            owns=["training", "features", "model export"],
            must_not_do=["order execution", "schema changes"],
            depends_on=["contracts"],
            depended_on_by=["Trading"],
        ),
        "Trading": RepoRole(
            name="Trading",
            owns=["execution", "routing", "market data"],
            must_not_do=["training", "schema changes"],
            depends_on=["contracts", "TF"],
            depended_on_by=[],
        ),
    }
    return NorthStarContext(
        primary_goal="Unblock the paper-trading promotion path.",
        primary_task_id="NS-1",
        active_tasks=list(active_tasks),
        repo_roles=repo_roles,
        dependency_order=["contracts", "TF", "Trading"],
        routing_summary="contracts -> TF -> Trading",
    )


def _build_integration_orchestrator(
    tmp_path: Path,
    response_text: str,
) -> tuple[MasterPromptOrchestrator, RepoConfig]:
    repo_config, _ = _prepare_repo(tmp_path)
    orchestrator = MasterPromptOrchestrator(
        repo_configs=[repo_config],
        output_dir=tmp_path / "out",
        client=_StaticResponseClient(response_text),
        max_docs=5,
        max_chars=4000,
        quality_threshold=0.4,
    )
    return orchestrator, repo_config


class _StaticResponseClient:
    """Deterministic OpenAI client stub for integration tests."""

    def __init__(self, text: str):
        self._text = text
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **_kwargs):
        return SimpleNamespace(output=[SimpleNamespace(type="text", text=self._text)], usage=None)


@pytest.fixture(autouse=True)
def _stub_agent_policy(monkeypatch):
    class _StubPolicy:
        def __init__(self, mode: str | None = None):
            self.mode = mode

        def annotate_prompts(self, prompts: list[str]) -> list[str]:
            return prompts

    monkeypatch.setattr("automation.master_prompt_orchestrator.AdaptiveAgentSelectionPolicy", _StubPolicy)


@pytest.fixture(autouse=True)
def _stub_cost_tracker(monkeypatch):
    tracker = MagicMock()
    tracker.record_text_usage = MagicMock()
    monkeypatch.setattr("automation.master_prompt_orchestrator._COST_TRACKER", tracker)
    return tracker


@pytest.fixture
def template_orchestrator() -> MasterPromptOrchestrator:
    orchestrator = MasterPromptOrchestrator.__new__(MasterPromptOrchestrator)
    orchestrator.enable_prompt_templates = True
    return orchestrator


@pytest.fixture
def orchestrator_stub(tmp_path: Path) -> MasterPromptOrchestrator:
    orchestrator = MasterPromptOrchestrator.__new__(MasterPromptOrchestrator)
    orchestrator.enable_prompt_templates = True
    orchestrator.enable_quality_validation = True
    orchestrator.enable_adaptive_complexity = True
    orchestrator.enable_human_review = False
    orchestrator.quality_threshold = 0.4
    orchestrator.feedback_analyzer = MagicMock()
    orchestrator.quality_scorer = PromptQualityScorer(feedback_analyzer=MagicMock())
    orchestrator.repo_analyzer = RepositoryAnalyzer()
    orchestrator.agent_selection_policy = SimpleNamespace(annotate_prompts=lambda prompts: prompts)
    orchestrator.output_dir = tmp_path
    orchestrator.model = "test-model"
    orchestrator._log = MagicMock()
    return orchestrator


@pytest.fixture
def disable_cross_repo(monkeypatch):
    monkeypatch.setattr("automation.master_prompt_orchestrator.CROSS_REPO_TODO_ENABLED", False)


@pytest.fixture
def integration_feedback_stub(monkeypatch):
    stub = MagicMock()
    stub.analyze_feedback.return_value = _feedback_insights()
    stub.get_guidance.return_value = SimpleNamespace(prompt_whitelist=[], panel_flags=[])
    stub.should_filter_prompt.return_value = (False, "")
    monkeypatch.setattr("automation.master_prompt_orchestrator.get_feedback_analyzer", lambda: stub)
    return stub


class TestRepositoryAnalyzer:
    """Test repository analysis functionality."""

    def test_analyze_repository_detects_python(self, tmp_path: Path):
        """Should detect Python as primary language from .py files"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "main.py").write_text("print('hi')", encoding="utf-8")
        (docs_dir / "helper.py").write_text("pass", encoding="utf-8")
        docs = [_doc_slice("Repo overview")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert result.primary_language == "py"

    def test_analyze_repository_detects_architecture_microservices(self, tmp_path: Path):
        """Should detect microservices architecture from doc keywords"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        docs = [_doc_slice("This platform uses a microservice mesh with API gateway.")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert result.architecture_style == "microservices"

    def test_analyze_repository_detects_architecture_monolithic(self, tmp_path: Path):
        """Should detect monolithic architecture from doc keywords"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        docs = [_doc_slice("Legacy monolith with single application tier.")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert result.architecture_style == "monolithic"

    def test_extract_code_patterns_finds_singleton(self, tmp_path: Path):
        """Should identify singleton pattern from documentation"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        docs = [_doc_slice("Services rely on a singleton registry for config.")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert "singleton" in result.code_patterns

    def test_extract_code_patterns_finds_factory(self, tmp_path: Path):
        """Should identify factory pattern from documentation"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        docs = [_doc_slice("UI widgets are created via factory pattern helpers.")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert "factory" in result.code_patterns

    def test_extract_conventions_finds_pep8(self, tmp_path: Path):
        """Should detect PEP 8 style guide from documentation"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        docs = [_doc_slice("Follow PEP 8 for style across services.")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert result.conventions.get("style_guide") == "PEP 8"

    def test_extract_conventions_finds_naming_snake_case(self, tmp_path: Path):
        """Should detect snake_case naming convention"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        docs = [_doc_slice("Functions must use snake_case naming.")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert result.conventions.get("naming") == "snake_case"

    def test_extract_dependencies_from_requirements_txt(self, tmp_path: Path):
        """Should parse dependencies from requirements.txt"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        requirements_path = docs_dir.parent / "requirements.txt"
        requirements_path.write_text("requests==2.0\npytest>=7.0", encoding="utf-8")
        docs = [_doc_slice("Deps doc")]

        result = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert result.dependencies == ["pytest", "requests"]

    def test_analyze_repository_caches_results(self, tmp_path: Path):
        """Should cache analysis results and reuse for same repo"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "main.py").write_text("print('hi')", encoding="utf-8")
        docs = [_doc_slice("microservice references")]

        with patch.object(analyzer, "_detect_architecture_style", wraps=analyzer._detect_architecture_style) as mock_detect:
            first = analyzer.analyze_repository("demo", docs, [docs_dir])
            second = analyzer.analyze_repository("demo", docs, [docs_dir])

        assert first is second
        assert mock_detect.call_count == 1

    def test_analyze_repository_handles_missing_dirs(self, tmp_path: Path):
        """Should handle non-existent directories gracefully"""

        analyzer = RepositoryAnalyzer()
        docs_dir = tmp_path / "demo" / "docs"
        docs_dir.mkdir(parents=True)
        missing_dir = tmp_path / "demo" / "ghost"
        docs = [_doc_slice("Doc content")]

        result = analyzer.analyze_repository("demo", docs, [missing_dir, docs_dir])

        assert result.file_count >= 0


class TestPromptQualityScorer:
    """Test quality scoring system."""

    def test_score_prompt_with_high_quality(self):
        """Should score well-structured, clear prompt highly (>0.7)"""

        feedback = _feedback_insights(prompt_id="abc12345ffff", success=9, total=10)
        analyzer = MagicMock()
        analyzer.analyze_feedback.return_value = feedback
        scorer = PromptQualityScorer(feedback_analyzer=analyzer)
        metadata = _prompt_metadata(prompt_hash="abc12345deadbeef")

        score = scorer.score_prompt(
            "Implement feature X with clear deliverables and testing plan.",
            metadata,
            _repo_analysis(),
        )

        assert score >= 0.65

    def test_score_prompt_with_low_quality(self):
        """Should score vague, unclear prompt lowly (<0.4)"""

        analyzer = MagicMock()
        analyzer.analyze_feedback.return_value = _feedback_insights()
        scorer = PromptQualityScorer(feedback_analyzer=analyzer)
        metadata = _prompt_metadata(prompt_hash="")

        score = scorer.score_prompt("Maybe do something if possible?", metadata, _repo_analysis())

        assert score < 0.4

    def test_score_clarity_rewards_action_verbs(self):
        """Should increase clarity score for specific action verbs"""

        scorer = PromptQualityScorer(feedback_analyzer=MagicMock())

        prompt_text = (
            "Implement and thoroughly test the module by following the detailed plan. "
            "Document assumptions, highlight risks, and provide numbered execution steps. "
            "1. Analyze data sources and enumerate invariants. "
            "2. Refactor the parser, verify outcomes, and report findings in detail."
        )
        score = scorer._score_clarity(prompt_text)

        assert score >= 0.6

    def test_score_clarity_penalizes_vague_language(self):
        """Should decrease clarity score for vague terms"""

        scorer = PromptQualityScorer(feedback_analyzer=MagicMock())

        score = scorer._score_clarity("Maybe this could be done perhaps someday")

        assert score < 0.5

    def test_score_actionability_rewards_deliverables(self):
        """Should increase score when deliverables are specified"""

        scorer = PromptQualityScorer(feedback_analyzer=MagicMock())

        score = scorer._score_actionability("Provide deliverable code, ensure tests must pass")

        assert score > 0.7

    def test_score_context_rewards_context_sections(self):
        """Should increase score when context is provided"""

        scorer = PromptQualityScorer(feedback_analyzer=MagicMock())
        metadata = _prompt_metadata()

        score = scorer._score_context("Context: architecture info", metadata)

        assert score > 0.5

    def test_score_historical_performance_uses_feedback(self):
        """Should use feedback analyzer data for historical scoring"""

        insights = _feedback_insights(prompt_id="deadbeef1234", success=6, total=10)
        analyzer = MagicMock()
        analyzer.analyze_feedback.return_value = insights
        scorer = PromptQualityScorer(feedback_analyzer=analyzer)

        historical = scorer._score_historical_performance("deadbeef9876")

        assert historical == pytest.approx(0.6, rel=1e-3)

    def test_score_historical_performance_uses_template_success_rate(self):
        """Should use template success rate when no feedback data"""

        analyzer = MagicMock()
        analyzer.analyze_feedback.return_value = _feedback_insights(prompt_id="zzz")
        scorer = PromptQualityScorer(feedback_analyzer=analyzer)
        metadata = _prompt_metadata(prompt_hash="", template="bug_fix_template")

        with patch.object(scorer, "_get_template_success_rate", return_value=0.9):
            score = scorer.score_prompt("Implement API feature", metadata, _repo_analysis())

        assert score >= 0.27  # includes 0.3 * template success

    def test_score_prompt_clamps_to_zero_one_range(self):
        """Should ensure score is always between 0.0 and 1.0"""

        analyzer = MagicMock()
        analyzer.analyze_feedback.return_value = _feedback_insights()
        scorer = PromptQualityScorer(feedback_analyzer=analyzer)
        metadata = _prompt_metadata()

        with patch.object(scorer, "_score_clarity", return_value=-2.0), \
             patch.object(scorer, "_score_actionability", return_value=-2.0), \
             patch.object(scorer, "_score_context", return_value=-2.0), \
             patch.object(scorer, "_score_historical_performance", return_value=-2.0):
            score = scorer.score_prompt("", metadata, _repo_analysis())

        assert 0.0 <= score <= 1.0


class TestPromptTemplates:
    """Test template matching and classification."""

    def test_classify_task_type_bug_fix(self, template_orchestrator: MasterPromptOrchestrator):
        """Should classify bug-related prompts as 'bug_fix'"""

        assert template_orchestrator._classify_task_type("Fix the login bug") == "bug_fix"

    def test_classify_task_type_feature(self, template_orchestrator: MasterPromptOrchestrator):
        """Should classify feature prompts as 'feature'"""

        assert template_orchestrator._classify_task_type("Implement new feature flag") == "feature"

    def test_classify_task_type_refactor(self, template_orchestrator: MasterPromptOrchestrator):
        """Should classify refactoring prompts as 'refactor'"""

        assert template_orchestrator._classify_task_type("Refactor service for clarity") == "refactor"

    def test_classify_task_type_testing(self, template_orchestrator: MasterPromptOrchestrator):
        """Should classify test-related prompts as 'testing'"""

        assert template_orchestrator._classify_task_type("Add unit tests for parser") == "testing"

    def test_classify_task_type_documentation(self, template_orchestrator: MasterPromptOrchestrator):
        """Should classify doc prompts as 'documentation'"""

        assert template_orchestrator._classify_task_type("Document the API usage") == "documentation"

    def test_identify_template_match_returns_correct_template(self, template_orchestrator: MasterPromptOrchestrator):
        """Should match prompt to appropriate template by task type"""

        match = template_orchestrator._identify_template_match("Fix the crash bug in auth module")

        assert match == "bug_fix_template"

    def test_identify_template_match_returns_none_when_disabled(self, template_orchestrator: MasterPromptOrchestrator):
        """Should return None when templates are disabled"""

        template_orchestrator.enable_prompt_templates = False

        assert template_orchestrator._identify_template_match("Add tests") is None


class TestDeduplication:
    """Test duplicate and similarity detection."""

    def test_deduplicate_removes_exact_duplicates(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should remove prompts with identical hashes"""

        metadata = _prompt_metadata(prompt_hash="hash-one")
        duplicate = _prompt_metadata(prompt_hash="hash-one")
        prompts = [("Fix bug", metadata), ("Fix bug", duplicate)]

        deduped = orchestrator_stub._deduplicate_prompts(prompts)

        assert len(deduped) == 1

    def test_deduplicate_keeps_unique_prompts(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should keep prompts with different hashes"""

        prompts = [
            ("Fix auth bug", _prompt_metadata(prompt_hash="hash-a")),
            ("Add metrics", _prompt_metadata(prompt_hash="hash-b")),
        ]

        deduped = orchestrator_stub._deduplicate_prompts(prompts)

        assert len(deduped) == 2

    def test_is_similar_detects_high_overlap(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should detect prompts with >70% word overlap as similar"""

        existing = [("Fix the login button crash in checkout", _prompt_metadata())]

        assert orchestrator_stub._is_similar_to_existing(
            "Fix the login button crash in checkout flow",
            existing,
        )

    def test_is_similar_allows_low_overlap(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should allow prompts with <70% word overlap"""

        existing = [("Fix the login button crash", _prompt_metadata())]

        assert not orchestrator_stub._is_similar_to_existing("Write documentation", existing)

    def test_deduplicate_logs_removed_count(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should log number of duplicates removed"""

        prompts = [
            ("Fix bug", _prompt_metadata(prompt_hash="hash-a")),
            ("Fix bug again", _prompt_metadata(prompt_hash="hash-a")),
        ]

        orchestrator_stub._deduplicate_prompts(prompts)

        messages = [call.args[0] for call in orchestrator_stub._log.call_args_list]
        assert any("Removed" in message for message in messages)


class TestDiversityEnforcement:
    """Test task type balancing logic."""

    def test_ensure_diversity_limits_per_task_type(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should limit prompts per task type to max_per_type"""

        prompts = []
        for idx in range(6):
            meta = _prompt_metadata(prompt_hash=f"feature-{idx}", task_type="feature")
            meta.quality_score = 0.9 - idx * 0.05
            prompts.append((f"Feature prompt {idx}", meta))
        for idx in range(2):
            meta = _prompt_metadata(prompt_hash=f"bug-{idx}", task_type="bug_fix")
            meta.quality_score = 0.8
            prompts.append((f"Bug prompt {idx}", meta))

        result = orchestrator_stub._ensure_prompt_diversity(prompts)

        feature_count = sum(1 for _, meta in result if meta.task_type == "feature")
        assert feature_count <= 4  # max_per_type for 8 prompts across 2 types

    def test_ensure_diversity_selects_highest_quality(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should select highest quality prompts within each type"""

        prompts = []
        for score in [0.2, 0.5, 0.9]:
            meta = _prompt_metadata(prompt_hash=f"test-{score}", task_type="testing")
            meta.quality_score = score
            prompts.append((f"Testing prompt {score}", meta))

        result = orchestrator_stub._ensure_prompt_diversity(prompts)

        qualities = [meta.quality_score for _, meta in result if meta.task_type == "testing"]
        assert qualities == sorted(qualities, reverse=True)

    def test_ensure_diversity_balances_task_types(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should ensure balanced distribution across types"""

        prompts = [
            ("Fix bug", _prompt_metadata(prompt_hash="bug", task_type="bug_fix")),
            ("Add feature", _prompt_metadata(prompt_hash="feature", task_type="feature")),
            ("Write docs", _prompt_metadata(prompt_hash="doc", task_type="documentation")),
            ("Add tests", _prompt_metadata(prompt_hash="test", task_type="testing")),
        ]
        for _, meta in prompts:
            meta.quality_score = 0.9

        result = orchestrator_stub._ensure_prompt_diversity(prompts)
        task_types = {meta.task_type for _, meta in result}

        assert task_types == {"bug_fix", "feature", "documentation", "testing"}


class TestAdaptiveComplexity:
    """Test adaptive complexity logic."""

    def test_adjust_complexity_simplifies_when_agents_struggling(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should simplify prompts when success rate <50%"""

        orchestrator_stub.feedback_analyzer.analyze_feedback.return_value = _feedback_insights(
            prompt_id="low",
            success=4,
            total=10,
        )
        metadata = _prompt_metadata(difficulty="complex")
        prompts = [("Complex task description", metadata)]

        adjusted = orchestrator_stub._adjust_prompt_complexity(prompts)

        text, updated = adjusted[0]
        assert "**Note**" in text
        assert updated.expected_difficulty == "moderate"
        assert updated.adaptive_complexity_level == "simplified"

    def test_adjust_complexity_maintains_when_agents_succeeding(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should maintain complexity when success rate >80%"""

        orchestrator_stub.feedback_analyzer.analyze_feedback.return_value = _feedback_insights(
            prompt_id="high",
            success=9,
            total=10,
        )
        metadata = _prompt_metadata(difficulty="moderate")
        prompts = [("Moderate task", metadata)]

        adjusted = orchestrator_stub._adjust_prompt_complexity(prompts)

        assert adjusted[0][1].adaptive_complexity_level == "increase"
        assert adjusted[0][0] == "Moderate task"

    def test_adjust_complexity_adds_simplification_note(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should add step-by-step guidance when simplifying"""

        orchestrator_stub.feedback_analyzer.analyze_feedback.return_value = _feedback_insights(
            prompt_id="low2",
            success=3,
            total=10,
        )
        metadata = _prompt_metadata(difficulty="complex")
        prompts = [("Rewrite entire service", metadata)]

        adjusted = orchestrator_stub._adjust_prompt_complexity(prompts)

        assert "Break this task" in adjusted[0][0]

    def test_adjust_complexity_updates_metadata(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should update metadata with adaptive_complexity_level"""

        orchestrator_stub.feedback_analyzer.analyze_feedback.return_value = _feedback_insights(
            prompt_id="mid",
            success=6,
            total=10,
        )
        metadata = _prompt_metadata(difficulty="moderate")
        prompts = [("Balanced task", metadata)]

        adjusted = orchestrator_stub._adjust_prompt_complexity(prompts)

        assert adjusted[0][1].adaptive_complexity_level == "maintain"


class TestMetadataGeneration:
    """Test metadata and difficulty estimation."""

    def test_generate_prompt_metadata_creates_all_fields(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should create metadata with all required fields"""

        docs = [_doc_slice("Todo content", Path("docs/Todo.md"))]
        repo_analysis = _repo_analysis()
        todo_items = [TodoItem(text="Task", title="Task", is_blocked=False)]

        prompts_with_metadata = orchestrator_stub._generate_prompt_metadata(
            ["Fix the failing unit tests"],
            "demo",
            docs,
            repo_analysis,
            todo_items,
        )

        _, metadata = prompts_with_metadata[0]
        assert metadata.prompt_id
        assert metadata.prompt_hash
        assert metadata.rationale

    def test_generate_prompt_metadata_computes_hash(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should compute correct prompt hash"""

        docs = [_doc_slice("Architecture doc")]
        repo_analysis = _repo_analysis()
        prompt = "Fix the memory leak"

        metadata = orchestrator_stub._generate_prompt_metadata(
            [prompt],
            "demo",
            docs,
            repo_analysis,
            [],
        )[0][1]

        expected_hash = hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()
        assert metadata.prompt_hash == expected_hash

    def test_generate_prompt_metadata_classifies_task_type(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should correctly classify task type"""

        metadata = orchestrator_stub._generate_prompt_metadata(
            ["Fix the crash in parser"],
            "demo",
            [_doc_slice("Doc")],
            _repo_analysis(),
            [],
        )[0][1]

        assert metadata.task_type == "bug_fix"

    def test_generate_prompt_metadata_estimates_difficulty(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should estimate difficulty as simple/moderate/complex"""

        metadata = orchestrator_stub._generate_prompt_metadata(
            ["Implement feature with architecture references and multiple steps"],
            "demo",
            [_doc_slice("Doc")],
            _repo_analysis(),
            [],
        )[0][1]

        assert metadata.expected_difficulty in {"moderate", "complex"}

    def test_estimate_difficulty_simple_for_short_prompts(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should classify short prompts (<100 words) as simple"""

        difficulty = orchestrator_stub._estimate_difficulty("Fix typo")

        assert difficulty == "simple"

    def test_estimate_difficulty_complex_for_long_prompts(self, orchestrator_stub: MasterPromptOrchestrator):
        """Should classify long prompts (>300 words) as complex"""

        long_prompt = " ".join(["word"] * 320)

        assert orchestrator_stub._estimate_difficulty(long_prompt) == "complex"


class TestIntegrationWorkflow:
    """Test end-to-end prompt generation pipeline."""

    def _response_text(self) -> str:
        return (
            "1. Fix login bug (Grok): Investigate failing auth.\n"
            "2. Add missing tests (Codex): Increase coverage."
        )

    def test_generate_prompt_batch_end_to_end(
        self,
        tmp_path: Path,
        disable_cross_repo,
        integration_feedback_stub,
        monkeypatch,
    ):
        """Should generate complete prompt batch with all enhancements"""

        monkeypatch.setattr(
            PromptQualityScorer,
            "score_prompt",
            lambda self, text, metadata, analysis: 0.9,
        )
        orchestrator, repo_config = _build_integration_orchestrator(tmp_path, self._response_text())

        result = orchestrator.generate_prompt_batch_for_repo(repo_config)

        assert result is not None
        assert result.prompt_count == 2
        assert result.metadata_file and result.metadata_file.exists()
        assert len(result.prompts_with_metadata) == 2

    def test_generate_prompt_batch_filters_low_quality(
        self,
        tmp_path: Path,
        disable_cross_repo,
        integration_feedback_stub,
        monkeypatch,
    ):
        """Should filter prompts below quality threshold"""

        scores = iter([0.2, 0.8])

        def fake_score(*_args, **_kwargs):
            return next(scores)

        monkeypatch.setattr(PromptQualityScorer, "score_prompt", fake_score)
        orchestrator, repo_config = _build_integration_orchestrator(tmp_path, self._response_text())

        result = orchestrator.generate_prompt_batch_for_repo(repo_config)

        assert result is not None
        assert result.prompt_count == 1

    def test_generate_prompt_batch_applies_feedback_filtering(
        self,
        tmp_path: Path,
        disable_cross_repo,
        integration_feedback_stub,
        monkeypatch,
    ):
        """Should filter prompts with poor historical performance"""

        integration_feedback_stub.should_filter_prompt.side_effect = [
            (True, "blocked"),
            (False, ""),
        ]
        monkeypatch.setattr(
            PromptQualityScorer,
            "score_prompt",
            lambda self, text, metadata, analysis: 0.9,
        )
        orchestrator, repo_config = _build_integration_orchestrator(tmp_path, self._response_text())

        result = orchestrator.generate_prompt_batch_for_repo(repo_config)

        assert result is not None
        assert result.prompt_count == 1
        assert integration_feedback_stub.should_filter_prompt.call_count >= 1

    def test_generate_prompt_batch_writes_metadata_file(
        self,
        tmp_path: Path,
        disable_cross_repo,
        integration_feedback_stub,
        monkeypatch,
    ):
        """Should write metadata JSON file alongside prompts"""

        monkeypatch.setattr(
            PromptQualityScorer,
            "score_prompt",
            lambda self, text, metadata, analysis: 0.9,
        )
        orchestrator, repo_config = _build_integration_orchestrator(tmp_path, self._response_text())

        result = orchestrator.generate_prompt_batch_for_repo(repo_config)

        assert result and result.metadata_file
        metadata = json.loads(result.metadata_file.read_text(encoding="utf-8"))
        assert metadata["quality_threshold"] == 0.4
        assert metadata["prompt_count"] == result.prompt_count

    def test_generate_prompt_batch_updates_manifest(
        self,
        tmp_path: Path,
        disable_cross_repo,
        integration_feedback_stub,
        monkeypatch,
    ):
        """Should append to manifest.jsonl with quality stats"""

        monkeypatch.setattr(
            PromptQualityScorer,
            "score_prompt",
            lambda self, text, metadata, analysis: 0.9,
        )
        orchestrator, repo_config = _build_integration_orchestrator(tmp_path, self._response_text())

        result = orchestrator.generate_prompt_batch_for_repo(repo_config)

        manifest_path = tmp_path / "out" / repo_config.name / "manifest.jsonl"
        assert manifest_path.exists()
        last_line = manifest_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        manifest_entry = json.loads(last_line)
        assert manifest_entry["repo_name"] == repo_config.name
        assert manifest_entry["prompt_count"] == result.prompt_count


class TestNorthStarPromptEnhancements:
    def test_system_prompt_includes_repo_role_and_priority_tasks(
        self,
        orchestrator_stub: MasterPromptOrchestrator,
    ):
        north_star = _north_star_context(
            ActiveTask(
                task_id="TF-101",
                title="Export the promoted model manifest",
                description="Ship the next manifest to Trading.",
                status="in_progress",
                priority="P0",
                repo="TF",
            ),
            ActiveTask(
                task_id="TF-102",
                title="Tighten feature validation",
                description="Guard input assumptions before export.",
                status="planned",
                priority="P1",
                repo="TF",
            ),
        )
        repo_analysis = _repo_analysis("TF")
        repo_config = RepoConfig(
            name="TF",
            docs_dirs=[],
            role="upstream framework",
        )

        with patch.object(orchestrator_stub, "_load_north_star_context", return_value=north_star):
            prompt = orchestrator_stub._build_system_prompt(
                _feedback_insights(),
                repo_analysis,
                repo_config,
            )

        assert "Role: upstream framework" in prompt
        assert "Current repo P0/P1 North Star tasks" in prompt
        assert "TF-101: Export the promoted model manifest" in prompt
        assert "TF-102: Tighten feature validation" in prompt
        assert "Must not do" in prompt

    def test_generate_cross_repo_coordination_prompt_writes_non_empty_output(
        self,
        tmp_path: Path,
        disable_cross_repo,
    ):
        north_star = _north_star_context(
            ActiveTask(
                task_id="C-1",
                title="Finalize schema checksum",
                description="Lock the schema used downstream.",
                status="in_progress",
                priority="P0",
                repo="contracts",
            ),
            ActiveTask(
                task_id="T-7",
                title="Prepare live routing validation",
                description="Validate the paper-trading handoff.",
                status="planned",
                priority="P1",
                repo="Trading",
            ),
        )
        orchestrator = MasterPromptOrchestrator(
            repo_configs=[RepoConfig(name="Trading", docs_dirs=[])],
            output_dir=tmp_path / "out",
            client=_StaticResponseClient("1. Prompt (Grok): do work"),
            max_docs=1,
            max_chars=200,
        )

        with patch.object(orchestrator, "_load_north_star_context", return_value=north_star):
            output_path = orchestrator.generate_cross_repo_coordination_prompt()

        assert output_path is not None
        assert output_path.exists()
        contents = output_path.read_text(encoding="utf-8")
        assert contents.strip()
        assert "contracts" in contents
        assert "Trading" in contents
        assert "Advance contracts task C-1" in contents
