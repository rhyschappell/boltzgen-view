"""Hard-threshold pre-filters reimplementing BoltzGen defaults."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Default filter specification
# Each entry: {"feature": col, "lower_is_better": bool, "threshold": val}
# "lower_is_better=True"  → keep rows where col ≤ threshold
# "lower_is_better=False" → keep rows where col ≥ threshold
DEFAULT_FILTERS: list[dict[str, Any]] = [
    {"feature": "has_x", "lower_is_better": True, "threshold": 0},
    {"feature": "filter_rmsd", "lower_is_better": True, "threshold": 2.5},
    {"feature": "filter_rmsd_design", "lower_is_better": True, "threshold": 2.5},
    {"feature": "CYS_fraction", "lower_is_better": True, "threshold": 0},
    {"feature": "ALA_fraction", "lower_is_better": True, "threshold": 0.3},
    {"feature": "GLY_fraction", "lower_is_better": True, "threshold": 0.3},
    {"feature": "GLU_fraction", "lower_is_better": True, "threshold": 0.3},
    {"feature": "LEU_fraction", "lower_is_better": True, "threshold": 0.3},
    {"feature": "VAL_fraction", "lower_is_better": True, "threshold": 0.3},
]


def apply_filters(
    df: pd.DataFrame,
    filters: list[dict[str, Any]] | None = None,
    extra_filters: list[dict[str, Any]] | None = None,
    max_display: int = 5000,
) -> tuple[pd.DataFrame, dict]:
    """Apply hard-threshold filters to *df*.

    Parameters
    ----------
    df:
        Full metrics dataframe.
    filters:
        List of filter dicts (defaults to :data:`DEFAULT_FILTERS`).
    extra_filters:
        Additional filters appended after *filters*.
    max_display:
        Soft cap — not applied here but stored in the summary for callers.

    Returns
    -------
    filtered_df:
        DataFrame with only passing rows (index preserved).
    summary:
        Dict with keys ``"filters"`` (list of per-filter result dicts) and
        ``"total_passed"`` / ``"total_input"``.
    """
    if filters is None:
        filters = DEFAULT_FILTERS

    all_filters = list(filters)
    if extra_filters:
        all_filters.extend(extra_filters)

    mask = pd.Series(True, index=df.index)
    filter_results: list[dict] = []

    for flt in all_filters:
        col = flt["feature"]
        threshold = flt["threshold"]
        lower_is_better: bool = flt["lower_is_better"]

        if col not in df.columns:
            filter_results.append(
                {
                    "feature": col,
                    "threshold": threshold,
                    "lower_is_better": lower_is_better,
                    "passed": int(mask.sum()),
                    "skipped": True,
                    "reason": "column absent",
                }
            )
            continue

        before = int(mask.sum())
        if lower_is_better:
            new_mask = df[col] <= threshold
        else:
            new_mask = df[col] >= threshold

        # NaN rows fail the filter
        new_mask = new_mask.fillna(False)
        mask = mask & new_mask
        after = int(mask.sum())

        filter_results.append(
            {
                "feature": col,
                "threshold": threshold,
                "lower_is_better": lower_is_better,
                "before": before,
                "after": after,
                "removed": before - after,
                "skipped": False,
            }
        )

    filtered_df = df[mask].copy()
    summary = {
        "total_input": len(df),
        "total_passed": len(filtered_df),
        "max_display": max_display,
        "filters": filter_results,
    }
    return filtered_df, summary


def print_summary(summary: dict) -> None:
    """Pretty-print filter summary to stdout."""
    print(
        f"Filters applied: {summary['total_input']:,} → "
        f"{summary['total_passed']:,} designs passed\n"
    )
    header = f"{'Filter':<30} {'Threshold':>10} {'Before':>8} {'After':>8} {'Removed':>8}"
    print(header)
    print("-" * len(header))
    for r in summary["filters"]:
        if r.get("skipped"):
            print(f"  {r['feature']:<28} {'(skipped — column absent)'}")
            continue
        direction = "≤" if r["lower_is_better"] else "≥"
        print(
            f"  {r['feature']:<28} {direction}{r['threshold']:>9} "
            f"{r['before']:>8,} {r['after']:>8,} {r['removed']:>8,}"
        )
