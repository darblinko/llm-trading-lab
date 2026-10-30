import csv
from datetime import date
from pathlib import Path

import pytest

from prompt_history.__main__ import main
from prompt_history.changelog import entry_problems, field_coverage, parse_entries
from prompt_history.index import NONCONFORMING, compliance, counts_by, write_index
from prompt_history.record import folder_name, record_change, unified_diff
from prompt_history.validate import apply_patch, validate_history

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "prompt_history"
DAY = date(2026, 1, 5)


def test_folder_name_enforces_convention():
    assert (
        folder_name(DAY, "entry_review", "add-volume-gate")
        == "2026-01-05_entry_review_add-volume-gate"
    )
    with pytest.raises(ValueError):
        folder_name(DAY, "Entry-Review", "add-volume-gate")
    with pytest.raises(ValueError):
        folder_name(DAY, "entry_review", "one")


def test_record_change_writes_four_files_and_refuses_overwrite(tmp_path):
    folder = record_change(tmp_path, DAY, "entry_review", "add-volume-gate", "a\n", "a\nb\n")
    assert sorted(p.name for p in folder.iterdir()) == [
        "after.md",
        "before.md",
        "diff.patch",
        "rationale.md",
    ]
    assert "+b" in (folder / "diff.patch").read_text()
    with pytest.raises(FileExistsError):
        record_change(tmp_path, DAY, "entry_review", "add-volume-gate", "a\n", "c\n")
    with pytest.raises(ValueError):
        record_change(tmp_path, DAY, "entry_review", "no-change-here", "a\n", "a\n")


def test_template_record_passes_until_snapshots_drift(tmp_path):
    folder = record_change(tmp_path, DAY, "entry_review", "add-volume-gate", "a\n", "a\nb\n")
    assert validate_history(tmp_path) == []
    (folder / "after.md").write_text("a\nc\n")
    problems = [i.problem for i in validate_history(tmp_path)]
    assert problems == ["diff.patch does not match before.md and after.md"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("a", "b"),
        ("a\n", "b"),
        ("a", "b\n"),
        ("a\n", "b\n"),
        ("x\na", "x\nb"),
        ("x\ny", "x\ny\nz"),
    ],
)
def test_recorded_patch_validates_for_every_trailing_newline_case(tmp_path, before, after):
    record_change(tmp_path, DAY, "entry_review", "edit-last-line", before, after)
    assert validate_history(tmp_path) == []
    assert apply_patch(before, unified_diff(before, after)) == after


def test_unified_diff_marks_a_missing_final_newline():
    diff = unified_diff("a", "b")
    assert "-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n" in diff


def test_apply_patch_ignores_headers_and_hunking():
    one = unified_diff("a\nb\nc\n", "a\nB\nc\n")
    other = "--- x\t2026-01-01\n+++ y\t2026-01-02\n@@ -2 +2 @@\n-b\n+B\n"
    assert apply_patch("a\nb\nc\n", one) == "a\nB\nc\n"
    assert apply_patch("a\nb\nc\n", other) == "a\nB\nc\n"


def test_patch_that_changes_the_wrong_line_is_rejected(tmp_path):
    folder = record_change(
        tmp_path, DAY, "entry_review", "capitalize-first-line", "a\nx\na\n", "A\nx\na\n"
    )
    (folder / "diff.patch").write_text(
        "--- before.md\n+++ after.md\n@@ -1,3 +1,3 @@\n a\n x\n-a\n+A\n"
    )
    assert apply_patch("a\nx\na\n", (folder / "diff.patch").read_text()) == "a\nx\nA\n"
    problems = [i.problem for i in validate_history(tmp_path)]
    assert problems == ["diff.patch does not match before.md and after.md"]


def test_apply_patch_rejects_context_that_does_not_match():
    patch = "@@ -1,2 +1,2 @@\n q\n-b\n+B\n"
    assert apply_patch("a\nb\n", patch) is None


def test_apply_patch_handles_insertion_at_start_and_missing_final_newline():
    assert apply_patch("a\n", "@@ -0,0 +1 @@\n+z\n") == "z\na\n"
    marker = "\\ No newline at end of file\n"
    patch = f"@@ -1,2 +1,2 @@\n a\n-b\n{marker}+c\n{marker}"
    assert apply_patch("a\nb", patch) == "a\nc"


def test_validate_reports_each_convention_break(tmp_path):
    bad = tmp_path / "2026-01-05-not_conforming"
    bad.mkdir()
    (bad / "rationale.md").write_text("# notes\n")
    problems = {i.problem for i in validate_history(tmp_path, changelog="")}
    assert {
        "folder name does not match YYYY-MM-DD_<prompt_name>_<slug>",
        "missing before.md",
        "diff not checked: a snapshot or the patch is missing",
        "rationale does not state a falsifier",
        "not linked from the changelog",
    } <= problems


def test_changelog_fields_and_pending_outcome():
    text = (EXAMPLES / "CHANGELOG.md").read_text() + (
        "\n## 2026-01-06 10:00 ET: partial entry\n\n**Trigger**: x\n"
        "**Outcome (filled in after 1 session)**: y\n"
    )
    first, second = parse_entries(text)
    assert entry_problems(first) == ([], True)
    missing, pending = entry_problems(second)
    assert "Files" in missing and not pending
    assert field_coverage([first, second])["Trigger"] == 2


def test_example_tree_is_clean_and_indexes(tmp_path, capsys):
    records = EXAMPLES / "records"
    changelog = EXAMPLES / "CHANGELOG.md"
    assert main(["validate", "--root", str(records), "--changelog", str(changelog)]) == 0
    assert all(passing == total for _, passing, total in compliance(records, changelog.read_text()))
    assert counts_by(records, "prompt") == {"entry_review": 1}
    paths = write_index(records, changelog, tmp_path)
    with paths[1].open() as handle:
        assert list(csv.reader(handle)) == [["month", "records"], ["2026-01", "1"]]
    capsys.readouterr()


def test_counts_by_prompt_marks_nonconforming(tmp_path):
    (tmp_path / "2026-02-01-free-form-name").mkdir()
    assert counts_by(tmp_path, "prompt") == {NONCONFORMING: 1}
    assert counts_by(tmp_path, "month") == {"2026-02": 1}


def test_cli_record(tmp_path, capsys):
    before, after = tmp_path / "b.md", tmp_path / "a.md"
    before.write_text("x\n")
    after.write_text("y\n")
    root = tmp_path / "history"
    assert (
        main(
            [
                "record",
                "--root",
                str(root),
                "--prompt",
                "p",
                "--slug",
                "make-change",
                "--before",
                str(before),
                "--after",
                str(after),
                "--date",
                "2026-01-05",
            ]
        )
        == 0
    )
    assert (root / "2026-01-05_p_make-change" / "diff.patch").exists()
    assert "created" in capsys.readouterr().out
