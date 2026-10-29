"""Aggregate a prompt-history tree into counts. The outputs carry no record text."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

from prompt_history.changelog import field_coverage, parse_entries
from prompt_history.record import FOLDER
from prompt_history.validate import record_issues

DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")

RATIONALE_MISSING = "rationale not checked"
CHECKS = (
    ("follows_naming_convention", ("folder name does not match",)),
    ("has_all_four_files", ("missing ",)),
    ("diff_matches_snapshots", ("diff.patch does not match", "diff not checked")),
    ("names_trigger", ("does not name a trigger", RATIONALE_MISSING)),
    ("states_expected_change", ("does not state an expected", RATIONALE_MISSING)),
    ("states_falsifier", ("does not state a falsifier", RATIONALE_MISSING)),
    ("linked_from_changelog", ("not linked from the changelog",)),
)


def compliance(root: Path, changelog: str) -> list[tuple[str, int, int]]:
    """(check, records passing, records checked) for each convention check."""
    folders = sorted(p for p in root.iterdir() if p.is_dir())
    problems = [record_issues(folder, changelog) for folder in folders]
    rows = []
    for name, markers in CHECKS:
        passing = sum(1 for found in problems if not any(m in p for p in found for m in markers))
        rows.append((name, passing, len(folders)))
    return rows


NONCONFORMING = "(name outside convention)"


def counts_by(root: Path, part: str) -> Counter:
    """Records per month ("month") or per prompt name ("prompt"), from folder names.

    A folder whose name breaks the convention still counts toward its month when it starts
    with a date, and counts under NONCONFORMING for the prompt breakdown.
    """
    counter: Counter = Counter()
    for folder in (p for p in root.iterdir() if p.is_dir()):
        match = FOLDER.match(folder.name)
        if part == "prompt":
            counter[match.group(2) if match else NONCONFORMING] += 1
        elif DATE_PREFIX.match(folder.name):
            counter[folder.name[:7]] += 1
    return counter


def write_csv(path: Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_index(root: Path, changelog_path: Path, out_dir: Path) -> list[Path]:
    changelog = changelog_path.read_text()
    entries = parse_entries(changelog)
    coverage = [
        (f"changelog_field_{k.lower().replace(' ', '_')}", v, len(entries))
        for k, v in field_coverage(entries).items()
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "prompt_history_compliance.csv": (
            ("check", "passing", "of"),
            compliance(root, changelog) + coverage,
        ),
        "prompt_history_by_month.csv": (
            ("month", "records"),
            sorted(counts_by(root, "month").items()),
        ),
        "prompt_history_by_prompt.csv": (
            ("prompt_name", "records"),
            counts_by(root, "prompt").most_common(),
        ),
    }
    for name, (header, rows) in outputs.items():
        write_csv(out_dir / name, header, rows)
    return [out_dir / name for name in outputs]
