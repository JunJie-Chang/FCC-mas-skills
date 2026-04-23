"""
utils/file_naming.py — Unified filename generation.

Observed naming convention from Works/:
  General:  YYYY.MM.DD_TaskName_InternName.docx
  Multiple: YYYY.MM.DD_TaskName_Justin,Neil,Ethan.docx
  Version:  YYYY.MM.DD_TaskName_v2_InternName.docx  (omitted when version=1)

  Speech:   {speech_date}演講_{edit_date}_{title}_v{n}_InternName.docx
            (version always included for speech files)
"""
import re
from datetime import date as _date_type
from typing import Union

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize(name: str) -> str:
    """Replace characters that are invalid in file/folder names."""
    return _INVALID_CHARS.sub("-", name).strip()


def _format_date(d: Union[str, _date_type]) -> str:
    """Accept a date object or a string in any common format → YYYY.MM.DD."""
    if isinstance(d, _date_type):
        return d.strftime("%Y.%m.%d")
    # Already a string — normalise separators
    return str(d).replace("-", ".").replace("/", ".")


def _intern_str(intern_name: Union[str, list[str]]) -> str:
    names = intern_name if isinstance(intern_name, list) else [intern_name]
    return ",".join(_sanitize(n) for n in names)


def general(
    task_name: str,
    intern_name: Union[str, list[str]],
    task_date: Union[str, _date_type] = None,
    version: int = None,
    ext: str = "docx",
) -> str:
    """
    Build a filename for a general task output.

    Args:
        task_name:    Human-readable task description (spaces allowed).
        intern_name:  Single name string or list of names.
        task_date:    Date of the task; defaults to today.
        version:      Version number; omitted from filename when None or 1.
        ext:          File extension without the dot (default 'docx').

    Returns:
        Filename string, e.g. '2026.04.07_Tesla 自動駕駛調查_Justin.docx'
    """
    d = _format_date(task_date or _date_type.today())
    intern = _intern_str(intern_name)
    parts = [d, _sanitize(task_name)]
    if version and version > 1:
        parts.append(f"v{version}")
    parts.append(intern)
    return "_".join(parts) + f".{ext}"


def speech(
    speech_date: Union[str, _date_type],
    edit_date: Union[str, _date_type],
    title: str,
    intern_name: Union[str, list[str]],
    version: int = 1,
    ext: str = "docx",
) -> str:
    """
    Build a filename for a speech/演講 file.

    Args:
        speech_date:  Date of the speech.
        edit_date:    Date of this edit/revision.
        title:        Content name / topic.
        intern_name:  Single name string or list of names.
        version:      Version number (always included for speech files).
        ext:          File extension without the dot (default 'docx').

    Returns:
        Filename string, e.g. '2026.04.10演講_2026.04.07_AI產業趨勢_v1_Justin.docx'
    """
    sd = _format_date(speech_date)
    ed = _format_date(edit_date)
    intern = _intern_str(intern_name)
    return f"{sd}演講_{ed}_{title}_v{version}_{intern}.{ext}"
