from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent
LIVE_DESKTOP_PATTERN = re.compile(
    r"\b(?:import|from)\s+(?:uiautomation|keyboard|pyvda)\b|ctypes\.windll\.user32"
)
ORCHESTRATION_PREFIX = "test_orchestration_v1_"


@lru_cache(maxsize=None)
def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


@lru_cache(maxsize=None)
def _looks_like_pytest_module(path: Path) -> bool:
    text = _read_text(path)
    return "def test_" in text or "unittest.TestCase" in text


@lru_cache(maxsize=None)
def _uses_live_desktop(path: Path) -> bool:
    return bool(LIVE_DESKTOP_PATTERN.search(_read_text(path)))


def _relative_to_repo(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return path


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    path = Path(collection_path)
    if path.suffix != ".py" or not path.name.startswith("test"):
        return False

    relative_path = _relative_to_repo(path)
    if "debug" in relative_path.parts:
        return True

    return not _looks_like_pytest_module(path)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("unit") or item.get_closest_marker("orchestration") or item.get_closest_marker("desktop"):
            continue

        path = Path(str(item.path))
        if path.name.startswith(ORCHESTRATION_PREFIX):
            item.add_marker(pytest.mark.orchestration)
            continue

        if _uses_live_desktop(path):
            item.add_marker(pytest.mark.desktop)
            continue

        item.add_marker(pytest.mark.unit)