"""Create one change record per prompt edit.

Layout: <root>/YYYY-MM-DD_<prompt_name>_<short-slug>/ holding before.md, after.md,
diff.patch (unified diff of the two) and rationale.md (trigger, enforced rule, expected
behaviour change, falsifier).
"""

from __future__ import annotations

import difflib
import re
from datetime import date
from pathlib import Path

RECORD_FILES = ("before.md", "after.md", "diff.patch", "rationale.md")
PROMPT_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){1,4}$")
FOLDER = re.compile(r"^(\d{4}-\d{2}-\d{2})_([a-z][a-z0-9_]*?)_([a-z0-9]+(?:-[a-z0-9]+){1,4})$")

RATIONALE_TEMPLATE = """# Rationale: {title}

## Trigger

Which review, incident or measurement prompted this change.

## What the new text enforces

The rule the added or changed text is meant to impose.

## Expected behavior change

What the agent should now do differently, stated so it can be counted in the logs.

## Falsifier

The observation over the next sessions that would show the change did not work.

## Cross-references

Changelog entry and related records.
"""


def folder_name(day: date, prompt_name: str, slug: str) -> str:
    if not PROMPT_NAME.match(prompt_name):
        raise ValueError(f"prompt name must be snake_case: {prompt_name!r}")
    if not SLUG.match(slug):
        raise ValueError(f"slug must be 2 to 5 kebab-case words: {slug!r}")
    return f"{day.isoformat()}_{prompt_name}_{slug}"


NO_NEWLINE_MARKER = "\\ No newline at end of file\n"


def unified_diff(before: str, after: str) -> str:
    """Unified diff of two snapshots, with a marker after a last line that has no newline."""
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="before.md",
        tofile="after.md",
    )
    return "".join(
        line if line.endswith("\n") else line + "\n" + NO_NEWLINE_MARKER for line in lines
    )


def record_change(
    root: Path,
    day: date,
    prompt_name: str,
    slug: str,
    before: str,
    after: str,
) -> Path:
    """Write a new change record and return its folder. Refuses to overwrite one."""
    if before == after:
        raise ValueError("before and after are identical; nothing to record")
    folder = root / folder_name(day, prompt_name, slug)
    folder.mkdir(parents=True, exist_ok=False)
    title = slug.replace("-", " ")
    contents = {
        "before.md": before,
        "after.md": after,
        "diff.patch": unified_diff(before, after),
        "rationale.md": RATIONALE_TEMPLATE.format(title=f"{prompt_name} {title}"),
    }
    for name, text in contents.items():
        (folder / name).write_text(text)
    return folder
