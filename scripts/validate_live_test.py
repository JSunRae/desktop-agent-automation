"""
Validation script for live mode testing.

This script checks all prerequisites before running the automation in live mode,
ensuring safe testing with benign prompts.
"""

import sys
from pathlib import Path

# Add project root to path - must be before automation import
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from automation import config  # noqa: E402


def check_prerequisites():
    """Check all prerequisites for safe live testing."""
    
    print("\n" + "="*70)
    print("LIVE MODE VALIDATION")
    print("="*70 + "\n")
    
    checks_passed = []
    checks_failed = []
    
    # 1. Check prompt file exists
    print("1. Checking prompt file...")
    if config.FINISHED_PANEL_PROMPT_PATH.exists():
        with open(config.FINISHED_PANEL_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            prompts = [p.strip() for p in content.split("\n\n") if p.strip()]
            print(f"   ✓ Prompt file exists: {config.FINISHED_PANEL_PROMPT_PATH}")
            print(f"   ✓ Found {len(prompts)} prompt(s)")
            
            # Show prompts
            for i, prompt in enumerate(prompts, 1):
                first_line = prompt.split("\n")[0]
                print(f"      - {first_line[:70]}...")
            
            checks_passed.append("Prompt file")
    else:
        print(f"   ✗ Prompt file not found: {config.FINISHED_PANEL_PROMPT_PATH}")
        checks_failed.append("Prompt file")
    
    print()
    
    # 2. Check environment variables
    print("2. Checking environment variables...")
    env_checks = {
        "ENABLE_FINISHED_PANEL_FOLLOWUPS": config.ENABLE_FINISHED_PANEL_FOLLOWUPS,
        "ENABLE_SEND_TO_INACTIVE_PANELS": config.ENABLE_SEND_TO_INACTIVE_PANELS,
        "FINISHED_PANEL_DRY_RUN": config.FINISHED_PANEL_DRY_RUN,
    }
    
    for name, value in env_checks.items():
        status = "✓" if value else "✗"
        print(f"   {status} {name}: {value}")
        if value:
            checks_passed.append(name)
        else:
            checks_failed.append(name)
    
    print()
    
    # 3. Check for test panel (we can't check this without running)
    print("3. Test panel requirements:")
    print("   • Panel name should contain: 'Testing window functionality'")
    print("   • Panel should be in FINISHED state (idle 30+ minutes)")
    print("   • Panel should not have user-prepared text")
    print()
    
    # 4. Safety recommendations
    print("4. Safety recommendations:")
    print("   • Monitor logs in real-time during test")
    print("   • Keep terminal visible to press Ctrl+C if needed")
    print("   • Test during low-activity period")
    print("   • Start with FINISHED_PANEL_DRY_RUN=true first")
    print()
    
    # Summary
    print("="*70)
    print("SUMMARY")
    print("="*70 + "\n")
    
    print(f"Checks passed: {len(checks_passed)}")
    print(f"Checks failed: {len(checks_failed)}")
    print()
    
    if checks_failed:
        print("❌ Prerequisites not met. Fix the following before testing:")
        for check in checks_failed:
            print(f"   - {check}")
        print()
        print("To enable live mode, run:")
        print("   $env:ENABLE_FINISHED_PANEL_FOLLOWUPS = \"true\"")
        print("   $env:FINISHED_PANEL_DRY_RUN = \"false\"")
        print("   $env:ENABLE_SEND_TO_INACTIVE_PANELS = \"true\"")
        print()
        return False
    else:
        print("✅ All prerequisites met!")
        print()
        print("To start live mode testing:")
        print("   python -m automation.orchestrator")
        print()
        print("Monitor logs with:")
        print("   Get-Content logs\\@AutomationLog.txt -Tail 50 -Wait")
        print()
        return True


if __name__ == "__main__":
    success = check_prerequisites()
    sys.exit(0 if success else 1)
