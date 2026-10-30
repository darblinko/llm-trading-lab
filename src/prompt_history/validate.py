"""Check a prompt-history tree against the record convention."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from prompt_history.record import FOLDER, RECORD_FILES


@dataclass(frozen=True)
class Issue:
    record: str
    problem: str


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NO_NEWLINE = "\\"


def apply_patch(before: str, diff_text: str) -> str | None:
    """Apply a single-file unified diff to `before`; None when a hunk does not apply.

    File headers are ignored, so diffs from diff -u, git diff and difflib all apply.
    Context and removed lines must match `before` at the hunk's stated position.
    """
    source = before.splitlines(keepends=True)
    lines = diff_text.splitlines(keepends=True)
    result: list[str] = []
    position, index = 0, 0
    while index < len(lines):
        match = _HUNK.match(lines[index])
        index += 1
        if match is None:
            continue
        old_start, old_count = int(match[1]), int(match[2] or 1)
        hunk_start = old_start - 1 if old_count else old_start
        if hunk_start < position or hunk_start > len(source):
            return None
        result += source[position:hunk_start]
        position = hunk_start
        applied = _apply_hunk(source, position, lines, index, old_count, int(match[4] or 1))
        if applied is None:
            return None
        added, position, index = applied
        result += added
    return "".join(result + source[position:])


def _apply_hunk(
    source: list[str], position: int, lines: list[str], index: int, old_left: int, new_left: int
) -> tuple[list[str], int, int] | None:
    """Return (output lines, next source position, next diff index) for one hunk."""
    output: list[str] = []
    while old_left > 0 or new_left > 0:
        if index >= len(lines):
            return None
        line = lines[index]
        index += 1
        tag, text = (line[:1], line[1:]) if line not in ("\n", "") else (" ", line)
        if tag in " -":
            if position >= len(source) or source[position].rstrip("\n") != text.rstrip("\n"):
                return None
            if tag == " ":
                output.append(source[position])
                new_left -= 1
            position, old_left = position + 1, old_left - 1
        elif tag == "+":
            output.append(text)
            new_left -= 1
        else:
            return None
        if index < len(lines) and lines[index].startswith(_NO_NEWLINE):
            index += 1
            if tag == "+":
                output[-1] = output[-1].rstrip("\n")
    return output, position, index


def rationale_issues(text: str) -> list[str]:
    lowered = text.lower()
    problems = []
    if "trigger" not in lowered:
        problems.append("rationale does not name a trigger")
    if "expected" not in lowered:
        problems.append("rationale does not state an expected behaviour change")
    if "falsif" not in lowered:
        problems.append("rationale does not state a falsifier")
    return problems


def record_issues(folder: Path, changelog: str | None) -> list[str]:
    problems = []
    if not FOLDER.match(folder.name):
        problems.append("folder name does not match YYYY-MM-DD_<prompt_name>_<slug>")
    missing = [name for name in RECORD_FILES if not (folder / name).is_file()]
    problems += [f"missing {name}" for name in missing]
    if {"before.md", "after.md", "diff.patch"} & set(missing):
        problems.append("diff not checked: a snapshot or the patch is missing")
    else:
        patched = apply_patch(
            (folder / "before.md").read_text(), (folder / "diff.patch").read_text()
        )
        if patched != (folder / "after.md").read_text():
            problems.append("diff.patch does not match before.md and after.md")
    if "rationale.md" in missing:
        problems.append("rationale not checked: rationale.md is missing")
    else:
        problems += rationale_issues((folder / "rationale.md").read_text())
    if changelog is not None and folder.name not in changelog:
        problems.append("not linked from the changelog")
    return problems


def validate_history(root: Path, changelog: str | None = None) -> list[Issue]:
    folders = sorted(p for p in root.iterdir() if p.is_dir())
    return [Issue(f.name, problem) for f in folders for problem in record_issues(f, changelog)]
