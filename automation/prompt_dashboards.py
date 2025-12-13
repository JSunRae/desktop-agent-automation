"""Dashboard renderer for visualizing prompt quality trends."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automation.feedback_analyzer import get_feedback_analyzer
from automation.metrics import get_metrics_tracker


def render_prompt_dashboard(output_path: Optional[Path] = None) -> Path:
    analyzer = get_feedback_analyzer()
    guidance = analyzer.get_guidance()
    metrics = get_metrics_tracker()

    success_trend = _build_success_trend(metrics.response_feedback_metrics)
    pattern_trend = _build_pattern_trend(metrics.response_feedback_metrics, guidance.prompt_blocklist, guidance.prompt_whitelist)
    top_prompts = _build_prompt_summary(guidance.prompt_performance)

    html = _build_dashboard_html(success_trend, pattern_trend, top_prompts, guidance.prompt_blocklist, guidance.prompt_whitelist)
    target = Path(output_path) if output_path else Path("logs") / "prompt_dashboard.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def _build_success_trend(metrics) -> Dict[str, List]:
    totals: Dict[str, int] = defaultdict(int)
    successes: Dict[str, int] = defaultdict(int)
    for metric in metrics:
        stamp = metric.timestamp.isoformat() if isinstance(metric.timestamp, datetime) else metric.timestamp
        date_key = stamp[:10]
        totals[date_key] += 1
        if metric.response_category.value == "completed":
            successes[date_key] += 1
    dates = sorted(totals.keys())
    values = [(successes[d] / totals[d]) if totals[d] else 0.0 for d in dates]
    return {"labels": dates, "values": values}


def _build_pattern_trend(metrics, blocklist: List[str], whitelist: List[str]) -> Dict[str, List]:
    block_counts: Dict[str, int] = defaultdict(int)
    white_counts: Dict[str, int] = defaultdict(int)
    for metric in metrics:
        text = (metric.prompt_preview or "").lower()
        stamp = metric.timestamp.isoformat() if isinstance(metric.timestamp, datetime) else metric.timestamp
        date_key = stamp[:10]
        if any(pattern.lower() in text for pattern in blocklist):
            block_counts[date_key] += 1
        if any(pattern.lower() in text for pattern in whitelist):
            white_counts[date_key] += 1
    labels = sorted(set(block_counts.keys()) | set(white_counts.keys()))
    return {
        "labels": labels,
        "blocklist": [block_counts.get(label, 0) for label in labels],
        "whitelist": [white_counts.get(label, 0) for label in labels],
    }


def _build_prompt_summary(prompt_performance) -> List[Dict[str, float]]:
    summary = []
    for perf in list(prompt_performance)[:5]:
        summary.append(
            {
                "prompt_id": perf.prompt_id,
                "success_rate": round(perf.success_rate * 100, 2),
                "error_rate": round(perf.error_rate * 100, 2),
                "preview": perf.prompt_preview,
            }
        )
    return summary


def _build_dashboard_html(
    success_trend: Dict[str, List],
    pattern_trend: Dict[str, List],
    top_prompts: List[Dict[str, float]],
    blocklist: List[str],
    whitelist: List[str],
) -> str:
    success_json = json.dumps(success_trend)
    pattern_json = json.dumps(pattern_trend)
    prompts_json = json.dumps(top_prompts)
    blocklist_json = json.dumps(blocklist)
    whitelist_json = json.dumps(whitelist)

    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>Prompt Performance Dashboard</title>
<script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
<style>
body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 2rem; }}
section {{ margin-bottom: 2rem; }}
.card {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }}
h1 {{ margin-bottom: 1rem; }}
.flex {{ display: flex; gap: 1.5rem; flex-wrap: wrap; }}
.flex > .card {{ flex: 1; min-width: 280px; }}
code {{ background: #0f172a; padding: 0.2rem 0.4rem; border-radius: 4px; }}
ul {{ padding-left: 1.2rem; }}
</style>
</head>
<body>
<h1>Prompt Performance Dashboard</h1>
<div class=\"card\">
<canvas id=\"successTrend\"></canvas>
</div>
<div class=\"card\">
<canvas id=\"patternTrend\"></canvas>
</div>
<div class=\"flex\">
<div class=\"card\">
<h2>Top Prompts</h2>
<ul id=\"promptList\"></ul>
</div>
<div class=\"card\">
<h2>Pattern Signals</h2>
<p>Blocklist: <code id=\"blocklist\"></code></p>
<p>Whitelist: <code id=\"whitelist\"></code></p>
</div>
</div>
<script>
const successTrend = {success_json};
const patternTrend = {pattern_json};
const topPrompts = {prompts_json};
const blocklist = {blocklist_json};
const whitelist = {whitelist_json};

new Chart(document.getElementById('successTrend'), {{
    type: 'line',
    data: {{
        labels: successTrend.labels,
        datasets: [{{
            label: 'Success rate',
            data: successTrend.values,
            borderColor: '#10b981',
            fill: false,
            tension: 0.3,
        }}]
    }},
    options: {{ scales: {{ y: {{ min: 0, max: 1, ticks: {{ callback: v => (v*100).toFixed(0) + '%' }} }} }} }}
}});

new Chart(document.getElementById('patternTrend'), {{
    type: 'line',
    data: {{
        labels: patternTrend.labels,
        datasets: [
            {{ label: 'Blocklist matches', data: patternTrend.blocklist, borderColor: '#f97316', fill: false }},
            {{ label: 'Whitelist matches', data: patternTrend.whitelist, borderColor: '#38bdf8', fill: false }}
        ]
    }},
}});

const promptList = document.getElementById('promptList');
topPrompts.forEach(prompt => {{
    const item = document.createElement('li');
    item.textContent = `${{prompt.prompt_id}} – Success: ${{prompt.success_rate}}%, Errors: ${{prompt.error_rate}}%`;
    promptList.appendChild(item);
}});

document.getElementById('blocklist').textContent = blocklist.join(', ') || '—';
document.getElementById('whitelist').textContent = whitelist.join(', ') || '—';
</script>
</body>
</html>"""


__all__ = ["render_prompt_dashboard"]
