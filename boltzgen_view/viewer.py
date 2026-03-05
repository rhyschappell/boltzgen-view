"""Interactive parallel-coordinates viewer for BoltzGen designs."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import ipywidgets as widgets
import pandas as pd
import plotly.graph_objects as go
from IPython.display import display

from .loader import find_cif_path, find_refiltered_ids

# Default axes shown in the parallel-coordinates plot (in order).
# Columns absent from the dataframe are silently skipped.
DEFAULT_METRICS: list[str] = [
    "num_design",
    "filter_rmsd",
    "design_to_target_iptm",
    "design_to_target_ipsae",
    "target_to_design_ipsae",
    "design_ptm",
    "min_design_to_target_pae",
    "delta_sasa_refolded",
    "plip_hbonds_refolded",
    "plip_saltbridge_refolded",
    "design_hydrophobicity",
]

# Folder (relative to the notebook directory) where selected CIFs are staged.
CURRENT_STRUCTURES_DIR = Path(__file__).parent.parent / "notebooks" / "current_structures"


class ParallelCoordsViewer:
    """Interactive parallel-coordinates viewer.

    Parameters
    ----------
    df:
        Filtered metrics dataframe (all designs, used for selection).
    design_dir:
        Root directory of the BoltzGen run (used to resolve CIF paths).
    metrics:
        Columns to show as axes. Defaults to :data:`DEFAULT_METRICS`.
    color_by:
        Column used to colour lines (Viridis scale).
    max_display:
        Maximum number of rows shown in the plot. If ``len(df)`` exceeds this,
        a random sample is drawn for display; filtering always applies to *df*.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        design_dir: str | Path,
        metrics: list[str] | None = None,
        color_by: str = "design_to_target_iptm",
        max_display: int = 5000,
    ) -> None:
        self.df = df.reset_index(drop=True)
        self.design_dir = Path(design_dir)
        self.metrics = [m for m in (metrics or DEFAULT_METRICS) if m in df.columns]
        self.color_by = color_by if color_by in df.columns else None
        self.max_display = max_display

        self._refiltered_ids: set[str] = find_refiltered_ids(self.design_dir)

        self._fig: go.FigureWidget | None = None
        self._display_df: pd.DataFrame | None = None

    # Public API

    def show(self) -> None:
        """Render the parallel-coordinates plot + control buttons."""
        if len(self.df) > self.max_display:
            display_df = self.df.sample(self.max_display, random_state=42)
            banner_text = (
                f"Displaying {self.max_display:,} of {len(self.df):,} designs "
                f"(random sample). Selection applies to all {len(self.df):,}."
            )
        else:
            display_df = self.df
            banner_text = f"Displaying all {len(self.df):,} designs."

        self._display_df = display_df

        if self._refiltered_ids and "id" in display_df.columns:
            n_highlighted = display_df["id"].astype(str).isin(self._refiltered_ids).sum()
            banner_text += f" <b style='color:red'>{n_highlighted} refiltered designs highlighted in red.</b>"

        dimensions = self._build_dimensions(display_df)

        if self._refiltered_ids and "id" in display_df.columns and self.color_by and self.color_by in display_df.columns:
            # Viridis compressed into [0, 0.9]; red pinned at 1.0 for refiltered designs.
            combined_colorscale = [
                [0.0, "#440154"], [0.1, "#482878"], [0.2, "#3e4989"],
                [0.3, "#31688e"], [0.4, "#26828e"], [0.5, "#1f9e89"],
                [0.6, "#35b779"], [0.7, "#6ece58"], [0.8, "#b5de2b"],
                [0.9, "#fde725"], [1.0, "red"],
            ]
            is_refiltered = display_df["id"].astype(str).isin(self._refiltered_ids)
            raw = display_df[self.color_by].fillna(display_df[self.color_by].min())
            lo, hi = raw.min(), raw.max()
            normalized = (raw - lo) / (hi - lo) * 0.9 if hi > lo else raw * 0 + 0.45
            color_vals = normalized.where(~is_refiltered, 1.0).tolist()
            color_opts: dict[str, Any] = dict(
                color=color_vals,
                colorscale=combined_colorscale,
                showscale=False,
            )
        elif self._refiltered_ids and "id" in display_df.columns:
            color_vals = display_df["id"].astype(str).isin(self._refiltered_ids).astype(int).tolist()
            color_opts = dict(
                color=color_vals,
                colorscale=[[0, "rgba(180,180,180,0.3)"], [1, "red"]],
                showscale=False,
            )
        elif self.color_by and self.color_by in display_df.columns:
            color_vals = display_df[self.color_by].fillna(0).tolist()
            color_opts = dict(
                color=color_vals,
                colorscale="Viridis",
                showscale=False,
            )
        else:
            color_opts = {}

        parcoords = go.Parcoords(
            dimensions=dimensions,
            line=dict(**color_opts),
        )
        self._fig = go.FigureWidget([parcoords])
        n_axes = len(dimensions)
        fig_width = max(900, int(n_axes * 1.85 * 80))
        self._fig.update_layout(
            height=500,
            width=fig_width,
            margin=dict(l=80, r=80, t=60, b=20),
        )

        btn_show = widgets.Button(
            description="Show Selected",
            button_style="primary",
            icon="filter",
        )
        btn_copy = widgets.Button(
            description="Copy to current_structures",
            button_style="success",
            icon="copy",
        )

        btn_show.on_click(self._on_show_selected)
        btn_copy.on_click(self._on_copy_structures)

        self._output = widgets.Output()
        banner = widgets.HTML(f"<i>{banner_text}</i>")

        display(widgets.VBox([
            banner,
            self._fig,
            widgets.HBox([btn_show, btn_copy]),
            self._output,
        ]))

    def get_selected(self) -> pd.DataFrame:
        """Return designs matching current brush ranges in the plot."""
        if self._fig is None:
            raise RuntimeError("Call show() first.")

        parcoords_trace = self._fig.data[0]
        mask = pd.Series(True, index=self.df.index)

        for dim in parcoords_trace.dimensions:
            cr = dim.constraintrange
            if cr is None:
                continue
            col = dim.label
            if col not in self.df.columns:
                continue
            ranges = self._parse_constraintrange(cr)
            col_mask = pd.Series(False, index=self.df.index)
            for lo, hi in ranges:
                col_mask |= (self.df[col] >= lo) & (self.df[col] <= hi)
            mask &= col_mask

        return self.df[mask].copy()

    def copy_to_current_structures(self, selected: pd.DataFrame | None = None) -> Path:
        """Copy CIF files for *selected* designs to ``notebooks/current_structures/``.

        The folder is cleared first so it always reflects the current selection.
        Returns the destination directory path.
        """
        if selected is None:
            selected = self.get_selected()

        dest = CURRENT_STRUCTURES_DIR
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)

        paths = self._resolve_cif_paths(selected)
        if not paths:
            print("No CIF files found for selected designs.")
            return dest

        for p in paths:
            shutil.copy2(p, dest / p.name)

        print(f"Copied {len(paths)} CIF(s) to {dest}")
        return dest

    # Button callbacks

    def _on_show_selected(self, _btn: Any) -> None:
        self._output.outputs = ()
        selected = self.get_selected()
        cols = [c for c in ["id", "design_to_target_iptm", "design_ptm",
                             "min_design_to_target_pae", "filter_rmsd"]
                if c in selected.columns]
        with self._output:
            print(f"{len(selected):,} designs selected.")
            display(selected[cols].head(20))

    def _on_copy_structures(self, _btn: Any) -> None:
        self._output.outputs = ()
        with self._output:
            self.copy_to_current_structures()

    # Helpers

    def _build_dimensions(self, df: pd.DataFrame) -> list[dict]:
        dims = []
        for col in self.metrics:
            if col not in df.columns:
                continue
            vals = df[col].fillna(df[col].median()).tolist()
            dims.append(
                dict(
                    label=col,
                    values=vals,
                    range=[min(vals), max(vals)] if vals else [0, 1],
                )
            )
        return dims

    @staticmethod
    def _parse_constraintrange(cr: Any) -> list[tuple[float, float]]:
        if cr is None:
            return []
        if isinstance(cr[0], (int, float)):
            return [(float(cr[0]), float(cr[1]))]
        return [(float(r[0]), float(r[1])) for r in cr]

    def _resolve_cif_paths(self, selected: pd.DataFrame) -> list[Path]:
        paths: list[Path] = []
        if "id" not in selected.columns:
            print("No 'id' column in dataframe — cannot resolve CIF paths.")
            return paths
        for design_id in selected["id"]:
            p = find_cif_path(self.design_dir, str(design_id))
            if p is not None:
                paths.append(p)
        return paths
