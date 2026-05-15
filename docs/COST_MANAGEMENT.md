# Cost Management and Budgeting Guide

This guide explains how the desktop agent automation system tracks model usage costs, how pricing is configured, and how to set budgets and alerts.

## 1. Cost Tracking Overview

The system uses `automation.cost_tracker.CostTracker` to:

- Record per-call token usage and estimated dollar cost.
- Track separate counts for text and vision events.
- Persist records to a JSON Lines file (`logs/cost_metrics.jsonl`).
- Provide session-level aggregates and budget checks.

The cost tracker is designed to be:

- **Stateless across restarts** for historical reporting (via log file).
- **Stateful per process** for quick session summaries.

---

## 2. Pricing Configuration

### 2.1 Default model rates

`CostTracker` ships with conservative placeholder rates in `DEFAULT_MODEL_RATES`:

- `gpt-4o-mini`: input/output per 1k tokens.
- `gpt-4o`: input/output per 1k tokens.
- `gpt-4-turbo`: input/output per 1k tokens.

These are **approximate** and should be overridden to match your organization’s pricing.

### 2.2 Overriding via environment variables

Use `COST_TRACKER_MODEL_RATES` to provide a JSON object mapping model names to rates:

```powershell
$env:COST_TRACKER_MODEL_RATES = '{
  "gpt-4.1": {"input_per_1k": 0.005, "output_per_1k": 0.015},
  "gpt-4o-mini": {"input_per_1k": 0.00045, "output_per_1k": 0.0009}
}'
```

Notes:

- Keys are normalized to lowercase internally.
- Each object must contain `input_per_1k` and `output_per_1k` numbers.

### 2.3 Vision pricing

Vision/image usage uses `COST_TRACKER_VISION_COST_PER_IMAGE`:

```powershell
$env:COST_TRACKER_VISION_COST_PER_IMAGE = "0.02"  # USD per image
```

If not set, `DEFAULT_VISION_COST_PER_IMAGE` (currently `0.02`) is used.

### 2.4 Monthly pricing verification

Use the repo-maintained verification script to compare `DEFAULT_MODEL_RATES` against the latest published OpenAI pricing and save an auditable report set under `logs/pricing_checks/`.

Canonical monthly command:

```powershell
master --run pricing-verification
```

Direct script fallback:

```powershell
python scripts/verify_pricing.py --monthly-check
```

What the monthly command does:

- Compares current `DEFAULT_MODEL_RATES` against the latest pricing source it can parse.
- Writes timestamped JSON and Markdown reports to `logs/pricing_checks/`.
- Compares against the most recent compatible saved report, if one exists.
- Prints a console summary with rate deltas and per-1M-token impact.

Operator follow-up:

1. Review the console output and saved Markdown report.
2. If rates changed, update `automation/cost_tracker.py` and any `COST_TRACKER_MODEL_RATES` overrides used in deployment.
3. Re-run the same monthly command to confirm the baseline is current.
4. Commit the code change and the new `logs/pricing_checks/` report artifacts together.

---

## 3. Cost Calculation Methodology

For each recorded event, `CostTracker` computes:

- `$input_tokens` and `$output_tokens` from the model’s `usage` object.
- Fetches a `TokenRate` for the model (best prefix match on `model.lower()`).
- Calculates token cost:

$$
\text{token\_cost} = \frac{\text{input\_tokens}}{1000} \cdot \text{input\_per\_1k} + \frac{\text{output\_tokens}}{1000} \cdot \text{output\_per\_1k}
$$

- For vision calls, adds:

$$
\text{vision\_cost} = \text{image\_count} \cdot \text{vision\_cost\_per\_image}
$$

- Total cost:

$$
\text{total\_cost} = \text{token\_cost} + \text{vision\_cost}
$$

Values are rounded to 6 decimal places when persisted.

---

## 4. Log Format and Location

By default, records are written to:

- `logs/cost_metrics.jsonl` (see `DEFAULT_COST_METRICS_PATH`).

Each line is a JSON object with fields:

- `timestamp`: ISO 8601 string.
- `source`: logical caller (e.g., `master_orchestrator`, `desktop_auto_allow_agent`).
- `event`: event name (e.g., `panel_followup`, `seed_prompt`, `copilot_status`).
- `model`: model identifier used.
- `input_tokens`, `output_tokens`.
- `vision_images`.
- `token_cost`, `vision_cost`, `total_cost`.
- `details`: arbitrary metadata, typically contains the original `usage` structure.

Example line:

