"""
View automation metrics summary.

This script displays collected metrics about prompt seeding and model selections.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from automation.metrics import get_metrics_tracker  # noqa: E402
from automation.cost_tracker import get_cost_tracker  # noqa: E402


def main():
    """Display metrics summary."""
    tracker = get_metrics_tracker()
    tracker.print_summary()
    
    # Show cost report
    cost_tracker = get_cost_tracker()
    cost_tracker.print_cost_report(days=7)
    
    # Check for budget alerts
    alerts = cost_tracker.check_budget_alerts()
    if alerts:
        print("🚨 ACTIVE BUDGET ALERTS:")
        print("-" * 70)
        for alert in alerts:
            print(f"  ⚠️  {alert}")
        print()
    
    # Show recent events if there are any
    if tracker.prompt_metrics:
        print("\n📝 RECENT PROMPT SEEDINGS (Last 5)")
        print("-" * 70)
        for metric in tracker.prompt_metrics[-5:]:
            status = "✓" if metric.success else "✗"
            model = metric.model_requested or "None"
            print(f"{status} [{metric.timestamp.strftime('%Y-%m-%d %H:%M:%S')}]")
            print(f"   Panel: {metric.panel_title[:60]}")
            print(f"   Prompt #{metric.prompt_index}: {metric.prompt_preview[:50]}...")
            print(f"   Model: {model}")
            if not metric.success and metric.error_message:
                print(f"   Error: {metric.error_message}")
            print()
    
    if tracker.model_metrics:
        print("🤖 RECENT MODEL SELECTIONS (Last 5)")
        print("-" * 70)
        for metric in tracker.model_metrics[-5:]:
            status = "✓" if metric.success else "✗"
            print(f"{status} [{metric.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"{metric.model_label} - {metric.panel_title[:50]}")
        print()


if __name__ == "__main__":
    main()
