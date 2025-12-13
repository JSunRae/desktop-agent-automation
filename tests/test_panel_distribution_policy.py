import math

from scripts.align_panels import MonitorInfo
from scripts.align_panels import _split_counts_evenly, _two_col_slots_with_optional_vertical_merge


def test_split_counts_evenly_balanced():
    assert _split_counts_evenly(0, 3) == [0, 0, 0]
    assert _split_counts_evenly(5, 2) == [3, 2]
    assert _split_counts_evenly(20, 3) == [7, 7, 6]


def test_two_col_slots_odd_merges_vertical():
    m = MonitorInfo(index=0, x=0, y=0, width=1080, height=1920, is_primary=True)
    slots = _two_col_slots_with_optional_vertical_merge(m, 5)

    assert len(slots) == 5

    heights = [s.height for s in slots]
    min_h = min(heights)
    max_h = max(heights)

    # With 5 panels: rows=3 => base height ~ 640; merged slot should be ~1280.
    assert max_h >= 2 * min_h - 2


def test_two_col_slots_even_no_merge():
    m = MonitorInfo(index=0, x=0, y=0, width=1080, height=1920, is_primary=True)
    slots = _two_col_slots_with_optional_vertical_merge(m, 6)

    assert len(slots) == 6

    heights = [s.height for s in slots]
    min_h = min(heights)
    max_h = max(heights)

    # With 6 panels: rows=3 => all slots should be close in height.
    assert max_h <= math.ceil(min_h * 1.05)
