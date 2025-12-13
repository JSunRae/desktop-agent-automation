"""Enhanced OpenAI pricing verification automation.

This script compares the hard-coded pricing metadata stored in
``automation.cost_tracker.DEFAULT_MODEL_RATES`` with the latest figures
published by OpenAI. The enhanced workflow supports:

* Detailed diff detection with percentage changes per rate type
* JSON/Markdown report generation under ``logs/pricing_checks``
* Optional git auto-commit of generated reports
* Historical comparisons against the most recent saved report
* Notification previews for console/email/webhook delivery

Run ``python scripts/verify_pricing.py --help`` for the full CLI reference.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from automation.cost_tracker import DEFAULT_MODEL_RATES, DEFAULT_RATES_LAST_UPDATED  # noqa: E402

DEFAULT_PRICING_URLS = [
    "https://raw.githubusercontent.com/openai/openai-cookbook/main/data/pricing.json",
    "https://openai.com/pricing",
]

REPORTS_DIR = PROJECT_ROOT / "logs" / "pricing_checks"
CHECKER_VERSION = "1.1.0"
PER_MILLION_TOKENS = 1000  # Rates are stored per 1k tokens
RATE_TYPES = ("input", "output", "vision")


@dataclass(frozen=True)
class PricingRecord:
    """Normalized pricing entry for a single model."""

    model: str
    input: Optional[float]
    output: Optional[float]
    vision: Optional[float] = None

    def payload(self) -> Dict[str, Optional[float]]:
        return {"input": self.input, "output": self.output, "vision": self.vision}


PricingMap = Dict[str, PricingRecord]


def parse_pricing_text(text: str) -> PricingMap:
    """Parse pricing data from JSON or HTML/markdown tables."""

    text = text.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        parsed = _parse_pricing_payload(payload)
        if parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    pattern = re.compile(
        r"(gpt-[\w-]+)[^$]+\$(\d+\.\d+|0?\.\d+)[^$]+1k\s*(?:input|prompt)[^$]+\$(\d+\.\d+|0?\.\d+)",
        re.IGNORECASE,
    )
    matches = pattern.findall(text)
    parsed: PricingMap = {}
    for raw_model, input_raw, output_raw in matches:
        model = raw_model.strip()
        try:
            entry = PricingRecord(model=model, input=float(input_raw), output=float(output_raw))
        except ValueError:
            continue
        parsed[_normalize_model_key(model)] = entry
    return parsed


def _parse_pricing_payload(payload: object) -> PricingMap:
    parsed: PricingMap = {}
    if isinstance(payload, Mapping):
        for model, data in payload.items():
            rates = _normalize_rate_mapping(data)
            if not rates:
                continue
            name = str(model)
            parsed[_normalize_model_key(name)] = PricingRecord(
                model=name,
                input=rates.get("input"),
                output=rates.get("output"),
                vision=rates.get("vision"),
            )
    elif isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("model") or entry.get("id") or entry.get("name") or "")
            if not name:
                continue
            rates = _normalize_rate_mapping(entry)
            if not rates:
                continue
            parsed[_normalize_model_key(name)] = PricingRecord(
                model=name,
                input=rates.get("input"),
                output=rates.get("output"),
                vision=rates.get("vision"),
            )
    return parsed


def _normalize_rate_mapping(data: object) -> Optional[Dict[str, float]]:
    if not isinstance(data, Mapping):
        return None
    input_candidates = [
        data.get("input_per_1k"),
        data.get("input"),
        data.get("prompt"),
        data.get("prompt_1k_tokens"),
        data.get("input_tokens"),
    ]
    output_candidates = [
        data.get("output_per_1k"),
        data.get("output"),
        data.get("completion"),
        data.get("completion_1k_tokens"),
        data.get("output_tokens"),
    ]
    vision_candidates = [
        data.get("vision_per_image"),
        data.get("image"),
        data.get("image_per_call"),
        data.get("vision"),
    ]
    result: Dict[str, float] = {}
    input_rate = _first_float(input_candidates)
    if input_rate is not None:
        result["input"] = input_rate
    output_rate = _first_float(output_candidates)
    if output_rate is not None:
        result["output"] = output_rate
    vision_rate = _first_float(vision_candidates)
    if vision_rate is not None:
        result["vision"] = vision_rate
    return result or None


def _first_float(values: Iterable[object]) -> Optional[float]:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def download_text(url: str) -> Optional[str]:
    try:
        with urlopen(url, timeout=10) as response:  # nosec B310 - controlled URLs
            return response.read().decode("utf-8", errors="replace")
    except (URLError, OSError):
        return None


def load_pricing_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def prompt_for_rates() -> PricingMap:
    print("Manual pricing input mode. Press Enter to keep the current value.")
    overrides: PricingMap = {}
    for model, rate in DEFAULT_MODEL_RATES.items():
        base_input = rate.input_per_1k
        base_output = rate.output_per_1k
        try:
            new_input = input(f"{model} input $/1K (default {base_input}): ").strip()
            new_output = input(f"{model} output $/1K (default {base_output}): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted by user.")
            sys.exit(130)
        input_value = base_input if not new_input else float(new_input)
        output_value = base_output if not new_output else float(new_output)
        record = PricingRecord(model=model, input=input_value, output=output_value)
        overrides[_normalize_model_key(model)] = record
    return overrides


def build_current_rates() -> PricingMap:
    current: PricingMap = {}
    for model, rate in DEFAULT_MODEL_RATES.items():
        record = PricingRecord(model=model, input=rate.input_per_1k, output=rate.output_per_1k)
        current[_normalize_model_key(model)] = record
    return current


def compare_pricing(current_rates: PricingMap, api_rates: PricingMap, tolerance: float) -> Dict[str, Any]:
    increased: List[Dict[str, Any]] = []
    decreased: List[Dict[str, Any]] = []
    unchanged: List[str] = []
    deprecated: List[str] = []

    for key, local in current_rates.items():
        remote = api_rates.get(key)
        if not remote:
            deprecated.append(local.model)
            continue
        changed = False
        for rate_type in RATE_TYPES:
            local_value = getattr(local, rate_type)
            remote_value = getattr(remote, rate_type)
            if remote_value is None and local_value is None:
                continue
            if remote_value is None:
                continue
            if local_value is None:
                entry = _build_change_entry(
                    model=local.model,
                    rate_type=rate_type,
                    old_price=None,
                    new_price=remote_value,
                )
                increased.append(entry)
                changed = True
                continue
            if _rate_changed(local_value, remote_value, tolerance):
                entry = _build_change_entry(
                    model=local.model,
                    rate_type=rate_type,
                    old_price=local_value,
                    new_price=remote_value,
                )
                if remote_value > local_value:
                    increased.append(entry)
                else:
                    decreased.append(entry)
                changed = True
        if not changed:
            unchanged.append(local.model)

    new_models = [record.model for key, record in api_rates.items() if key not in current_rates]

    return {
        "unchanged": sorted(unchanged),
        "increased": increased,
        "decreased": decreased,
        "new_models": sorted(new_models),
        "deprecated": sorted(deprecated),
    }


def _build_change_entry(*, model: str, rate_type: str, old_price: Optional[float], new_price: Optional[float]) -> Dict[str, Any]:
    change_pct = None
    if old_price not in (None, 0):
        change_pct = round(((new_price or 0) - old_price) / old_price * 100, 2)
    delta = None
    if old_price is not None and new_price is not None:
        delta = new_price - old_price
    per_million = _per_million_delta(old_price, new_price)
    return {
        "model": model,
        "rate_type": rate_type,
        "old_price": old_price,
        "new_price": new_price,
        "change_pct": change_pct,
        "change_per_1m_tokens": per_million,
        "delta": delta,
    }


def _per_million_delta(old_price: Optional[float], new_price: Optional[float]) -> Optional[float]:
    if new_price is None:
        return None
    base_old = old_price or 0.0
    delta = new_price - base_old
    return round(delta * PER_MILLION_TOKENS, 6)


def _rate_changed(local_value: float, remote_value: float, tolerance: float) -> bool:
    if remote_value == 0:
        return local_value != 0
    relative = abs(remote_value - local_value) / abs(remote_value)
    return relative > tolerance


def build_recommendations(changes: Dict[str, Any]) -> List[str]:
    recommendations: List[str] = []
    for change in changes["increased"] + changes["decreased"]:
        rate_type = change["rate_type"]
        old_price = _format_currency(change["old_price"])
        new_price = _format_currency(change["new_price"])
        recommendations.append(
            f"Update automation/cost_tracker.py for {change['model']} {rate_type} rate ({old_price} -> {new_price})."
        )
    for model in changes["new_models"]:
        recommendations.append(f"Evaluate new model '{model}' for potential adoption.")
    for model in changes["deprecated"]:
        recommendations.append(f"Confirm whether '{model}' should be removed from DEFAULT_MODEL_RATES.")
    if not recommendations:
        recommendations.append("No action required. Pricing matches DEFAULT_MODEL_RATES.")
    return recommendations


def generate_json_report(payload: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def generate_markdown_report(payload: Dict[str, Any], output_path: Path) -> Path:
    check_dt = datetime.fromisoformat(payload["check_date"])
    counts = payload["comparison"]
    changes = payload["changes"]
    age_days = payload.get("local_rates_age_days")
    lines: List[str] = []
    lines.append(f"# OpenAI Pricing Check - {check_dt.strftime('%B %d, %Y')}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- {counts['unchanged_count']} models unchanged")
    lines.append(f"- {counts['increased_count']} models increased")
    lines.append(f"- {counts['decreased_count']} models decreased")
    lines.append(f"- {counts['new_models_count']} new models detected")
    lines.append(f"- {counts['deprecated_count']} deprecated models")
    if age_days is not None:
        lines.append(f"- Local defaults last updated {age_days} days ago")
    lines.append("")

    if changes["increased"]:
        lines.append("## Price Increases")
        for change in changes["increased"]:
            lines.extend(_markdown_change_block(change))
        lines.append("")

    if changes["decreased"]:
        lines.append("## Price Decreases")
        for change in changes["decreased"]:
            lines.extend(_markdown_change_block(change))
        lines.append("")

    if changes["new_models"]:
        lines.append("## New Models")
        api_latest = payload["full_pricing"]["api_latest"]
        for model in changes["new_models"]:
            model_rates = api_latest.get(model, {})
            line = (
                f"- **{model}**: input {_format_currency(model_rates.get('input'))}, "
                f"output {_format_currency(model_rates.get('output'))}"
            )
            lines.append(line)
        lines.append("")

    if changes["deprecated"]:
        lines.append("## Deprecated Models")
        for model in changes["deprecated"]:
            lines.append(f"- {model}")
        lines.append("")

    lines.append("## Recommendations")
    for idx, rec in enumerate(payload["recommendations"], start=1):
        lines.append(f"{idx}. {rec}")
    lines.append("")

    if payload.get("previous_comparison"):
        trend = payload["previous_comparison"]
        lines.append("## Previous Comparison")
        lines.append(f"- Trend: {trend['price_trend']}")
        lines.append(f"- Models changed again: {', '.join(trend['models_that_changed_again']) or 'None'}")
        lines.append(f"- Cumulative increase: {trend['cumulative_increase_since_previous']:.2f} per 1M tokens")
        lines.append(f"- Time since last check: {trend['time_since_last_check']}")
        lines.append("")

    lines.append(f"---\nGenerated by verify_pricing.py v{CHECKER_VERSION}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _markdown_change_block(change: Dict[str, Any]) -> List[str]:
    lines = [f"### {change['model']} ({change['rate_type']} tokens)"]
    lines.append(f"- Old: {_format_currency(change['old_price'])}")
    lines.append(f"- New: {_format_currency(change['new_price'])}")
    if change["change_pct"] is not None:
        lines.append(f"- Change: {change['change_pct']:+.2f}%")
    if change["change_per_1m_tokens"] is not None:
        lines.append(f"- Impact per 1M tokens: {_format_currency(change['change_per_1m_tokens'])}")
    return lines


def format_console_output(payload: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> str:
    counts = payload["comparison"]
    changes = payload["changes"]
    lines: List[str] = []
    title = "OpenAI Pricing Verification Report"
    date_str = datetime.fromisoformat(payload["check_date"]).strftime("%B %d, %Y")
    width = max(len(title), len(date_str)) + 4
    border = "+" + "-" * (width - 2) + "+"
    lines.append(border)
    lines.append(f"| {title.ljust(width - 4)} |")
    lines.append(f"| {date_str.ljust(width - 4)} |")
    lines.append(border)
    lines.append("")
    lines.append("Summary:")
    lines.append(
        f"  OK  {counts['unchanged_count']:>3} unchanged | "
        f"INC {counts['increased_count']:>3} | DEC {counts['decreased_count']:>3} | "
        f"NEW {counts['new_models_count']:>3} | DEP {counts['deprecated_count']:>3}"
    )
    age_days = payload.get("local_rates_age_days")
    if age_days is not None:
        lines.append(f"Local defaults last updated {age_days} days ago.")
    lines.append("")
    if changes["increased"]:
        lines.append("Price Increases:")
        lines.extend(_format_console_changes(changes["increased"]))
        lines.append("")
    if changes["decreased"]:
        lines.append("Price Decreases:")
        lines.extend(_format_console_changes(changes["decreased"]))
        lines.append("")
    if changes["new_models"]:
        lines.append("New Models Detected:")
        for model in changes["new_models"]:
            lines.append(f"  - {model}")
        lines.append("")
    if changes["deprecated"]:
        lines.append("Models Missing From API:")
        for model in changes["deprecated"]:
            lines.append(f"  - {model}")
        lines.append("")
    if previous:
        lines.append("Comparison With Previous Check:")
        lines.append(f"  Trend: {previous['price_trend']}")
        again = ", ".join(previous["models_that_changed_again"]) or "None"
        lines.append(f"  Changed again: {again}")
        lines.append(
            f"  Cumulative increase: {previous['cumulative_increase_since_previous']:.2f} per 1M tokens"
        )
        lines.append(f"  Time since last check: {previous['time_since_last_check']}")
    return "\n".join(lines)


def _format_console_changes(items: Sequence[Dict[str, Any]]) -> List[str]:
    formatted: List[str] = []
    for item in items:
        pct = f" ({item['change_pct']:+.2f}%)" if item["change_pct"] is not None else ""
        formatted.append(
            f"  - {item['model']} [{item['rate_type']}] { _format_currency(item['old_price']) } -> { _format_currency(item['new_price']) }{pct}"
        )
    return formatted


def load_previous_report(reports_dir: Path) -> Optional[Dict[str, Any]]:
    if not reports_dir.exists():
        return None
    candidates = sorted(reports_dir.glob("pricing_check_*.json"))
    if not candidates:
        return None
    latest = candidates[-1]
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def compare_with_previous(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    prev_changes = previous.get("changes", {})
    curr_changes = current.get("changes", {})
    prev_changed_models = {item["model"] for item in prev_changes.get("increased", []) + prev_changes.get("decreased", [])}
    curr_changed_models = {item["model"] for item in curr_changes.get("increased", []) + curr_changes.get("decreased", [])}
    overlap = sorted(curr_changed_models.intersection(prev_changed_models))
    curr_inc = len(curr_changes.get("increased", []))
    prev_inc = len(prev_changes.get("increased", []))
    curr_dec = len(curr_changes.get("decreased", []))
    prev_dec = len(prev_changes.get("decreased", []))
    trend = "stable"
    if curr_inc > prev_inc:
        trend = "increasing"
    elif curr_dec > prev_dec:
        trend = "decreasing"

    cumulative_increase = sum(
        change.get("change_per_1m_tokens", 0) or 0 for change in curr_changes.get("increased", [])
    )

    current_dt = datetime.fromisoformat(current["check_date"])
    previous_dt = datetime.fromisoformat(previous.get("check_date", current["check_date"]))
    delta_days = (current_dt - previous_dt).days

    return {
        "price_trend": trend,
        "models_that_changed_again": overlap,
        "cumulative_increase_since_previous": cumulative_increase,
        "time_since_last_check": f"{delta_days} days",
    }


def notify_pricing_changes(changes: Dict[str, Any], method: str) -> None:
    change_count = len(changes.get("increased", [])) + len(changes.get("decreased", []))
    new_models = len(changes.get("new_models", []))
    if method == "console":
        print_alert(change_count, new_models)
    elif method == "email":
        print("Email notification would be sent to: [configure in .env]")
        print_email_preview(change_count, new_models, changes)
    elif method == "webhook":
        print("Webhook would POST to: [configure in .env]")
        print_webhook_payload(change_count, new_models, changes)


def print_alert(change_count: int, new_models: int) -> None:
    print(f"PRICING ALERT: {change_count} rate changes, {new_models} new models detected.")


def print_email_preview(change_count: int, new_models: int, changes: Dict[str, Any]) -> None:
    subject = f"OpenAI pricing update: {change_count} changes"
    body = {
        "subject": subject,
        "new_models": changes.get("new_models", []),
        "highlights": changes.get("increased", [])[:3],
    }
    print(json.dumps(body, indent=2))


def print_webhook_payload(change_count: int, new_models: int, changes: Dict[str, Any]) -> None:
    payload = {
        "event": "pricing_update",
        "change_count": change_count,
        "new_models": changes.get("new_models", []),
        "increases": changes.get("increased", [])[:5],
    }
    print(json.dumps(payload, indent=2))


def auto_commit_pricing_changes(
    report_paths: Sequence[Path],
    changes: Dict[str, Any],
    *,
    run_dir: Path,
    dry_run: bool = False,
) -> bool:
    if not shutil.which("git"):
        print("Git not available. Skipping auto-commit.")
        return False
    rel_paths = [str(path.relative_to(run_dir)) for path in report_paths]
    inc = len(changes.get("increased", []))
    dec = len(changes.get("decreased", []))
    new = len(changes.get("new_models", []))
    today = datetime.now().date().isoformat()
    title = f"chore: Pricing check {today} - {inc} increases, {dec} decreases, {new} new"
    summary_lines = ["Changes detected:"]
    for change in changes.get("increased", [])[:3]:
        summary_lines.append(
            f"- {change['model']} {change['rate_type']}: +{(change['change_pct'] or 0):.2f}%"
        )
    if len(changes.get("increased", [])) > 3:
        summary_lines.append("- ...")
    summary_lines.append("Reports: " + ", ".join(rel_paths))

    git_base = ["git", "-C", str(run_dir)]
    commands = [
        git_base + ["add", *rel_paths],
        git_base + ["commit", "-m", title, "-m", "\n".join(summary_lines)],
    ]

    if _repo_dirty(run_dir):
        print("Warning: repository has other pending changes. Proceeding with auto-commit anyway.")

    if dry_run:
        for cmd in commands:
            print("DRY RUN:", " ".join(cmd))
        return True

    try:
        for cmd in commands:
            subprocess.run(cmd, check=True)
        print("Auto-commit completed.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"Git command failed: {exc}")
        return False


def _repo_dirty(run_dir: Path) -> bool:
    git_cmd = ["git", "-C", str(run_dir), "status", "--porcelain"]
    try:
        result = subprocess.run(git_cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        return False
    return bool(result.stdout.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify OpenAI pricing vs cost_tracker defaults")
    parser.add_argument(
        "--pricing-url",
        action="append",
        help="Pricing endpoint to scrape (can be repeated)",
    )
    parser.add_argument(
        "--pricing-file",
        action="append",
        type=Path,
        help="Local JSON or HTML file with pricing tables",
    )
    parser.add_argument("--manual", action="store_true", help="Skip fetch attempts and prompt for manual values")
    parser.add_argument("--tolerance", type=float, default=0.05, help="Relative delta threshold (default: 5%)")
    parser.add_argument("--json", action="store_true", help="Output full report payload in JSON")
    parser.add_argument("--save-report", action="store_true", help="Persist reports under logs/pricing_checks")
    parser.add_argument(
        "--auto-commit",
        action="store_true",
        help="Automatically commit generated pricing reports (requires --save-report)",
    )
    parser.add_argument(
        "--notify",
        choices=["console", "email", "webhook"],
        default="console",
        help="Notification preview method",
    )
    parser.add_argument(
        "--compare-previous",
        action="store_true",
        help="Compare against the most recent saved pricing report",
    )
    return parser


def fetch_remote_rates(args: argparse.Namespace) -> Tuple[PricingMap, str]:
    remote_rates: PricingMap = {}
    source = ""
    if not args.manual:
        candidate_urls = args.pricing_url or DEFAULT_PRICING_URLS
        for url in candidate_urls:
            text = download_text(url)
            if not text:
                continue
            parsed = parse_pricing_text(text)
            if parsed:
                remote_rates = parsed
                source = url
                break
        if not remote_rates and args.pricing_file:
            for path in args.pricing_file:
                text = load_pricing_file(path)
                if not text:
                    continue
                parsed = parse_pricing_text(text)
                if parsed:
                    remote_rates = parsed
                    source = str(path)
                    break
    if not remote_rates:
        remote_rates = prompt_for_rates()
        source = "manual"
    return remote_rates, source


def build_full_pricing_map(pricing_map: PricingMap) -> Dict[str, Dict[str, Optional[float]]]:
    return {record.model: record.payload() for record in pricing_map.values()}


def _normalize_model_key(name: str) -> str:
    return name.lower().strip()


def _format_currency(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"${value:.4f}"


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.auto_commit and not args.save_report:
        parser.error("--auto-commit requires --save-report")

    reports_dir = REPORTS_DIR
    if args.save_report or args.compare_previous:
        reports_dir.mkdir(parents=True, exist_ok=True)

    current_rates = build_current_rates()
    remote_rates, metadata_source = fetch_remote_rates(args)
    changes = compare_pricing(current_rates, remote_rates, args.tolerance)
    recommendations = build_recommendations(changes)
    now = datetime.now(timezone.utc)
    local_age_days = (datetime.now() - DEFAULT_RATES_LAST_UPDATED).days

    previous_analysis = None
    if args.compare_previous:
        previous = load_previous_report(reports_dir)
        if previous:
            previous_analysis = compare_with_previous(
                {
                    "check_date": now.isoformat(),
                    "changes": changes,
                },
                previous,
            )
        else:
            print("No previous pricing check found. This will act as the baseline.")

    comparison_counts = {
        "unchanged_count": len(changes["unchanged"]),
        "increased_count": len(changes["increased"]),
        "decreased_count": len(changes["decreased"]),
        "new_models_count": len(changes["new_models"]),
        "deprecated_count": len(changes["deprecated"]),
    }

    payload = {
        "check_date": now.isoformat(),
        "checker_version": CHECKER_VERSION,
        "api_source": metadata_source,
        "comparison": comparison_counts,
        "changes": changes,
        "full_pricing": {
            "current_code": build_full_pricing_map(current_rates),
            "api_latest": build_full_pricing_map(remote_rates),
        },
        "recommendations": recommendations,
        "local_rates_age_days": local_age_days,
    }
    if previous_analysis:
        payload["previous_comparison"] = previous_analysis

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    console = format_console_output(payload, payload.get("previous_comparison"))
    print(console)

    report_paths: List[Path] = []
    if args.save_report:
        base_name = f"pricing_check_{now.date().isoformat()}"
        json_path = reports_dir / f"{base_name}.json"
        md_path = reports_dir / f"{base_name}.md"
        generate_json_report(payload, json_path)
        generate_markdown_report(payload, md_path)
        report_paths = [json_path, md_path]
        print("Reports saved to:")
        for path in report_paths:
            rel = path.relative_to(PROJECT_ROOT)
            print(f"  - {rel}")

    change_detected = any(
        [
            changes["increased"],
            changes["decreased"],
            changes["new_models"],
            changes["deprecated"],
        ]
    )
    if change_detected:
        notify_pricing_changes(changes, args.notify)

    if args.auto_commit and report_paths:
        auto_commit_pricing_changes(report_paths, changes, run_dir=PROJECT_ROOT)


if __name__ == "__main__":
    main()
