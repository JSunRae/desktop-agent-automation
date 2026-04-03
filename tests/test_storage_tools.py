"""Tests for automation.diagnose_storage and automation.cleanup_storage.

Covers path filtering, repo selection, dry-run behaviour, execute
confirmations, summary accounting, and the regression guardrail that
repo-scoped mode never touches non-selected repos.

All filesystem access is mocked — tests are deterministic and fast.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from automation.cleanup_storage import (
    CleanupCandidate,
    CleanupResult,
    _categorize,
    _is_protected,
    _matches_category,
    _matches_repo_filters,
    _refuse_dangerous,
    collect_candidates,
    execute_cleanup,
    print_preview,
    print_result,
)
from automation.cleanup_storage import (
    cli_main as cleanup_cli_main,
)

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
from automation.diagnose_storage import (
    DiagnosisReport,
    WorkspaceEntry,
    _build_recommendations,
    _format_bytes,
    _repo_name_from_path,
    _severity,
    print_report,
)
from automation.diagnose_storage import cli_main as diagnose_cli_main

# ============================================================================
# diagnose_storage tests
# ============================================================================

class TestFormatBytes:
    def test_bytes(self) -> None:
        assert _format_bytes(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert "KB" in _format_bytes(2048)

    def test_megabytes(self) -> None:
        assert "MB" in _format_bytes(5 * 1024 * 1024)

    def test_gigabytes(self) -> None:
        assert "GB" in _format_bytes(3 * 1024 ** 3)


class TestSeverity:
    def test_ok(self) -> None:
        assert _severity(50 * 1024 * 1024) == "ok"

    def test_warn(self) -> None:
        assert _severity(200 * 1024 * 1024) == "warn"

    def test_critical(self) -> None:
        assert _severity(600 * 1024 * 1024) == "critical"


class TestRepoNameFromPath:
    def test_normal_path(self) -> None:
        assert _repo_name_from_path("/home/user/repos/my-project") == "my-project"

    def test_trailing_slash(self) -> None:
        assert _repo_name_from_path("C:\\Users\\Pilot\\my-repo\\") == "my-repo"

    def test_none(self) -> None:
        assert _repo_name_from_path(None) is None

    def test_empty(self) -> None:
        assert _repo_name_from_path("") is None


class TestBuildRecommendations:
    def test_healthy(self) -> None:
        entries = [WorkspaceEntry(
            folder_name="abc", folder_path="/tmp/abc",
            size_bytes=10 * 1024 * 1024, file_count=5, severity="ok",
        )]
        recs = _build_recommendations(entries, 10 * 1024 * 1024)
        assert any("healthy" in r.lower() for r in recs)

    def test_critical_flagged(self) -> None:
        entries = [WorkspaceEntry(
            folder_name="big", folder_path="/tmp/big",
            size_bytes=800 * 1024 * 1024, file_count=100,
            severity="critical", repo_name="big-repo",
        )]
        recs = _build_recommendations(entries, 800 * 1024 * 1024)
        assert any("critical" in r.lower() for r in recs)


class TestDiagnoseReportJson:
    """Verify JSON serialisation round-trips."""

    def test_roundtrip(self) -> None:
        report = DiagnosisReport(
            timestamp="2026-01-01T00:00:00+00:00",
            hostname="test-host",
            roots_scanned=["/tmp/root"],
            total_size_bytes=1024,
            workspace_count=1,
            entries=[WorkspaceEntry(
                folder_name="ws1", folder_path="/tmp/root/ws1",
                size_bytes=1024, file_count=2, severity="ok",
            )],
            severity_counts={"ok": 1, "warn": 0, "critical": 0},
            recommendations=["All good."],
        )
        from dataclasses import asdict
        blob = json.dumps(asdict(report), default=str)
        parsed = json.loads(blob)
        assert parsed["hostname"] == "test-host"
        assert parsed["workspace_count"] == 1


# ============================================================================
# cleanup_storage tests
# ============================================================================

class TestCategorize:
    def test_cache(self) -> None:
        assert _categorize("CachedData") == "cache"

    def test_logs(self) -> None:
        assert _categorize("logs") == "logs"

    def test_unknown(self) -> None:
        assert _categorize("randomFolder") == "other"


class TestMatchesCategory:
    def test_include_match(self) -> None:
        assert _matches_category("Cache", include={"cache"}, exclude=None) is True

    def test_include_no_match(self) -> None:
        assert _matches_category("logs", include={"cache"}, exclude=None) is False

    def test_exclude_match(self) -> None:
        assert _matches_category("logs", include=None, exclude={"logs"}) is False

    def test_no_filters(self) -> None:
        assert _matches_category("anything", include=None, exclude=None) is True


class TestMatchesRepoFilters:
    def test_name_match(self) -> None:
        assert _matches_repo_filters(
            "my-project", "/home/user/my-project", "abc123",
            repo_names={"my-project"},
        ) is True

    def test_name_no_match(self) -> None:
        assert _matches_repo_filters(
            "other-repo", "/home/user/other-repo", "abc123",
            repo_names={"my-project"},
        ) is False

    def test_exclude_repo(self) -> None:
        assert _matches_repo_filters(
            "my-project", "/home/user/my-project", "abc123",
            exclude_repos={"my-project"},
        ) is False

    def test_hash_prefix(self) -> None:
        assert _matches_repo_filters(
            "repo", "/path", "abc123def",
            hash_prefixes={"abc123"},
        ) is True

    def test_hash_prefix_no_match(self) -> None:
        assert _matches_repo_filters(
            "repo", "/path", "xyz789",
            hash_prefixes={"abc123"},
        ) is False

    def test_regex_match(self) -> None:
        pattern = re.compile(r"my-proj", re.IGNORECASE)
        assert _matches_repo_filters(
            "my-project", "/home/user/my-project", "abc",
            repo_regex=pattern,
        ) is True

    def test_regex_no_match(self) -> None:
        pattern = re.compile(r"^trading$", re.IGNORECASE)
        assert _matches_repo_filters(
            "my-project", "/home/user/my-project", "abc",
            repo_regex=pattern,
        ) is False

    def test_no_filters_passes(self) -> None:
        assert _matches_repo_filters("any", "/any", "any") is True


class TestIsProtected:
    def test_settings(self) -> None:
        assert _is_protected(Path("C:/Code/User/settings.json")) is True

    def test_extensions(self) -> None:
        assert _is_protected(Path("/home/.config/Code/extensions/ms-python")) is True

    def test_normal_cache(self) -> None:
        assert _is_protected(Path("/home/.cache/Code/Cache/abc")) is False


class TestRefuseDangerous:
    """Ensure dangerous paths are refused."""

    def test_nonexistent(self, tmp_path: Path) -> None:
        assert _refuse_dangerous(tmp_path / "nonexistent") is not None

    def test_filesystem_root(self, tmp_path: Path) -> None:
        with mock.patch("automation.cleanup_storage.Path.exists", return_value=True):
            reason = _refuse_dangerous(Path("/"))
        assert reason is not None

    def test_outside_approved(self, tmp_path: Path) -> None:
        p = tmp_path / "somefile"
        p.mkdir()
        reason = _refuse_dangerous(p)
        assert reason is not None and "outside" in reason


# ---------------------------------------------------------------------------
# Dry-run behaviour
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace" / "abc123"
        target.mkdir(parents=True)
        (target / "data.txt").write_text("hello")

        candidates = [CleanupCandidate(
            path=str(target),
            size_bytes=5,
            file_count=1,
            category="workspaceStorage",
            reason="test",
        )]
        result = execute_cleanup(candidates, dry_run=True)

        assert result.dry_run is True
        assert result.candidates_deleted == 0
        assert result.candidates_skipped == len(candidates)
        assert target.exists(), "dry-run must not delete anything"

    def test_dry_run_reports_reclaimable(self) -> None:
        candidates = [
            CleanupCandidate(path="/fake/a", size_bytes=100, file_count=1, category="cache", reason="old"),
            CleanupCandidate(path="/fake/b", size_bytes=200, file_count=2, category="logs", reason="old"),
        ]
        result = execute_cleanup(candidates, dry_run=True)
        assert result.bytes_reclaimable == 300


# ---------------------------------------------------------------------------
# Execute + confirmation
# ---------------------------------------------------------------------------

class TestExecuteCleanup:
    def test_execute_with_safe_target(self, tmp_path: Path) -> None:
        """Deletion within an approved root succeeds."""
        target = tmp_path / "Code" / "Cache" / "old_cache"
        target.mkdir(parents=True)
        (target / "file.bin").write_bytes(b"x" * 100)

        candidates = [CleanupCandidate(
            path=str(target),
            size_bytes=100,
            file_count=1,
            category="cache",
            reason="test",
        )]

        # Patch _is_safe_target to allow our tmp directory
        with mock.patch("automation.cleanup_storage._is_safe_target", return_value=True), \
             mock.patch("automation.cleanup_storage._is_protected", return_value=False):
            result = execute_cleanup(candidates, dry_run=False, confirm_fn=lambda _: True)

        assert result.candidates_deleted == 1
        assert result.bytes_reclaimed == 100
        assert not target.exists()

    def test_execute_refuses_outside_root(self, tmp_path: Path) -> None:
        """Deletion outside approved roots is refused."""
        target = tmp_path / "not_vscode" / "data"
        target.mkdir(parents=True)
        (target / "file.txt").write_text("keep me")

        candidates = [CleanupCandidate(
            path=str(target),
            size_bytes=7,
            file_count=1,
            category="other",
            reason="test",
        )]

        result = execute_cleanup(candidates, dry_run=False, confirm_fn=lambda _: True)
        assert result.candidates_errored == 1
        assert target.exists(), "must not delete outside approved roots"

    def test_confirm_each_denied(self, tmp_path: Path) -> None:
        """Per-item denial skips that item."""
        target = tmp_path / "ws"
        target.mkdir()
        (target / "f.txt").write_text("data")

        candidates = [CleanupCandidate(
            path=str(target), size_bytes=4, file_count=1,
            category="workspaceStorage", reason="test",
        )]

        with mock.patch("automation.cleanup_storage._is_safe_target", return_value=True), \
             mock.patch("automation.cleanup_storage._is_protected", return_value=False):
            result = execute_cleanup(
                candidates, dry_run=False, confirm_each=True,
                confirm_fn=lambda _: False,
            )

        assert result.candidates_skipped == 1
        assert result.candidates_deleted == 0
        assert target.exists()


# ---------------------------------------------------------------------------
# Summary accounting
# ---------------------------------------------------------------------------

class TestSummaryAccounting:
    def test_repo_summaries(self) -> None:
        candidates = [
            CleanupCandidate(
                path="/a", size_bytes=100, file_count=1,
                repo_name="repo-a", category="cache", reason="old",
            ),
            CleanupCandidate(
                path="/b", size_bytes=200, file_count=2,
                repo_name="repo-a", category="logs", reason="old",
            ),
            CleanupCandidate(
                path="/c", size_bytes=50, file_count=1,
                repo_name="repo-b", category="cache", reason="old",
            ),
        ]
        result = execute_cleanup(candidates, dry_run=True)
        assert result.bytes_reclaimable == 350
        assert len(result.repo_summaries) == 2
        # repo-a should be first (300 bytes)
        assert result.repo_summaries[0].repo_name == "repo-a"
        assert result.repo_summaries[0].reclaimable_bytes == 300

    def test_total_matches_sum(self) -> None:
        candidates = [
            CleanupCandidate(path=f"/item{i}", size_bytes=i * 10, file_count=1,
                             category="cache", reason="old")
            for i in range(1, 6)
        ]
        result = execute_cleanup(candidates, dry_run=True)
        expected = sum(c.size_bytes for c in candidates)
        assert result.bytes_reclaimable == expected


# ---------------------------------------------------------------------------
# Regression: repo-scoped mode must not touch non-selected repos
# ---------------------------------------------------------------------------

class TestRepoScopedIsolation:
    """Ensure that filtering by repo name/hash/regex never leaks candidates
    from non-matching repos."""

    def _make_ws_dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create two fake workspace dirs with workspace.json files and old mtimes."""
        root = tmp_path / "workspaceStorage"
        root.mkdir(parents=True)

        ws_a = root / "aaaa1111"
        ws_a.mkdir()
        (ws_a / "workspace.json").write_text(json.dumps({"folder": "file:///C%3A/repos/project-alpha"}))
        data_a = ws_a / "data.bin"
        data_a.write_bytes(b"x" * 50)

        ws_b = root / "bbbb2222"
        ws_b.mkdir()
        (ws_b / "workspace.json").write_text(json.dumps({"folder": "file:///C%3A/repos/project-beta"}))
        data_b = ws_b / "data.bin"
        data_b.write_bytes(b"y" * 50)

        # Set modification times to 90 days ago so they pass the age filter
        old_time = (datetime.now(tz=timezone.utc) - timedelta(days=90)).timestamp()
        for f in [data_a, ws_a / "workspace.json", data_b, ws_b / "workspace.json"]:
            os.utime(f, (old_time, old_time))

        return ws_a, ws_b

    def test_repo_name_filter_isolates(self, tmp_path: Path) -> None:
        ws_a, ws_b = self._make_ws_dirs(tmp_path)
        root = ws_a.parent

        # Patch VSCODE_STORAGE_ROOTS to point to our tmp dir
        with mock.patch("automation.cleanup_storage.VSCODE_STORAGE_ROOTS", [root]), \
             mock.patch("automation.diagnose_storage.VSCODE_STORAGE_ROOTS", [root]):
            candidates = collect_candidates(
                older_than_days=0,
                repo_names={"project-alpha"},
            )

        paths = {c.path for c in candidates}
        assert str(ws_a) in paths or any("aaaa1111" in p for p in paths), \
            "project-alpha workspace should be included"
        assert not any("bbbb2222" in p for p in paths), \
            "project-beta workspace must NOT be touched when filtering for alpha"

    def test_hash_prefix_filter_isolates(self, tmp_path: Path) -> None:
        ws_a, ws_b = self._make_ws_dirs(tmp_path)
        root = ws_a.parent

        with mock.patch("automation.cleanup_storage.VSCODE_STORAGE_ROOTS", [root]), \
             mock.patch("automation.diagnose_storage.VSCODE_STORAGE_ROOTS", [root]):
            candidates = collect_candidates(
                older_than_days=0,
                hash_prefixes={"aaaa"},
            )

        paths = {c.path for c in candidates}
        assert not any("bbbb2222" in p for p in paths), \
            "hash-prefix filter must isolate to matching hashes only"

    def test_regex_filter_isolates(self, tmp_path: Path) -> None:
        ws_a, ws_b = self._make_ws_dirs(tmp_path)
        root = ws_a.parent

        with mock.patch("automation.cleanup_storage.VSCODE_STORAGE_ROOTS", [root]), \
             mock.patch("automation.diagnose_storage.VSCODE_STORAGE_ROOTS", [root]):
            candidates = collect_candidates(
                older_than_days=0,
                repo_regex=re.compile(r"alpha"),
            )

        paths = {c.path for c in candidates}
        assert not any("bbbb2222" in p for p in paths), \
            "regex filter must isolate to matching repos only"

    def test_exclude_repo_isolates(self, tmp_path: Path) -> None:
        ws_a, ws_b = self._make_ws_dirs(tmp_path)
        root = ws_a.parent

        with mock.patch("automation.cleanup_storage.VSCODE_STORAGE_ROOTS", [root]), \
             mock.patch("automation.diagnose_storage.VSCODE_STORAGE_ROOTS", [root]):
            candidates = collect_candidates(
                older_than_days=0,
                exclude_repos={"project-alpha"},
            )

        paths = {c.path for c in candidates}
        assert not any("aaaa1111" in p for p in paths), \
            "excluded repo must not appear in candidates"


