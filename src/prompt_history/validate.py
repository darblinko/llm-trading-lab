"""Check a prompt-history tree against the record convention."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from prompt_history.record import FOLDER, RECORD_FILES, unified_diff


@dataclass(frozen=True)
class Issue:
    record: str
    problem: str


def changed_lines(diff_text: str) -> Counter:
    """Added and removed lines of a unified diff, as a multiset.

    File headers, hunk markers and context are ignored, so diffs produced by different tools
    (diff -u, git diff, difflib) of the same two files compare equal.
    """
    lines = diff_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("@@")), len(lines))
    return Counter(
        line.rstrip()
        for line in lines[start:]
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


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
        expected = unified_diff(
            (folder / "before.md").read_text(), (folder / "after.md").read_text()
        )
        if changed_lines((folder / "diff.patch").read_text()) != changed_lines(expected):
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
