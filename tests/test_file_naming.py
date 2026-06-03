"""Unit tests for utils/file_naming — deterministic, no I/O."""
from datetime import date

from utils.file_naming import general, speech


def test_general_basic():
    assert general("Tesla 自動駕駛調查", "Justin", "2026-04-07") == \
        "2026.04.07_Tesla 自動駕駛調查_Justin.docx"


def test_general_date_separators_normalised():
    # both "-" and "/" date strings normalise to dots
    assert general("X", "Justin", "2026/04/07") == "2026.04.07_X_Justin.docx"
    assert general("X", "Justin", date(2026, 4, 7)) == "2026.04.07_X_Justin.docx"


def test_general_multi_intern_joins_with_comma_space():
    # matches the documented fcc-shared shape "..._Justin, Neil.docx"
    out = general("X", ["Justin", "Neil"], "2026-04-07")
    assert out == "2026.04.07_X_Justin, Neil.docx"


def test_general_version_omitted_when_one():
    assert "v1" not in general("X", "Justin", "2026-04-07", version=1)
    assert "_v2_" in general("X", "Justin", "2026-04-07", version=2)


def test_general_sanitizes_invalid_chars():
    out = general('a/b:c*?"<>|d', "Justin", "2026-04-07")
    # no path/þillegal chars survive in the task-name segment
    for ch in '/\\:*?"<>|':
        assert ch not in out
    assert out.endswith("_Justin.docx")


def test_general_custom_extension():
    assert general("X", "Justin", "2026-04-07", ext="pptx").endswith(".pptx")


def test_speech_includes_version_and_dates():
    out = speech("2026-04-09", "2026-04-10", "台中智慧製造", "Justin", version=2)
    assert "演講" in out and "v2" in out and out.endswith(".docx")
