"""Prompt change records.

Usage:
  python -m prompt_history record --root DIR --prompt NAME --slug SLUG --before F --after F
  python -m prompt_history validate --root DIR [--changelog CHANGELOG.md]
  python -m prompt_history index --root DIR --changelog CHANGELOG.md --out-dir DIR
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from prompt_history.changelog import entry_problems, parse_entries
from prompt_history.index import write_index
from prompt_history.record import record_change
from prompt_history.validate import validate_history


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prompt_history")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    record.add_argument("--root", type=Path, required=True)
    record.add_argument("--prompt", required=True)
    record.add_argument("--slug", required=True)
    record.add_argument("--before", type=Path, required=True)
    record.add_argument("--after", type=Path, required=True)
    record.add_argument("--date", type=date.fromisoformat, default=date.today())
    validate = sub.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--changelog", type=Path)
    index = sub.add_parser("index")
    index.add_argument("--root", type=Path, required=True)
    index.add_argument("--changelog", type=Path, required=True)
    index.add_argument("--out-dir", type=Path, required=True)
    return parser


def run_validate(root: Path, changelog_path: Path | None) -> int:
    changelog = changelog_path.read_text() if changelog_path else None
    issues = validate_history(root, changelog)
    for issue in issues:
        print(f"{issue.record}: {issue.problem}")
    failures = len(issues)
    if changelog is not None:
        for entry in parse_entries(changelog):
            missing, pending = entry_problems(entry)
            failures += bool(missing)
            if missing:
                print(f"changelog '{entry.heading}': missing {', '.join(missing)}")
            if pending:
                print(f"changelog '{entry.heading}': outcome pending")
    print(f"{failures} problem(s)")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "record":
        folder = record_change(
            args.root,
            args.date,
            args.prompt,
            args.slug,
            args.before.read_text(),
            args.after.read_text(),
        )
        print(f"created {folder}; fill in {folder / 'rationale.md'}")
        return 0
    if args.command == "validate":
        return run_validate(args.root, args.changelog)
    for path in write_index(args.root, args.changelog, args.out_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
