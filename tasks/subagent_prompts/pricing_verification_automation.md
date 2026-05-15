# Task: Enhance Pricing Verification Automation

## Objective
Enhance the existing `scripts/verify_pricing.py` script to support automated monthly pricing checks with diff detection, alerting, and report generation. Create a system that makes it easy to comply with the recurring reminder in `docs/Todo.md` to check OpenAI pricing on the first business day of each month.

## Scope Boundaries - CRITICAL
**IN SCOPE:**
- Enhance `scripts/verify_pricing.py` with new features
- Add automated diff detection between current and previous pricing
- Generate pricing change reports saved to `logs/pricing_checks/`
- Add alerting mechanism for pricing changes detected
- Create summary report format showing old vs new prices
- Add `--auto-commit` flag to optionally commit pricing changes
- Improve output formatting for better readability
- Add `--notify` flag for alerting (email/webhook placeholder)

**OUT OF SCOPE:**
- Do NOT modify `automation/cost_tracker.py` (only read DEFAULT_MODEL_RATES)
- Do NOT change how costs are calculated (only verification)
- Do NOT add new pricing sources beyond OpenAI
- Do NOT create a scheduler (manual monthly run is fine)
- Do NOT build a web UI or dashboard
- Do NOT modify `.env` file handling
- Do NOT add dependencies beyond standard library + existing requirements
- Do NOT create new modules (enhance existing script only)

## Context

### Current State
The existing `scripts/verify_pricing.py` script:
- Compares hardcoded DEFAULT_MODEL_RATES in `automation/cost_tracker.py` with OpenAI's API
- Outputs differences to console
- Requires manual review and updating of code

### Problem
From `docs/Todo.md`:
```markdown
## Recurring Reminders
- [ ] First business day of every month: run `python scripts/verify_pricing.py --monthly-check`, 
      review diffs against `DEFAULT_MODEL_RATES`, and commit any adjustments with notes 
      in `logs/pricing_checks/`.
```

Currently this is a manual, tedious process. We need automation to:
1. Detect pricing changes automatically
2. Generate historical reports
3. Make it easy to commit changes with proper notes
4. Alert when changes are detected

### Reference Files
- **Script to enhance**: `scripts/verify_pricing.py`
- **Pricing source**: `automation/cost_tracker.py` (DEFAULT_MODEL_RATES dict)
- **Output directory**: `logs/pricing_checks/` (create if not exists)

## Requirements

### 1. Enhanced CLI Interface

Add these new flags to `verify_pricing.py`:

```python
parser.add_argument(
    '--json',
    action='store_true',
    help='Output results in JSON format'
)

parser.add_argument(
    '--save-report',
    action='store_true',
    help='Save pricing check report to logs/pricing_checks/'
)

parser.add_argument(
    '--auto-commit',
    action='store_true',
    help='Automatically commit pricing changes to git (requires --save-report)'
)

parser.add_argument(
    '--notify',
    choices=['console', 'email', 'webhook'],
    default='console',
    help='Notification method for pricing changes detected'
)

parser.add_argument(
    '--compare-previous',
    action='store_true',
    help='Compare against previous pricing check report'
)
```

### 2. Diff Detection

Implement comparison logic:

```python
def compare_pricing(current_rates: dict, api_rates: dict) -> dict:
    """
    Compare current hardcoded rates with API rates.
    
    Returns:
        {
            'unchanged': [list of models with same price],
            'increased': [{'model': name, 'old': price, 'new': price, 'change_pct': X}],
            'decreased': [{'model': name, 'old': price, 'new': price, 'change_pct': X}],
            'new_models': [list of models in API but not in code],
            'deprecated': [list of models in code but not in API]
        }
    """
    # Implementation here
```

**Requirements:**
- Calculate percentage change for each model
- Identify new models (in API, not in code)
- Identify deprecated models (in code, not in API)
- Handle both input/output token pricing separately
- Handle vision pricing (image tokens)

### 3. Report Generation

Generate reports in `logs/pricing_checks/`:

**File naming**: `pricing_check_YYYY-MM-DDTHHMMSSZ.json`

