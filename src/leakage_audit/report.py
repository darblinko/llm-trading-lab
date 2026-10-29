"""Run every audit on a bar file and render a markdown report."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from leakage_audit.barrier import (
    CHOP_THRESHOLD,
    DIAGNOSTIC,
    YearBalance,
    balance_by_year,
    triple_barrier_labels,
    vertical_share,
)
from leakage_audit.correlation import CorrelationFinding, correlation_audit
from leakage_audit.overlap import OverlapFinding, label_overlap
from leakage_audit.truncation import (
    FeatureFn,
    TruncationFinding,
    default_cut_points,
    truncation_audit,
)


@dataclass(frozen=True)
class AuditResult:
    correlation: list[CorrelationFinding]
    truncation: list[TruncationFinding]
    overlap: list[OverlapFinding]
    balance: list[YearBalance] = field(default_factory=list)
    vertical: float | None = None

    @property
    def leak_found(self) -> bool:
        overlapping = any(f.overlapping_rows for f in self.overlap)
        return bool(self.correlation or self.truncation or overlapping)


def run_audit(
    bars: pd.DataFrame,
    feature_fn: FeatureFn,
    feature_columns: list[str],
    target: str,
    folds: list,
    horizon: int,
    barrier: tuple[float, float, int] | None = None,
) -> AuditResult:
    featured = feature_fn(bars)
    correlation = correlation_audit(featured[feature_columns + [target]], target)
    truncation = truncation_audit(bars, feature_fn, feature_columns, default_cut_points(len(bars)))
    overlap = label_overlap(folds, horizon)
    if barrier is None:
        return AuditResult(correlation, truncation, overlap)
    labels = triple_barrier_labels(bars, *barrier)
    balance = balance_by_year(labels, bars["timestamp"], DIAGNOSTIC)
    return AuditResult(correlation, truncation, overlap, balance, vertical_share(labels))


def render_markdown(result: AuditResult, title: str) -> str:
    lines = [f"# {title}", "", f"Leak found: {'yes' if result.leak_found else 'no'}", ""]
    lines += ["## Correlation screen (|r| > 0.15 against the target)", ""]
    lines += [f"- {f.column}: |r| = {f.abs_r:.4f} over {f.rows} rows" for f in result.correlation]
    lines += ["- none"] if not result.correlation else []
    lines += ["", "## Truncation test", ""]
    lines += _truncation_lines(result.truncation) or ["- none"]
    lines += [
        "",
        "## Fold overlap",
        "",
        "| fold | train rows | rows reading the test fold |",
        "|---|---|---|",
    ]
    lines += [f"| {f.fold_id} | {f.train_rows} | {f.overlapping_rows} |" for f in result.overlap]
    if result.balance:
        lines += [
            "",
            "## Triple-barrier balance by year",
            "",
            "| year | rows | upper | lower | vertical | status |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {b.year} | {b.rows} | {b.upper:.1%} | {b.lower:.1%} | {b.vertical:.1%} "
            f"| {b.status} |"
            for b in result.balance
        ]
        chop = "PASS" if result.vertical <= CHOP_THRESHOLD else "WARN"
        lines += [
            "",
            f"Vertical (timeout) share over the sample: {result.vertical:.1%} "
            f"against a {CHOP_THRESHOLD:.0%} limit: {chop}",
        ]
    return "\n".join(lines) + "\n"


def _truncation_lines(findings: list[TruncationFinding]) -> list[str]:
    by_column: dict[str, list[TruncationFinding]] = {}
    for finding in findings:
        by_column.setdefault(finding.column, []).append(finding)
    return [
        f"- {column}: values change at {len(group)} cut points when later rows are removed "
        f"({sum(f.mismatched_rows for f in group)} rows; first at row {group[0].first_mismatch})"
        for column, group in by_column.items()
    ]
