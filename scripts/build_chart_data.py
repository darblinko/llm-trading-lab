"""Build docs/data.json from the CSVs in data/results.

Usage: python scripts/build_chart_data.py [--results data/results] [--out docs/data.json]

Every number in the output is read from a CSV, and each chart names its source file.
Render the README figures afterwards with the publish kit's svgchart.py.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REPO = "llm-trading-lab"
CHECKS_PER_FAMILY = 6
RECORD_CHECKS = (
    ("follows_naming_convention", "folder name follows convention"),
    ("has_all_four_files", "before, after, diff, rationale"),
    ("diff_matches_snapshots", "diff lines match snapshots"),
    ("names_trigger", 'rationale contains "trigger"'),
    ("states_expected_change", 'rationale contains "expected"'),
    ("states_falsifier", 'rationale contains "falsif"'),
    ("linked_from_changelog", "linked from changelog"),
)


def read_rows(results: Path, name: str) -> list[dict[str, str]]:
    with open(results / name, newline="") as handle:
        return list(csv.DictReader(handle))


def source(name: str) -> str:
    return f"data/results/{name}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def span(values: list[float], digits: int = 2) -> str:
    return f"{min(values):.{digits}f} to {max(values):.{digits}f}"


def hero_chart(results: Path) -> dict:
    stage_a = read_rows(results, "stage_a_gate_results.csv")
    b17 = read_rows(results, "b17_gate_results.csv")
    leak = read_rows(results, "leak_fix_before_after.csv")
    compliance = {r["check"]: r for r in read_rows(results, "prompt_history_compliance.csv")}
    leak_5m = next(r for r in leak if r["horizon"] == "5m" and r["metric"] == "accuracy")
    negative = sum(float(r["net_expectancy_bps"]) < 0 for r in b17)
    complete = compliance["has_all_four_files"]
    stage_a_pass = f"{sum(r['gate'] == 'pass' for r in stage_a)} of {len(stage_a)}"
    b17_pass = f"{sum(r['overall'] == 'pass' for r in b17)} of {len(b17)}"
    clean, leaked = pct(float(leak_5m["clean_v4"])), pct(float(leak_5m["leaked_v3"]))
    return {
        "name": "hero",
        "type": "stats",
        "title": "Negative results recorded as counts and rates",
        "subtitle": "Gate outcomes, a leak fix and the prompt change log",
        "source": "data/results/{stage_a_gate_results, b17_gate_results, "
        "leak_fix_before_after, prompt_history_compliance}.csv",
        "alt": f"Stage A families passing: {stage_a_pass}. b17 models passing: {b17_pass}. "
        f"5-minute classifier accuracy: {leaked} with the leak, {clean} without it. "
        f"Prompt change records: {complete['of']}.",
        "tiles": [
            {
                "label": "Stage A families pass",
                "value": stage_a_pass,
                "note": "in-sample 2016 to 2021",
            },
            {
                "label": "b17 entry models pass",
                "value": b17_pass,
                "note": f"{negative} of {len(b17)} below 0 bps net",
            },
            {"label": "5m accuracy, leak fixed", "value": clean, "note": f"{leaked} with the leak"},
            {
                "label": "Prompt change records",
                "value": complete["of"],
                "note": f"{complete['passing']} with all four files",
            },
        ],
    }


def stage_a_chart(results: Path) -> dict:
    checks = (
        "min_events",
        "distinct_months",
        "expectancy",
        "bootstrap_ci",
        "recent_years",
        "control",
    )
    rows = read_rows(results, "stage_a_gate_results.csv")
    passed = [sum(r[c] == "pass" for c in checks) for r in rows]
    return {
        "name": "stage-a-checks",
        "type": "hbar",
        "title": "Stage A checks passed per setup family",
        "subtitle": "In-sample 2016 to 2021; a family needs all six to pass the gate",
        "source": source("stage_a_gate_results.csv"),
        "alt": f"{sum(r['gate'] == 'pass' for r in rows)} of {len(rows)} families pass the "
        f"gate; the most checks any family passes is {max(passed)}.",
        "format": "number",
        "max": CHECKS_PER_FAMILY,
        "threshold": {"value": CHECKS_PER_FAMILY, "label": "all 6"},
        "data": [
            {"label": r["family"], "value": n, "status": r["gate"]}
            for r, n in zip(rows, passed, strict=True)
        ],
    }


def b17_chart(results: Path) -> dict:
    rows = read_rows(results, "b17_gate_results.csv")
    factors = [float(r["profit_factor"]) for r in rows]
    return {
        "name": "b17-profit-factor",
        "type": "hbar",
        "title": "Profit factor of the b17 directional entry models",
        "subtitle": "Point estimates; the gate requires the lower 95% bound to exceed 1",
        "source": source("b17_gate_results.csv"),
        "alt": f"Profit factor ranges from {span(factors)}; "
        f"{sum(r['gate_profit_factor_gt_1'] == 'fail' for r in rows)} of {len(rows)} "
        "models fail this gate.",
        "format": "decimal2",
        "max": 1.2,
        "threshold": {"value": 1.0, "label": "gate 1.0"},
        "data": [
            {"label": r["model"], "value": f, "status": r["gate_profit_factor_gt_1"]}
            for r, f in zip(rows, factors, strict=True)
        ],
    }


def leak_chart(results: Path) -> dict:
    rows = [
        r
        for r in read_rows(results, "leak_fix_before_after.csv")
        if r["metric"] in ("directional_accuracy", "accuracy")
    ]
    leaked = [float(r["leaked_v3"]) * 100 for r in rows]
    clean = [float(r["clean_v4"]) * 100 for r in rows]
    return {
        "name": "leak-fix",
        "type": "columns",
        "title": "Accuracy with and without two look-ahead leaks",
        "subtitle": "Regression: direction accuracy. Classifier: accuracy.",
        "source": source("leak_fix_before_after.csv"),
        "alt": f"Accuracy is {span(leaked, 1)} percent with the leaks and "
        f"{span(clean, 1)} percent without them.",
        "format": "percent",
        "categories": [f"{r['horizon']} {r['model']}" for r in rows],
        "series": [
            {"name": "leaked features (v3)", "values": [v / 100 for v in leaked]},
            {"name": "clean features (v4)", "values": [v / 100 for v in clean]},
        ],
    }


def walkforward_chart(results: Path) -> dict:
    rows = read_rows(results, "walkforward_folds.csv")
    by_model = {
        m: [float(r["auc_roc"]) for r in rows if r["model"] == m]
        for m in ("xgboost", "random_forest")
    }
    folds = [r["fold_id"] for r in rows if r["model"] == "xgboost"]
    return {
        "name": "walkforward-auc",
        "type": "line",
        "title": "Test-fold ROC AUC across 21 walk-forward folds",
        "subtitle": "Expanding window on 1-minute bars; 0.5 is chance level",
        "source": source("walkforward_folds.csv"),
        "alt": f"Fold AUC ranges from {span(by_model['xgboost'])} for xgboost and "
        f"{span(by_model['random_forest'])} for random forest.",
        "format": "decimal3",
        "min": 0.4,
        "max": 0.8,
        "x": folds,
        "series": [
            {"name": "xgboost", "values": by_model["xgboost"]},
            {"name": "random forest", "values": by_model["random_forest"]},
        ],
    }


def replay_chart(results: Path) -> dict:
    rows = read_rows(results, "llm_gate_replay.csv")
    skipped = sum(int(r["skipped"]) for r in rows)
    ticks = sum(int(r["ticks"]) for r in rows)
    return {
        "name": "llm-gate-replay",
        "type": "columns",
        "title": "Logged ticks per replay day, by gate decision",
        "subtitle": "Skipped: no trigger fired, the LLM is not called",
        "source": source("llm_gate_replay.csv"),
        "alt": f"Across {len(rows)} days the gate skips {skipped:,} of {ticks:,} ticks.",
        "format": "number",
        "categories": [r["date"] for r in rows],
        "series": [
            {"name": "skipped", "values": [int(r["skipped"]) for r in rows]},
            {"name": "invoked", "values": [int(r["invoked"]) for r in rows]},
        ],
    }


def gate_lift_chart(results: Path) -> dict:
    rows = read_rows(results, "expectancy_gate_lift.csv")
    labels = {
        "Executed (gate said GO)": "executed (LLM said go)",
        "Gated out (gate said WAIT)": "gated out (LLM said wait)",
        "All triggered": "all triggered signals",
    }
    rates = {r["set"]: pct(float(r["direction_correct_rate"])) for r in rows}
    return {
        "name": "gate-lift",
        "type": "hbar",
        "title": "Direction-correct rate by LLM entry decision",
        "subtitle": "Signals that triggered, split by whether the LLM approved entry",
        "source": source("expectancy_gate_lift.csv"),
        "alt": f"Signals the LLM rejected were direction-correct "
        f"{rates['Gated out (gate said WAIT)']} of the time, against "
        f"{rates['Executed (gate said GO)']} for the signals it approved.",
        "format": "percent",
        "max": 1,
        "data": [
            {
                "label": labels[r["set"]],
                "value": float(r["direction_correct_rate"]),
                "note": f"{r['signals']} signals",
            }
            for r in rows
        ],
    }


def compliance_chart(results: Path) -> dict:
    rows = {r["check"]: r for r in read_rows(results, "prompt_history_compliance.csv")}
    total = rows["has_all_four_files"]["of"]
    shares = [int(rows[k]["passing"]) / int(rows[k]["of"]) * 100 for k, _ in RECORD_CHECKS]
    return {
        "name": "prompt-compliance",
        "type": "hbar",
        "title": "Prompt change records passing each convention check",
        "subtitle": f"{total} records, May to October 2026",
        "source": source("prompt_history_compliance.csv"),
        "alt": f"From {span(shares, 1)} percent of records pass each check.",
        "format": "percent",
        "max": 1,
        "data": [
            {
                "label": label,
                "value": int(rows[key]["passing"]) / int(rows[key]["of"]),
                "note": f"{rows[key]['passing']} of {rows[key]['of']}",
            }
            for key, label in RECORD_CHECKS
        ],
    }


BUILDERS = (
    hero_chart,
    stage_a_chart,
    b17_chart,
    leak_chart,
    walkforward_chart,
    replay_chart,
    gate_lift_chart,
    compliance_chart,
)


def build(results: Path, revision: str, measured: str) -> dict:
    return {
        "meta": {"repo": REPO, "revision": revision, "measured": measured},
        "charts": [builder(results) for builder in BUILDERS],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=Path("data/results"))
    parser.add_argument("--out", type=Path, default=Path("docs/data.json"))
    parser.add_argument("--revision", default="unrecorded")
    parser.add_argument("--measured", default="2026-10-28")
    args = parser.parse_args(argv)
    document = build(args.results, args.revision, args.measured)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(f"wrote {args.out} with {len(document['charts'])} charts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