**Report structure**:
```json
{
  "check_date": "2025-12-13T10:30:00Z",
  "checker_version": "1.1.0",
  "api_source": "OpenAI API v1",
  "comparison": {
    "unchanged_count": 5,
    "increased_count": 2,
    "decreased_count": 0,
    "new_models_count": 1,
    "deprecated_count": 0
  },
  "changes": {
    "increased": [
      {
        "model": "gpt-4o",
        "rate_type": "input",
        "old_price": 0.0025,
        "new_price": 0.0030,
        "change_pct": 20.0,
        "change_per_1m_tokens": 0.5
      }
    ],
    "decreased": [],
    "new_models": ["gpt-5-mini"],
    "deprecated": []
  },
  "full_pricing": {
    "current_code": { /* DEFAULT_MODEL_RATES dict */ },
    "api_latest": { /* API response */ }
  },
  "recommendations": [
    "Update cost_tracker.py: gpt-4o input rate 0.0025 → 0.0030",
    "Review usage of gpt-4o due to 20% price increase",
    "New model available: gpt-5-mini - consider testing"
  ]
}
```

**Additional report**: `pricing_check_YYYY-MM-DD.md` (human-readable markdown)

```markdown
# OpenAI Pricing Check - December 13, 2025

## Summary
- ✅ 5 models unchanged
- ⚠️ 2 models increased
- ✨ 1 new model available
- 📉 0 models decreased
- 🗑️ 0 models deprecated

## Price Increases ⚠️

### gpt-4o
- **Input tokens**: $0.0025 → $0.0030 (+20.0%)
  - Impact: +$500 per 1M tokens
- **Recommendation**: Review usage, consider alternatives

### gpt-4-turbo
- **Output tokens**: $0.0100 → $0.0120 (+20.0%)
  - Impact: +$2000 per 1M tokens
- **Recommendation**: High-cost model, evaluate necessity

## New Models ✨

### gpt-5-mini
- Newly available in OpenAI API
- Pricing: Input $0.0001, Output $0.0002
- Recommendation: Test for cost optimization

## Recommendations
1. Update `automation/cost_tracker.py` DEFAULT_MODEL_RATES
2. Review active usage of price-increased models
3. Test new models for potential cost savings
4. Run cost analysis on recent usage with new rates

## Next Steps
```bash
# Update cost tracker
# Edit automation/cost_tracker.py and update DEFAULT_MODEL_RATES

# Commit changes
git add automation/cost_tracker.py logs/pricing_checks/
git commit -m "chore: Update OpenAI pricing (Dec 2025 check)"

# Re-run verification
python scripts/verify_pricing.py
```

---
Generated by verify_pricing.py v1.1.0
```

### 4. Comparison with Previous Report

Implement historical comparison:

```python
def load_previous_report(reports_dir: Path) -> Optional[dict]:
    """Load most recent previous pricing check report."""
    # Find latest report (by date in filename)
    # Parse JSON
    # Return report dict or None if no previous report

def compare_with_previous(current_report: dict, previous_report: dict) -> dict:
    """
    Compare current check with previous check to detect trends.
    
    Returns:
        {
            'price_trend': 'increasing' | 'decreasing' | 'stable',
            'models_that_changed_again': [...],
            'cumulative_increase_since_previous': X.XX,
            'time_since_last_check': 'X days'
        }
    """
```

### 5. Alerting System

Implement notification mechanism:

```python
def notify_pricing_changes(changes: dict, method: str):
    """
    Send notification about pricing changes.
    
    Args:
        changes: Dict of pricing changes from compare_pricing()
        method: 'console' | 'email' | 'webhook'
    """
    if method == 'console':
        # Print formatted alert to console
        print_alert(changes)
    elif method == 'email':
        # Placeholder: Show how email would be sent
        print("Email notification would be sent to: [configure in .env]")
        print_email_preview(changes)
    elif method == 'webhook':
        # Placeholder: Show webhook payload
        print("Webhook would POST to: [configure in .env]")
        print_webhook_payload(changes)

def print_alert(changes: dict):
    """Print colorful console alert for pricing changes."""
    # Use colors: red for increases, green for decreases, yellow for new
    # Example:
    # 🚨 PRICING ALERT: 2 models increased, 1 new model available
    # ⚠️  gpt-4o input: $0.0025 → $0.0030 (+20%)
    # ✨ New: gpt-5-mini
```