# ---------------------------------------------------------------------------
# CLI smoke tests (argument parsing only, no real FS)
# ---------------------------------------------------------------------------

class TestDiagnoseCli:
    def test_help_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            diagnose_cli_main(["--help"])
        assert exc_info.value.code == 0

    def test_default_runs(self) -> None:
        with mock.patch("automation.diagnose_storage.scan_workspaces") as m_scan, \
             mock.patch("automation.diagnose_storage.print_report"):
            m_scan.return_value = DiagnosisReport(
                timestamp="t", hostname="h", roots_scanned=[], total_size_bytes=0,
                workspace_count=0, entries=[], severity_counts={}, recommendations=[],
            )
            rc = diagnose_cli_main([])
        assert rc == 0


class TestCleanupCli:
    def test_help_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cleanup_cli_main(["--help"])
        assert exc_info.value.code == 0

    def test_dry_run_default(self) -> None:
        with mock.patch("automation.cleanup_storage.collect_candidates", return_value=[]), \
             mock.patch("automation.cleanup_storage.execute_cleanup") as m_exec, \
             mock.patch("automation.cleanup_storage.print_result"):
            m_exec.return_value = CleanupResult(dry_run=True)
            rc = cleanup_cli_main([])
        assert rc == 0
        m_exec.assert_called_once()
        assert m_exec.call_args[1]["dry_run"] is True


# ---------------------------------------------------------------------------
# Output formatting smoke tests
# ---------------------------------------------------------------------------

class TestOutputFormatting:
    def test_print_report_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = DiagnosisReport(
            timestamp="t", hostname="h", roots_scanned=[], total_size_bytes=0,
            workspace_count=0, entries=[], severity_counts={"ok": 0, "warn": 0, "critical": 0},
            recommendations=[],
        )
        print_report(report, as_json=True)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "hostname" in parsed

    def test_print_result_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = CleanupResult(dry_run=True, timestamp="t", bytes_reclaimable=999)
        print_result(result, as_json=True)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["bytes_reclaimable"] == 999

    def test_print_preview_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_preview([])
        out = capsys.readouterr().out
        assert "no cleanup candidates" in out.lower()
