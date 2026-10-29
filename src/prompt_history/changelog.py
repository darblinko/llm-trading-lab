"""Check that every changelog entry carries the template fields.

An entry starts with "## YYYY-MM-DD" and fields are bold labels such as **Trigger**:.
Outcome is filled in after at least one session, so a missing Outcome is reported as pending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REQUIRED_FIELDS = (
    "Files",
    "Trigger",
    "Change",
    "Why",
    "Contradiction check",
    "Validation",
    "Status",
)
DEFERRED_FIELD = "Outcome"
ENTRY_START = re.compile(r"^## (\d{4}-\d{2}-\d{2}.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Entry:
    heading: str
    fields: frozenset[str]


def parse_entries(text: str) -> list[Entry]:
    starts = list(ENTRY_START.finditer(text))
    entries = []
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        body = text[match.end() : end]
        labels = re.findall(r"\*\*([A-Za-z][A-Za-z ]*?)(?: \([^)]*\))?\*\*\s*:", body)
        entries.append(Entry(match.group(1).strip(), frozenset(labels)))
    return entries


def entry_problems(entry: Entry) -> tuple[list[str], bool]:
    """(missing required fields, whether the outcome is still pending)."""
    missing = [name for name in REQUIRED_FIELDS if name not in entry.fields]
    return missing, DEFERRED_FIELD not in entry.fields


def field_coverage(entries: list[Entry]) -> dict[str, int]:
    names = REQUIRED_FIELDS + (DEFERRED_FIELD,)
    return {name: sum(1 for e in entries if name in e.fields) for name in names}