### 6. Auto-Commit Feature

Implement git automation:

```python
def auto_commit_pricing_changes(report_path: Path, changes: dict):
    """
    Automatically commit pricing report to git.
    
    Args:
        report_path: Path to generated report
        changes: Pricing changes dict
    
    Raises:
        GitError: If git commands fail
    """
    # Check if git is available
    # Check if repo is clean (warn if not)
    # Add report files: logs/pricing_checks/*.json and *.md
    # Create commit with message:
    #   "chore: Pricing check YYYY-MM-DD - X changes detected"
    # Include summary in commit message
    # Push optional (require --push flag)
```

**Commit message format**:
```
chore: Pricing check 2025-12-13 - 2 increases, 1 new model

Changes detected:
- gpt-4o input: +20%
- gpt-4-turbo output: +20%
- New model: gpt-5-mini

Reports: logs/pricing_checks/pricing_check_2025-12-13.*
```

### 7. Output Formatting

Improve console output:

**Before changes:**
```
Model: gpt-4o
Current: 0.0025
API: 0.0030
Difference: 0.0005
```

**After changes:**
```
╔═══════════════════════════════════════════════════════════╗
║           OpenAI Pricing Verification Report             ║
║                  December 13, 2025                        ║
╚═══════════════════════════════════════════════════════════╝

📊 Summary:
   ✅ 5 unchanged
   ⚠️  2 increased (+20% avg)
   📉 0 decreased
   ✨ 1 new model
   🗑️  0 deprecated

⚠️  Price Increases:

   gpt-4o (input tokens)
   ├─ Old: $2.50 per 1M tokens
   ├─ New: $3.00 per 1M tokens
   ├─ Change: +20.0% (+$500 per 1M)
   └─ Impact: Medium usage model

   gpt-4-turbo (output tokens)
   ├─ Old: $10.00 per 1M tokens
   ├─ New: $12.00 per 1M tokens
   ├─ Change: +20.0% (+$2000 per 1M)
   └─ Impact: High usage model

✨ New Models:

   gpt-5-mini
   ├─ Input: $0.10 per 1M tokens
   ├─ Output: $0.20 per 1M tokens
   └─ Note: Evaluate for cost savings

📝 Action Items:
   1. Update DEFAULT_MODEL_RATES in automation/cost_tracker.py
   2. Review usage of price-increased models
   3. Test new models
   4. Re-run cost estimates with new pricing

💾 Reports saved to:
   - logs/pricing_checks/pricing_check_2025-12-13.json
   - logs/pricing_checks/pricing_check_2025-12-13.md

🔗 Next: Review reports and update code as needed
```

## Technical Requirements

### Error Handling
```python
# Handle API failures gracefully
try:
    api_rates = fetch_openai_pricing()
except requests.RequestException as e:
    print(f"❌ Failed to fetch API pricing: {e}")
    print("💡 Using cached rates from previous check...")
    api_rates = load_previous_report()['full_pricing']['api_latest']

# Handle missing previous reports
if not previous_report:
    print("ℹ️  No previous pricing check found. This is the baseline.")

# Handle git errors
if git_not_available():
    print("⚠️  Git not available. Skipping auto-commit.")
    print("💡 Manually commit: git add logs/pricing_checks/ && git commit")
```

### Testing
Create test cases for:
1. Diff detection with mock pricing data
2. Report generation
3. Previous report comparison
4. Alert formatting
5. Git commit (with dry-run mode)

**Test data**: Create fixtures in `tests/fixtures/pricing/`

### Dependencies
Use only existing requirements:
- `requests` (already installed)
- `openai` (already installed)
- Standard library: `json`, `datetime`, `pathlib`, `subprocess` (for git)

**No new dependencies required.**