```json
{
  "timestamp": "2025-12-11T14:05:20.123456",
  "source": "master_orchestrator",
  "event": "panel_followup",
  "model": "gpt-4.1",
  "input_tokens": 1400,
  "output_tokens": 800,
  "vision_images": 0,
  "token_cost": 0.014,
  "vision_cost": 0.0,
  "total_cost": 0.014,
  "details": {"usage": {"input_tokens": 1400, "output_tokens": 800}}
}
```

---

## 5. Budgets and Alert Thresholds

### 5.1 Budget environment variables

Use the following variables to set soft budget limits:

```powershell
$env:COST_TRACKER_DAILY_LIMIT = "10.0"    # USD
$env:COST_TRACKER_WEEKLY_LIMIT = "50.0"   # USD
$env:COST_TRACKER_MONTHLY_LIMIT = "200.0" # USD
```

`CostTracker.get_budget_limits()` reads these values and falls back to the same defaults if they are not set.

### 5.2 Alert logic

`CostTracker.check_budget_alerts()` calculates:

- `daily_cost`: total `total_cost` in the last 1 day.
- `weekly_cost`: last 7 days.
- `monthly_cost`: last 30 days.

For each period:

- If `cost >= limit`: emits `... BUDGET EXCEEDED`.
- Else if `cost >= 0.8 * limit`: emits `... BUDGET WARNING`.

Example usage:

```python
from automation.cost_tracker import get_cost_tracker

tracker = get_cost_tracker()
alerts = tracker.check_budget_alerts()
for msg in alerts:
    print(msg)
```

You can wire these alerts into your logging, notifications, or dashboards.

---

## 6. Estimating and Optimizing Costs

### 6.1 Hypothetical estimates

Use `CostTracker.estimate_cost` to evaluate a planned call without recording it:

```python
from automation.cost_tracker import get_cost_tracker

tracker = get_cost_tracker()
cost = tracker.estimate_cost(
    model="gpt-4.1",
    input_tokens=2000,
    output_tokens=1000,
    image_count=0,
)
print(f"Estimated cost: ${cost:.4f}")
```

### 6.2 Aggregates for a session

```python
from automation.cost_tracker import get_cost_tracker

tracker = get_cost_tracker()
print(tracker.get_session_totals())
# {"text_events": ..., "vision_events": ..., "input_tokens": ..., ...}
```

Call `reset_session_totals()` to start a new accounting window within the same process.

### 6.3 Optimization strategies

- **Use cheaper models where appropriate**
  - Map non-critical tasks (logging, summarization, routing) to `gpt-4o-mini` or similar.
- **Reduce prompt and response sizes**
  - Trim context documents before sending.
  - Use summaries instead of full histories when possible.
- **Batch related work**
  - Whenever possible, ask for multiple related actions in a single call (within reason) instead of many small calls.
- **Tighten follow-up criteria**
  - Adjust panel follow-up logic so that only genuinely useful follow-ups are sent.

---

## 7. Operational Playbooks

### 7.1 Daily cost review

1. Run a simple budget check script:

```powershell
python - << 'EOF'
  from automation.cost_tracker import get_cost_tracker

  tracker = get_cost_tracker()
  print(tracker.check_budget_alerts())
  EOF
```

### 7.2 Monthly pricing review

Run the standard pricing verification workflow:

```powershell
master --run pricing-verification
```

Direct script fallback:

```powershell
python scripts/verify_pricing.py --monthly-check
```

Expected outputs:

- A readable console summary of changed/default/new/missing model rates.
- Timestamped JSON and Markdown reports in `logs/pricing_checks/`.
- A previous-report comparison when a compatible prior report exists.

If pricing changed:

1. Update `DEFAULT_MODEL_RATES` in `automation/cost_tracker.py`.
2. Update any deployment-time `COST_TRACKER_MODEL_RATES` override to match.
3. Re-run the monthly check and commit the code and report artifacts together.

4. If daily budget warnings appear, consider temporarily:
   - Lowering `MAX_ALLOWS_PER_HOUR`.
   - Turning off non-essential workflows.

### 7.3 Investigating cost spikes

1. Filter `logs/cost_metrics.jsonl` by timestamp range.
2. Group by `source` and `event` to find the noisiest workflows.
3. Cross-reference with `automation/metrics.json` and `automation/allow_metrics.jsonl` for correlation with Allow patterns and prompt seeding.

### 7.4 Long-term archiving

- Periodically rotate or compress `logs/cost_metrics.jsonl` to avoid unbounded growth.
- Keep per-month snapshots for audit and forecasting.
