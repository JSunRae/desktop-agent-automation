"""Verify cost_tracker pricing metadata against OpenAI's published rates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from automation.cost_tracker import DEFAULT_MODEL_RATES, DEFAULT_RATES_LAST_UPDATED  # noqa: E402

DEFAULT_PRICING_URLS = [
    "https://raw.githubusercontent.com/openai/openai-cookbook/main/data/pricing.json",
    "https://openai.com/pricing",
]


@dataclass
class ComparisonResult:
    model: str
    local_input: float
    local_output: float
    remote_input: Optional[float]
    remote_output: Optional[float]
    input_delta: Optional[float]
    output_delta: Optional[float]
    input_changed: bool
    output_changed: bool


RatePair = Tuple[float, float]


def parse_pricing_text(text: str) -> Dict[str, RatePair]:
    text = text.strip()
    if not text:
        return {}
    # Try strict JSON first.
    try:
        payload = json.loads(text)
        parsed = _parse_pricing_payload(payload)
        if parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    # Fall back to regex scraping.
    pattern = re.compile(
        r"(gpt-[\w-]+)[^$]+\$(\d+\.\d+|0?\.\d+)[^$]+1k\s*(?:input|prompt)[^$]+\$(\d+\.\d+|0?\.\d+)",
        re.IGNORECASE,
    )
    matches = pattern.findall(text)
    parsed: Dict[str, RatePair] = {}
    for model, input_raw, output_raw in matches:
        try:
            parsed[model.lower()] = (float(input_raw), float(output_raw))
        except ValueError:
            continue
    return parsed


def _parse_pricing_payload(payload: object) -> Dict[str, RatePair]:
    parsed: Dict[str, RatePair] = {}
    if isinstance(payload, Mapping):
        for model, data in payload.items():
            rates = _normalize_rate_mapping(data)
            if rates:
                parsed[str(model).lower()] = rates
    elif isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, Mapping):
                continue
            model = entry.get("model") or entry.get("id")
            rates = _normalize_rate_mapping(entry)
            if model and rates:
                parsed[str(model).lower()] = rates
    return parsed


def _normalize_rate_mapping(data: object) -> Optional[RatePair]:
    if not isinstance(data, Mapping):
        return None
    input_candidates = [
        data.get("input_per_1k"),
        data.get("input"),
        data.get("prompt"),
        data.get("prompt_1k_tokens"),
    ]
    output_candidates = [
        data.get("output_per_1k"),
        data.get("output"),
        data.get("completion"),
        data.get("completion_1k_tokens"),
    ]
    input_rate = _first_float(input_candidates)
    output_rate = _first_float(output_candidates)
    if input_rate is None or output_rate is None:
        return None
    return (input_rate, output_rate)


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


def prompt_for_rates() -> Dict[str, RatePair]:
    print("Manual pricing input mode. Press Enter to keep the current value.")
    overrides: Dict[str, RatePair] = {}
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
        overrides[model.lower()] = (input_value, output_value)
    return overrides


def compare_rates(remote: Mapping[str, RatePair], tolerance: float) -> Tuple[list[ComparisonResult], list[str]]:
    findings: list[ComparisonResult] = []
    warnings: list[str] = []
    normalized_remote = {key.lower(): value for key, value in remote.items()}
    for model, local_rate in DEFAULT_MODEL_RATES.items():
        remote_rate = normalized_remote.get(model.lower())
        if remote_rate is None:
            warnings.append(f"No remote pricing found for {model}.")
            findings.append(
                ComparisonResult(
                    model=model,
                    local_input=local_rate.input_per_1k,
                    local_output=local_rate.output_per_1k,
                    remote_input=None,
                    remote_output=None,
                    input_delta=None,
                    output_delta=None,
                    input_changed=False,
                    output_changed=False,
                )
            )
            continue
        input_delta = remote_rate[0] - local_rate.input_per_1k
        output_delta = remote_rate[1] - local_rate.output_per_1k
        input_changed = _threshold_exceeded(remote_rate[0], local_rate.input_per_1k, tolerance)
        output_changed = _threshold_exceeded(remote_rate[1], local_rate.output_per_1k, tolerance)
        findings.append(
            ComparisonResult(
                model=model,
                local_input=local_rate.input_per_1k,
                local_output=local_rate.output_per_1k,
                remote_input=remote_rate[0],
                remote_output=remote_rate[1],
                input_delta=input_delta,
                output_delta=output_delta,
                input_changed=input_changed,
                output_changed=output_changed,
            )
        )
    for model, rates in normalized_remote.items():
        if model not in {name.lower() for name in DEFAULT_MODEL_RATES}:
            warnings.append(f"Remote pricing list includes unknown model '{model}'.")
    age_days = (datetime.now() - DEFAULT_RATES_LAST_UPDATED).days
    if age_days > 30:
        warnings.append(f"Local DEFAULT_MODEL_RATES are {age_days} days old. Consider refreshing the constants.")
    return findings, warnings


def _threshold_exceeded(remote_value: float, local_value: float, tolerance: float) -> bool:
    if remote_value == 0:
        return False
    relative = abs(remote_value - local_value) / remote_value
    return relative > tolerance


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
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    remote_rates: Dict[str, RatePair] = {}
    metadata_source = ""
    if not args.manual:
        candidate_urls = args.pricing_url or DEFAULT_PRICING_URLS
        for url in candidate_urls:
            text = download_text(url)
            if not text:
                continue
            parsed = parse_pricing_text(text)
            if parsed:
                remote_rates = parsed
                metadata_source = url
                break
        if not remote_rates and args.pricing_file:
            for path in args.pricing_file:
                text = load_pricing_file(path)
                if not text:
                    continue
                parsed = parse_pricing_text(text)
                if parsed:
                    remote_rates = parsed
                    metadata_source = str(path)
                    break
    if not remote_rates:
        remote_rates = prompt_for_rates()
        metadata_source = "manual"

    findings, warnings = compare_rates(remote_rates, args.tolerance)

    if args.json:
        payload = {
            "source": metadata_source,
            "warnings": warnings,
            "results": [result.__dict__ for result in findings],
        }
        print(json.dumps(payload, indent=2))
        return

    print("OPENAI PRICING VERIFICATION")
    print("============================")
    print(f"Source: {metadata_source or 'unknown'}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    headers = ["Model", "Local In", "Remote In", "Delta In", "Local Out", "Remote Out", "Delta Out", "Status"]
    rows = []
    for result in findings:
        status_bits = []
        if result.input_changed:
            status_bits.append("input")
        if result.output_changed:
            status_bits.append("output")
        status = ",".join(status_bits) if status_bits else "ok"
        rows.append(
            [
                result.model,
                f"{result.local_input:.6f}",
                _fmt_optional(result.remote_input),
                _fmt_optional(result.input_delta, signed=True),
                f"{result.local_output:.6f}",
                _fmt_optional(result.remote_output),
                _fmt_optional(result.output_delta, signed=True),
                status,
            ]
        )
    if rows:
        _print_table(headers, rows)
    else:
        print("No comparable pricing data was generated.")


def _fmt_optional(value: Optional[float], *, signed: bool = False) -> str:
    if value is None:
        return "-"
    if signed:
        return f"{value:+.6f}"
    return f"{value:.6f}"


def _print_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> None:
    rows_list = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in rows_list:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    header_line = " | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))
    divider = "-+-".join("-" * width for width in widths)
    print(header_line)
    print(divider)
    for row in rows_list:
        print(" | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)))


if __name__ == "__main__":
    main()
