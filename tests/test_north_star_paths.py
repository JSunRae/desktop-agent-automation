from __future__ import annotations

from pathlib import Path

from automation.north_star import _resolve_north_star_cache_path


def test_resolve_north_star_cache_path_honors_env_override(monkeypatch, tmp_path: Path) -> None:
    override_path = tmp_path / "north_star_cache.json"
    monkeypatch.setenv("NORTH_STAR_CACHE_PATH", str(override_path))

    assert _resolve_north_star_cache_path() == override_path
