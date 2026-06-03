"""Tests for utils/spec_io — the path-safety boundary for build specs."""
import json

import pytest

from utils.spec_io import load_spec, safe_filename, safe_subdir


@pytest.mark.parametrize("value,expected", [
    ("adhoc", "adhoc"),
    ("daily", "daily"),
    ("weekly", "weekly"),
    ("../../etc", "adhoc"),        # traversal → default
    ("/abs/path", "adhoc"),
    ("", "adhoc"),
    (None, "adhoc"),
    ("nonsense", "adhoc"),
])
def test_safe_subdir(value, expected):
    assert safe_subdir(value) == expected


def test_safe_subdir_respects_default():
    assert safe_subdir(None, "weekly") == "weekly"
    assert safe_subdir("bogus", "weekly") == "weekly"


@pytest.mark.parametrize("value,expected", [
    ("report.docx", "report.docx"),
    ("../../evil.docx", "evil.docx"),
    ("/abs/dir/x.docx", "x.docx"),
    ("a/b/c.docx", "c.docx"),
])
def test_safe_filename_strips_dirs(value, expected):
    assert safe_filename(value) == expected


def test_safe_filename_empty_falls_back():
    assert safe_filename("") == "untitled"
    assert safe_filename("/") == "untitled"


def test_load_spec_from_file(tmp_path):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps({"title": "T"}), encoding="utf-8")
    assert load_spec(str(p)) == {"title": "T"}
