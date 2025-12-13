# Task: Create Comprehensive Unit Tests for Enhanced Master Orchestrator

## Objective
Create a complete suite of unit tests for the newly enhanced Master Prompt Orchestrator in `automation/master_prompt_orchestrator.py`. The tests must validate all new functionality added in the December 2025 enhancement while maintaining 100% focus on the orchestrator module only.

## Scope Boundaries - CRITICAL
**IN SCOPE:**
- Testing `RepositoryAnalyzer` class and all its methods
- Testing `PromptQualityScorer` class and scoring logic
- Testing prompt template matching and selection
- Testing deduplication mechanisms (hash-based and semantic similarity)
- Testing diversity enforcement logic
- Testing metadata generation for prompts
- Testing adaptive complexity adjustment logic
- Testing integration points with `FeedbackAnalyzer` (mock the analyzer, test the integration)
- Testing quality validation and filtering workflow

**OUT OF SCOPE:**
- Do NOT modify `master_prompt_orchestrator.py` itself (only test it)
- Do NOT test `FeedbackAnalyzer` internals (mock it and test integration only)
- Do NOT test `CrossRepoTodoIngestionService` internals (mock it)
- Do NOT test LLM API calls (mock the OpenAI client)
- Do NOT create new features or enhancements
- Do NOT modify existing production code outside of tests
- Do NOT test UI components or panel automation

## Context
The Master Orchestrator was enhanced on December 12, 2025 with:
1. Repository analysis for detecting language, architecture, patterns, conventions
2. Prompt quality scoring system (4 criteria: clarity, actionability, context, historical performance)
3. Template-based prompt generation (5 templates: bug_fix, feature, refactor, testing, documentation)
4. Deduplication (exact hash + semantic similarity at 70% threshold)
5. Diversity enforcement across task types
6. Adaptive complexity based on agent success rates
7. Comprehensive metadata tracking

Reference documentation: `docs/MASTER_ORCHESTRATOR_ENHANCEMENT.md`

## Requirements

### 1. Test File Structure
Create `tests/test_master_prompt_orchestrator_enhanced.py` with these test classes:
- `TestRepositoryAnalyzer` - Test repository analysis functionality
- `TestPromptQualityScorer` - Test quality scoring system
- `TestPromptTemplates` - Test template matching and usage
- `TestDeduplication` - Test duplicate and similarity detection
- `TestDiversityEnforcement` - Test task type balancing
- `TestAdaptiveComplexity` - Test complexity adjustment logic
- `TestMetadataGeneration` - Test metadata creation
- `TestIntegrationWorkflow` - Test end-to-end prompt generation with mocks

### 2. RepositoryAnalyzer Tests
**Required test cases:**
```python
def test_analyze_repository_detects_python():
    """Should detect Python as primary language from .py files"""
    
def test_analyze_repository_detects_architecture_microservices():
    """Should detect microservices architecture from doc keywords"""
    
def test_analyze_repository_detects_architecture_monolithic():
    """Should detect monolithic architecture from doc keywords"""
    
def test_extract_code_patterns_finds_singleton():
    """Should identify singleton pattern from documentation"""
    
def test_extract_code_patterns_finds_factory():
    """Should identify factory pattern from documentation"""
    
def test_extract_conventions_finds_pep8():
    """Should detect PEP 8 style guide from documentation"""
    
def test_extract_conventions_finds_naming_snake_case():
    """Should detect snake_case naming convention"""
    
def test_extract_dependencies_from_requirements_txt():
    """Should parse dependencies from requirements.txt"""
    
def test_analyze_repository_caches_results():
    """Should cache analysis results and reuse for same repo"""
    
def test_analyze_repository_handles_missing_dirs():
    """Should handle non-existent directories gracefully"""
```

### 3. PromptQualityScorer Tests
**Required test cases:**
```python
def test_score_prompt_with_high_quality():
    """Should score well-structured, clear prompt highly (>0.7)"""
    
def test_score_prompt_with_low_quality():
    """Should score vague, unclear prompt lowly (<0.4)"""
    
def test_score_clarity_rewards_action_verbs():
    """Should increase clarity score for specific action verbs"""
    
def test_score_clarity_penalizes_vague_language():
    """Should decrease clarity score for vague terms"""
    
def test_score_actionability_rewards_deliverables():
    """Should increase score when deliverables are specified"""
    
def test_score_context_rewards_context_sections():
    """Should increase score when context is provided"""
    
def test_score_historical_performance_uses_feedback():
    """Should use feedback analyzer data for historical scoring"""
    
def test_score_historical_performance_uses_template_success_rate():
    """Should use template success rate when no feedback data"""
    
def test_score_prompt_clamps_to_zero_one_range():
    """Should ensure score is always between 0.0 and 1.0"""
```

