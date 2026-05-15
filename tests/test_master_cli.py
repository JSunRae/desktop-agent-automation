from __future__ import annotations

import sys

from automation.cli import master


def test_master_lists_pricing_verification_workflow(capsys) -> None:
    rc = master.main(["--list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "pricing-verification" in out
    assert "Monthly Pricing Verification" in out


def test_master_pricing_verification_invocation_uses_monthly_check() -> None:
    spec = master._resolve_command("pricing-verification")

    assert spec is not None
    invocation = master._build_invocation(spec, [])
    assert invocation == [
        sys.executable,
        "scripts/verify_pricing.py",
        "--monthly-check",
    ]


def test_master_launch_preflight_invocation_uses_new_script() -> None:
    spec = master._resolve_command("launch-preflight")

    assert spec is not None
    assert spec.ensure_orchestrator is False
    invocation = master._build_invocation(spec, [])
    assert invocation == [
        sys.executable,
        "scripts/launch_preflight.py",
    ]


def test_master_reset_runtime_state_invocation_uses_new_script() -> None:
    spec = master._resolve_command("reset-runtime-state")

    assert spec is not None
    assert spec.ensure_orchestrator is False
    invocation = master._build_invocation(spec, [])
    assert invocation == [
        sys.executable,
        "scripts/reset_runtime_state.py",
    ]
