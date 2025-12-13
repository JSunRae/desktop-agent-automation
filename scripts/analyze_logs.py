"""
Log analysis tool for detecting false positives and issues in automation logs.

This script analyzes the automation logs to identify:
- False positive panel processing (panels that shouldn't have been processed)
- Unexpected seeding attempts
- Rate limit issues
- Failed operations
- Suspicious patterns
"""

import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def parse_log_entry(line):
    """Parse a log line and extract timestamp, level, module, and message."""
    # Format: [2025-12-07 14:30:45] [INFO] [PanelTracker] Message
    match = re.match(r'\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s+(.*)', line)
    if match:
        timestamp_str, level, module, message = match.groups()
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = None
        return {
            'timestamp': timestamp,
            'level': level,
            'module': module,
            'message': message,
            'raw': line
        }
    return None


def analyze_logs(log_path, hours=1):
    """Analyze logs for the last N hours."""
    
    print("\n" + "="*70)
    print(f"LOG ANALYSIS - Last {hours} hour(s)")
    print("="*70 + "\n")
    
    if not log_path.exists():
        print(f"❌ Log file not found: {log_path}")
        return
    
    # Read log file
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    # Calculate time threshold
    now = datetime.now()
    cutoff_time = now.replace(hour=now.hour - hours if now.hour >= hours else 0)
    
    # Categories to track
    errors = []
    warnings = []
    seeded_panels = []
    dry_run_actions = []
    rate_limits = []
    panel_state_changes = []
    suspicious_patterns = []
    
    # Analyze each line
    for line in lines:
        entry = parse_log_entry(line.strip())
        if not entry:
            continue
        
        # Skip old entries
        if entry['timestamp'] and entry['timestamp'] < cutoff_time:
            continue
        
        message = entry['message']
        level = entry['level']
        
        # Categorize entries
        if level == 'ERROR':
            errors.append(entry)
        
        if level == 'WARNING':
            warnings.append(entry)
        
        if 'seeded_prompt' in message.lower() or 'seeding' in message.lower():
            seeded_panels.append(entry)
        
        if '[DRY-RUN]' in message:
            dry_run_actions.append(entry)
        
        if 'rate limit' in message.lower() or 'try again' in message.lower():
            rate_limits.append(entry)
        
        if 'Panel now' in message and ('FINISHED' in message or 'RUNNING' in message or 'IDLE' in message):
            panel_state_changes.append(entry)
        
        # Detect suspicious patterns
        if 'user text' in message.lower() and 'skipping' not in message.lower():
            suspicious_patterns.append(('Possible user text issue', entry))
        
        if 'failed to' in message.lower() or 'error' in message.lower():
            suspicious_patterns.append(('Operation failure', entry))
    
    # Report findings
    print("📊 SUMMARY")
    print("-" * 70)
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Seeded panels: {len(seeded_panels)}")
    print(f"Dry-run actions: {len(dry_run_actions)}")
    print(f"Rate limit events: {len(rate_limits)}")
    print(f"Panel state changes: {len(panel_state_changes)}")
    print(f"Suspicious patterns: {len(suspicious_patterns)}")
    print()
    
    # Show details
    if errors:
        print("🔴 ERRORS")
        print("-" * 70)
        for entry in errors[-10:]:  # Show last 10
            print(f"[{entry['timestamp']}] {entry['message'][:100]}")
        print()
    
    if warnings:
        print("⚠️  WARNINGS")
        print("-" * 70)
        for entry in warnings[-10:]:  # Show last 10
            print(f"[{entry['timestamp']}] {entry['message'][:100]}")
        print()
    
    if seeded_panels:
        print("🌱 SEEDED PANELS")
        print("-" * 70)
        for entry in seeded_panels[-5:]:  # Show last 5
            print(f"[{entry['timestamp']}] {entry['message'][:100]}")
        print()
    
    if dry_run_actions:
        print("🧪 DRY-RUN ACTIONS")
        print("-" * 70)
        for entry in dry_run_actions[-5:]:  # Show last 5
            print(f"[{entry['timestamp']}] {entry['message'][:100]}")
        print()
    
    if rate_limits:
        print("⏱️  RATE LIMIT EVENTS")
        print("-" * 70)
        for entry in rate_limits[-5:]:  # Show last 5
            print(f"[{entry['timestamp']}] {entry['message'][:100]}")
        print()
    
    if suspicious_patterns:
        print("🚨 SUSPICIOUS PATTERNS")
        print("-" * 70)
        for pattern_type, entry in suspicious_patterns[-5:]:  # Show last 5
            print(f"[{entry['timestamp']}] {pattern_type}: {entry['message'][:80]}")
        print()
    
    # False positive detection
    print("🔍 FALSE POSITIVE ANALYSIS")
    print("-" * 70)
    
    false_positive_indicators = []
    
    # Check for panels that shouldn't have been seeded
    for entry in seeded_panels:
        if 'user text' in entry['message'].lower():
            false_positive_indicators.append(
                f"Seeded panel with user text: {entry['message'][:80]}"
            )
    
    # Check for unexpected panel processing
    for entry in panel_state_changes:
        if 'STALE' in entry['message']:
            # STALE panels shouldn't be processed
            continue
        if 'FINISHED' in entry['message'] and 'unseeded' not in entry['message'].lower():
            # Might be processing a panel that was already seeded
            false_positive_indicators.append(
                f"State change on potentially seeded panel: {entry['message'][:80]}"
            )
    
    if false_positive_indicators:
        print("⚠️  Potential false positives detected:")
        for indicator in false_positive_indicators:
            print(f"   • {indicator}")
    else:
        print("✅ No obvious false positives detected")
    
    print()
    print("="*70)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze automation logs for issues")
    parser.add_argument(
        "--hours",
        type=int,
        default=1,
        help="Number of hours to analyze (default: 1)"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="logs/@AutomationLog.txt",
        help="Path to log file (default: logs/@AutomationLog.txt)"
    )
    
    args = parser.parse_args()
    
    log_path = Path(args.log_file)
    analyze_logs(log_path, args.hours)