### 4. Template Matching Tests
**Required test cases:**
```python
def test_classify_task_type_bug_fix():
    """Should classify bug-related prompts as 'bug_fix'"""
    
def test_classify_task_type_feature():
    """Should classify feature prompts as 'feature'"""
    
def test_classify_task_type_refactor():
    """Should classify refactoring prompts as 'refactor'"""
    
def test_classify_task_type_testing():
    """Should classify test-related prompts as 'testing'"""
    
def test_classify_task_type_documentation():
    """Should classify doc prompts as 'documentation'"""
    
def test_identify_template_match_returns_correct_template():
    """Should match prompt to appropriate template by task type"""
    
def test_identify_template_match_returns_none_when_disabled():
    """Should return None when templates are disabled"""
```

### 5. Deduplication Tests
**Required test cases:**
```python
def test_deduplicate_removes_exact_duplicates():
    """Should remove prompts with identical hashes"""
    
def test_deduplicate_keeps_unique_prompts():
    """Should keep prompts with different hashes"""
    
def test_is_similar_detects_high_overlap():
    """Should detect prompts with >70% word overlap as similar"""
    
def test_is_similar_allows_low_overlap():
    """Should allow prompts with <70% word overlap"""
    
def test_deduplicate_logs_removed_count():
    """Should log number of duplicates removed"""
```

### 6. Diversity Enforcement Tests
**Required test cases:**
```python
def test_ensure_diversity_limits_per_task_type():
    """Should limit prompts per task type to max_per_type"""
    
def test_ensure_diversity_selects_highest_quality():
    """Should select highest quality prompts within each type"""
    
def test_ensure_diversity_balances_task_types():
    """Should ensure balanced distribution across types"""
```

### 7. Adaptive Complexity Tests
**Required test cases:**
```python
def test_adjust_complexity_simplifies_when_agents_struggling():
    """Should simplify prompts when success rate <50%"""
    
def test_adjust_complexity_maintains_when_agents_succeeding():
    """Should maintain complexity when success rate >80%"""
    
def test_adjust_complexity_adds_simplification_note():
    """Should add step-by-step guidance when simplifying"""
    
def test_adjust_complexity_updates_metadata():
    """Should update metadata with adaptive_complexity_level"""
```

### 8. Metadata Generation Tests
**Required test cases:**
```python
def test_generate_prompt_metadata_creates_all_fields():
    """Should create metadata with all required fields"""
    
def test_generate_prompt_metadata_computes_hash():
    """Should compute correct prompt hash"""
    
def test_generate_prompt_metadata_classifies_task_type():
    """Should correctly classify task type"""
    
def test_generate_prompt_metadata_estimates_difficulty():
    """Should estimate difficulty as simple/moderate/complex"""
    
def test_estimate_difficulty_simple_for_short_prompts():
    """Should classify short prompts (<100 words) as simple"""
    
def test_estimate_difficulty_complex_for_long_prompts():
    """Should classify long prompts (>300 words) as complex"""
```

### 9. Integration Tests
**Required test cases:**
```python
def test_generate_prompt_batch_end_to_end():
    """Should generate complete prompt batch with all enhancements"""
    
def test_generate_prompt_batch_filters_low_quality():
    """Should filter prompts below quality threshold"""
    
def test_generate_prompt_batch_applies_feedback_filtering():
    """Should filter prompts with poor historical performance"""
    
def test_generate_prompt_batch_writes_metadata_file():
    """Should write metadata JSON file alongside prompts"""
    
def test_generate_prompt_batch_updates_manifest():
    """Should append to manifest.jsonl with quality stats"""
```

## Technical Requirements

### Test Framework
- Use `pytest` as the test framework
- Use `unittest.mock` for mocking dependencies
- Create fixtures for common test data in `conftest.py` if needed

### Mocking Strategy
```python
# Mock FeedbackAnalyzer
@patch('automation.master_prompt_orchestrator.get_feedback_analyzer')
def test_example(mock_get_analyzer):
    mock_analyzer = MagicMock()
    mock_analyzer.analyze_feedback.return_value = FeedbackInsights(...)
    mock_get_analyzer.return_value = mock_analyzer
    # Test code here

# Mock OpenAI client
@patch('automation.master_prompt_orchestrator.OpenAIClient')
def test_example(mock_client_class):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.output = [MagicMock(type="text", text="Generated prompts...")]
    mock_client.responses.create.return_value = mock_response
    # Test code here
```

