"""Load BoltzGen metrics CSVs and resolve CIF paths."""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pandas as pd


def find_metrics_csv(design_dir: str | Path) -> Path:
    """Find the metrics CSV in *design_dir*.

    Tries ``aggregate_metrics_*.csv`` first, then falls back to
    ``all_designs_metrics.csv``.
    """
    design_dir = Path(design_dir)
    matches = sorted(design_dir.glob("aggregate_metrics_*.csv"))
    if matches:
        return matches[-1] 
    fallback = design_dir / "all_designs_metrics.csv"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"No metrics CSV found in {design_dir}. "
        "Expected aggregate_metrics_*.csv or all_designs_metrics.csv."
    )


def load_metrics(design_dir: str | Path) -> pd.DataFrame:
    """Load metrics CSV and derive computed columns.

    Derived columns
    ---------------
    filter_rmsd
        Alias for ``bb_rmsd`` when the column is absent.
    filter_rmsd_design
        Alias for ``bb_rmsd_design`` when the column is absent.
    has_x
        1 if ``'X'`` appears in ``designed_sequence``, else 0.
    neg_min_design_to_target_pae
        Negation of ``min_design_to_target_pae`` (higher → better).
    """
    csv_path = find_metrics_csv(design_dir)
    df = pd.read_csv(csv_path)

    extra: dict = {}

    if "filter_rmsd" not in df.columns:
        extra["filter_rmsd"] = df["bb_rmsd"] if "bb_rmsd" in df.columns else float("nan")
    if "filter_rmsd_design" not in df.columns:
        extra["filter_rmsd_design"] = df["bb_rmsd_design"] if "bb_rmsd_design" in df.columns else float("nan")

    if "designed_sequence" in df.columns:
        extra["has_x"] = df["designed_sequence"].apply(
            lambda s: 1 if isinstance(s, str) and "X" in s else 0
        )
    else:
        extra["has_x"] = 0

    if "min_design_to_target_pae" in df.columns:
        extra["neg_min_design_to_target_pae"] = -df["min_design_to_target_pae"]
    else:
        extra["neg_min_design_to_target_pae"] = float("nan")

    if extra:
        df = pd.concat([df, pd.DataFrame(extra, index=df.index)], axis=1)

    return df


def find_refiltered_ids(design_dir: str | Path) -> set[str]:
    """Return design IDs present in the sibling ``refiltered/`` directory.

    Looks for any CSV file under ``{design_dir.parent}/refiltered/`` that
    contains an ``id`` column.  Returns an empty set if the directory or a
    suitable CSV is not found.
    """
    refiltered_dir = Path(design_dir).parent / "refiltered"
    if not refiltered_dir.is_dir():
        return set()

    # Prefer the smallest CSV (most filtered); skip any without an 'id' column.
    candidates = sorted(refiltered_dir.rglob("*.csv"), key=lambda p: p.stat().st_size)
    for csv_path in candidates:
        try:
            df = pd.read_csv(csv_path, usecols=["id"])
            return set(df["id"].astype(str))
        except (ValueError, KeyError):
            continue

    return set()


def find_cif_path(design_dir: str | Path, design_id: str) -> Path | None:
    """Return the refold CIF path for *design_id*, or None if not found."""
    p = Path(design_dir) / "refold_cif" / f"{design_id}.cif"
    return p if p.exists() else None
