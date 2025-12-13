"""
Test script to verify finished panel follow-through in dry-run mode.

This script simulates the environment for testing without making actual UI changes.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set dry-run mode
os.environ["ENABLE_FINISHED_PANEL_FOLLOWUPS"] = "true"
os.environ["FINISHED_PANEL_DRY_RUN"] = "true"
os.environ["ENABLE_SEND_TO_INACTIVE_PANELS"] = "true"

from automation import panel_tracker as pt
from types import SimpleNamespace

def main():
    print("\n" + "="*70)
    print("FINISHED PANEL FOLLOW-THROUGH DRY-RUN TEST")
    print("="*70 + "\n")
    
    # Create a mock VS Code window
    mock_window = SimpleNamespace(Name="Testing window functionality - desktop-agent-automation")
    vs_windows = [mock_window]
    
    print(f"Configuration:")
    print(f"  ENABLE_FINISHED_PANEL_FOLLOWUPS: {pt.ENABLE_FINISHED_PANEL_FOLLOWUPS}")
    print(f"  FINISHED_PANEL_DRY_RUN: {pt.FINISHED_PANEL_DRY_RUN}")
    print(f"  FINISHED_PANEL_PROMPT_PATH: {pt.FINISHED_PANEL_PROMPT_PATH}")
    print()
    
    # Check if prompt file exists
    if pt.FINISHED_PANEL_PROMPT_PATH.exists():
        print(f"✓ Prompt file found: {pt.FINISHED_PANEL_PROMPT_PATH}")
        with open(pt.FINISHED_PANEL_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            prompts = [p.strip() for p in content.split("\n\n") if p.strip()]
            print(f"  Found {len(prompts)} prompt(s)")
    else:
        print(f"✗ Prompt file not found: {pt.FINISHED_PANEL_PROMPT_PATH}")
        print("  Please create the prompt file before running.")
        return 1
    
    print()
    print("Attempting to process finished panels...")
    print()
    
    try:
        processed = pt.process_finished_panels_with_prompts(vs_windows)
        print()
        print(f"Result: {processed} panel(s) processed in dry-run mode")
        print()
        
        if processed > 0:
            print("✓ Dry-run test completed successfully!")
            print("  Check the output above for '[DRY-RUN]' messages")
        else:
            print("ℹ No finished panels found to process")
            print("  This is expected if no panels are in FINISHED state")
        
        return 0
        
    except Exception as e:
        print(f"✗ Error during processing: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    print()
    sys.exit(exit_code)