### Test Data
Create realistic test data that mimics production:
- Sample repository documentation (markdown content)
- Sample prompts (good and bad quality)
- Sample feedback metrics
- Sample todo items with dependencies

### Code Coverage
- Target: >90% code coverage for new enhancement code
- Use `pytest-cov` to measure coverage
- Run: `pytest tests/test_master_prompt_orchestrator_enhanced.py --cov=automation.master_prompt_orchestrator --cov-report=term-missing`

## Success Criteria

### All tests must:
1. ✅ Pass with `pytest tests/test_master_prompt_orchestrator_enhanced.py -v`
2. ✅ Achieve >90% coverage of enhanced orchestrator code
3. ✅ Use appropriate mocks (no actual API calls, no file I/O unless testing file operations)
4. ✅ Have clear, descriptive test names
5. ✅ Include docstrings explaining what is tested
6. ✅ Be independent (can run in any order)
7. ✅ Complete in <5 seconds total runtime

### Deliverables:
1. `tests/test_master_prompt_orchestrator_enhanced.py` - Main test file
2. Sample test data files in `tests/fixtures/` if needed
3. Brief summary in test file header documenting coverage

## Constraints

### Time Limit
Complete within 2-3 hours of focused work.

### No Scope Creep
- Do NOT refactor production code
- Do NOT add new features
- Do NOT test modules outside master_prompt_orchestrator.py
- Do NOT modify documentation (it's already complete)

### Code Style
- Follow existing test patterns in `tests/` directory
- Use consistent naming: `test_<class>_<method>_<scenario>`
- Keep tests focused (one assertion per test when possible)

## Example Test Structure

```python
"""
Comprehensive unit tests for enhanced Master Prompt Orchestrator.

Tests cover:
- Repository analysis (language, architecture, patterns, conventions)
- Prompt quality scoring (clarity, actionability, context, historical)
- Template matching and selection
- Deduplication (hash-based and semantic)
- Diversity enforcement
- Adaptive complexity adjustment
- Metadata generation
- End-to-end integration workflow

Coverage target: >90%
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
from automation.master_prompt_orchestrator import (
    RepositoryAnalyzer,
    PromptQualityScorer,
    MasterPromptOrchestrator,
    PromptMetadata,
    PromptTemplate,
    RepositoryAnalysis,
    DocumentSlice,
)
from automation.feedback_analyzer import FeedbackInsights, PromptPerformance


class TestRepositoryAnalyzer:
    """Test repository analysis functionality."""
    
    def test_analyze_repository_detects_python(self):
        """Should detect Python as primary language from .py files."""
        # Arrange
        analyzer = RepositoryAnalyzer()
        docs = [DocumentSlice(...)]  # Sample docs
        repo_dirs = [Path("./test_repo")]
        
        # Mock file system
        with patch.object(Path, 'rglob') as mock_rglob:
            mock_rglob.return_value = [Path("test.py"), Path("main.py")]
            
            # Act
            result = analyzer.analyze_repository("test_repo", docs, repo_dirs)
            
            # Assert
            assert result.primary_language == "py"


# ... Continue with all other test classes
```

## Reference Files
- **Main file to test**: `automation/master_prompt_orchestrator.py`
- **Documentation**: `docs/MASTER_ORCHESTRATOR_ENHANCEMENT.md`
- **Related modules** (mock these):
  - `automation/feedback_analyzer.py`
  - `automation/cross_repo_todo_ingestion.py`
  - `automation/metrics.py`

## Questions to Consider
- Are all edge cases covered (empty inputs, missing files, invalid data)?
- Do tests verify error handling gracefully?
- Are all new dataclasses (PromptMetadata, RepositoryAnalysis) tested?
- Do integration tests cover the full workflow?

## Final Checklist
Before submitting:
- [ ] All tests pass
- [ ] Coverage >90% for enhanced code
- [ ] No actual file I/O or API calls (all mocked)
- [ ] Tests run in <5 seconds
- [ ] No production code modified
- [ ] Test names are clear and descriptive
- [ ] Docstrings explain what each test validates

---
**Agent Assignment**: Codex Mini (moderate complexity, clear requirements, systematic testing)
**Estimated Time**: 2-3 hours
**Priority**: High (validates critical enhancement)
**Dependencies**: None (enhancement already completed)