## Success Criteria

### The enhanced script must:
1. ✅ Support all new CLI flags (--json, --save-report, --auto-commit, etc.)
2. ✅ Accurately detect pricing differences
3. ✅ Generate both JSON and Markdown reports
4. ✅ Save reports to `logs/pricing_checks/` with timestamped names
5. ✅ Compare with previous reports when requested
6. ✅ Show formatted console output with colors/symbols
7. ✅ Support auto-commit with proper git messages
8. ✅ Gracefully handle errors (API failures, git issues)
9. ✅ Maintain backward compatibility (existing usage still works)
10. ✅ Include help text for all new options

### Deliverables:
1. Enhanced `scripts/verify_pricing.py`
2. Example reports in `logs/pricing_checks/` (for documentation)
3. Updated script docstring documenting new features
4. Brief usage examples in script header comments

## Usage Examples

```bash
# Basic check (existing functionality)
python scripts/verify_pricing.py

# Generate and save reports
python scripts/verify_pricing.py --save-report

# Compare with previous check
python scripts/verify_pricing.py --save-report --compare-previous

# Auto-commit changes
python scripts/verify_pricing.py --save-report --auto-commit

# JSON output for automation
python scripts/verify_pricing.py --monthly-check

# Get alerts via email (when configured)
python scripts/verify_pricing.py --save-report --notify email

# Monthly workflow (recommended)
python scripts/verify_pricing.py --save-report --compare-previous --notify console
# Review output, then:
python scripts/verify_pricing.py --save-report --auto-commit
```

## Constraints

### Time Limit
Complete within 2-3 hours of focused work.

### No Scope Creep
- Do NOT modify cost_tracker.py logic
- Do NOT add web UI or dashboard
- Do NOT create schedulers (cron, Windows Task Scheduler)
- Do NOT add external notification services beyond placeholders
- Do NOT change pricing calculation methods
- Focus on verification and reporting only

### Code Style
- Follow existing script patterns
- Use type hints for new functions
- Add docstrings for all new functions
- Keep backward compatibility
- Use consistent formatting with existing code

## Example Function Signatures

```python
def compare_pricing(
    current_rates: Dict[str, Dict[str, float]],
    api_rates: Dict[str, Dict[str, float]]
) -> Dict[str, Any]:
    """Compare current rates with API rates and categorize changes."""
    pass

def generate_json_report(
    comparison: Dict[str, Any],
    output_path: Path
) -> None:
    """Generate JSON pricing report."""
    pass

def generate_markdown_report(
    comparison: Dict[str, Any],
    output_path: Path
) -> None:
    """Generate human-readable Markdown report."""
    pass

def format_console_output(
    comparison: Dict[str, Any],
    use_colors: bool = True
) -> str:
    """Format comparison results for console display."""
    pass

def auto_commit_reports(
    report_paths: List[Path],
    comparison: Dict[str, Any]
) -> bool:
    """Commit pricing reports to git. Returns True if successful."""
    pass
```

## Reference Files
- **Main script**: `scripts/verify_pricing.py`
- **Pricing source**: `automation/cost_tracker.py` (DEFAULT_MODEL_RATES)
- **Output directory**: `logs/pricing_checks/` (will be created)
- **Todo reference**: `docs/Todo.md` (recurring reminder section)

## Final Checklist
Before submitting:
- [ ] All CLI flags work correctly
- [ ] JSON and Markdown reports generated properly
- [ ] Console output is well-formatted
- [ ] Diff detection is accurate
- [ ] Previous report comparison works
- [ ] Auto-commit feature tested (dry-run)
- [ ] Error handling for API failures
- [ ] Error handling for git issues
- [ ] Backward compatible (old usage works)
- [ ] Help text is clear and complete
- [ ] Example reports in logs/pricing_checks/
- [ ] Code follows existing style
- [ ] No new dependencies added

---
**Agent Assignment**: Codex Mini (moderate complexity, well-defined enhancement, clear requirements)
**Estimated Time**: 2-3 hours
**Priority**: Medium (supports recurring monthly task)
**Dependencies**: None
