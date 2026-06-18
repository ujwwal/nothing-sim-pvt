"""
pit_loader.py — HUD Point-in-Time (PIT) Count loader (CoC level).

DATASET: datasets/hud pit count_/2007-2024-PIT-Counts-by-CoC.xlsb
SOURCE:  HUD (Continuum of Care level, annual, 2007–2024)
PURPOSE: Produce a clean, standardised CoC × year DataFrame containing
         baseline homeless population counts for the unified pipeline.

KEY FINDINGS FROM DATASET EXPLORATION:
- Binary Excel (.xlsb) format — requires the ``pyxlsb`` engine.
- One sheet per reporting year (2007–2024); named by year string.
- Additional metadata sheets (e.g. "CoC Mergers", "field list, all years")
  are skipped automatically.
- Single-row header (no merged cells). Row 0 = column names.
- ~390 CoCs per year, with some year-to-year variation due to mergers/splits.
- "Count Types" column flags Sheltered-Only vs Sheltered+Unsheltered counts.
  Sheltered-Only CoCs report 0 unsheltered — not missing, structural.
- Chronic homelessness columns present starting around 2011.
  Earlier years may have NaN for chronic counts — schema-drift NaN,
  documented in ``missing_fields``.
- CoC identifier: column 0 = "CoC Number", same [A-Z]{2}-\\d{3} format as SPM.

FIELDS EXTRACTED:
  Identifiers: coc_number, coc_name, coc_category, count_type
  Population:  overall_homeless, sheltered_total, unsheltered_total
  Chronic:     chronic_homeless_total, chronic_homeless_sheltered,
               chronic_homeless_unsheltered, chronic_individuals_total
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIT_COC_FILE = "hud pit count_/2007-2024-PIT-Counts-by-CoC.xlsb"

# Sheets that are not year-data sheets (skip these)
_NON_YEAR_SHEETS: frozenset[str] = frozenset({
    "coc mergers", "cocs, states, dds", "field list, all years",
    "table_categories", "generate_table", "pit_counts_table_template",
    "pit_counts_table", "generate_chart", "chart_categories",
    "pit_counts_chart", "pit_counts_chart_template",
})

COC_ID_PATTERN = re.compile(r"^[A-Z]{2}-\d{3}\w?$")

# ---------------------------------------------------------------------------
# Column keyword matchers
# ---------------------------------------------------------------------------
# (keyword,) — matched as case-insensitive substring of the column header.
# First matching column wins.
_COL_MATCHERS: dict[str, list[str]] = {
    "coc_number":                    ["coc number"],
    "coc_name":                      ["coc name"],
    "coc_category":                  ["coc category"],
    "count_type":                    ["count types"],
    # Total homeless counts
    "overall_homeless":              ["overall homeless"],
    "sheltered_total":               ["sheltered total homeless"],
    "unsheltered_total":             ["unsheltered homeless"],
    # Chronic homelessness (may be absent in earlier years)
    "chronic_homeless_total":        ["overall chronically homeless"],
    "chronic_homeless_sheltered":    ["sheltered total chronically homeless"],
    "chronic_homeless_unsheltered":  ["unsheltered chronically homeless"],
    "chronic_individuals_total":     ["overall chronically homeless individuals"],
}

_NUMERIC_FIELDS: frozenset[str] = frozenset({
    "overall_homeless", "sheltered_total", "unsheltered_total",
    "chronic_homeless_total", "chronic_homeless_sheltered",
    "chronic_homeless_unsheltered", "chronic_individuals_total",
})


# ---------------------------------------------------------------------------
# Loader class
# ---------------------------------------------------------------------------

class PITLoader:
    """
    Loads and normalises all annual sheets from the HUD PIT CoC workbook.

    Produces a clean CoC × year DataFrame. No model assumptions are made.

    Usage::

        loader = PITLoader()
        df = loader.load_all()
        df = loader.load_all(years=[2015, 2016, 2017])
    """

    def __init__(self, datasets_dir: str | Path | None = None) -> None:
        if datasets_dir is None:
            datasets_dir = Path(__file__).parent.parent.parent / "datasets"
        self.datasets_dir = Path(datasets_dir)
        self.pit_path = self.datasets_dir / PIT_COC_FILE

        if not self.pit_path.exists():
            raise FileNotFoundError(
                f"PIT CoC workbook not found at {self.pit_path}. "
                "Ensure datasets/hud pit count_/2007-2024-PIT-Counts-by-CoC.xlsb is present."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def available_years(self) -> list[int]:
        """Return the list of reporting years present in the workbook."""
        xl = pd.ExcelFile(self.pit_path, engine="pyxlsb")
        years: list[int] = []
        for name in xl.sheet_names:
            if name.lower().strip() in _NON_YEAR_SHEETS:
                continue
            try:
                years.append(int(name.strip()))
            except ValueError:
                logger.debug("PIT: skipping non-year sheet %r.", name)
        return sorted(years)

    def load_all(self, years: list[int] | None = None) -> pd.DataFrame:
        """
        Load PIT count data for the given years as a tidy DataFrame.

        Parameters
        ----------
        years : list[int] | None
            Reporting years to include. Defaults to all available (2007–2024).

        Returns
        -------
        pd.DataFrame
            One row per CoC × year with columns for total, sheltered,
            unsheltered, and chronic homeless counts.

        Notes
        -----
        - Sheltered-Only CoCs have structural 0s (not NaN) for unsheltered
          counts. These are valid and must not be imputed.
        - Chronic columns may be NaN for years < ~2011 (schema drift).
          These NaNs are documented in the ``missing_fields`` column.
        """
        target_years = years if years is not None else self.available_years()
        frames: list[pd.DataFrame] = []

        for year in target_years:
            try:
                df_year = self._load_year(year)
                frames.append(df_year)
                logger.info("PIT %d: loaded %d CoC records.", year, len(df_year))
            except Exception as exc:  # noqa: BLE001
                logger.warning("PIT %d: failed to load — %s", year, exc)

        if not frames:
            logger.warning("PIT loader returned no records.")
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        for col in _NUMERIC_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(
            "PIT: loaded %d CoC×year records across %d years.",
            len(df), df["year"].nunique(),
        )
        return df

    # ------------------------------------------------------------------
    # Year-level loading
    # ------------------------------------------------------------------

    def _load_year(self, year: int) -> pd.DataFrame:
        """Load and parse one year sheet, returning a normalised DataFrame."""
        raw = pd.read_excel(
            self.pit_path,
            sheet_name=str(year),
            header=0,           # single-row header
            engine="pyxlsb",
        )

        # Normalise column names for matching
        cols_lower = [str(c).lower().strip() for c in raw.columns]

        # Build column index: canonical_field → positional index
        col_map: dict[str, int] = {}
        missing: list[str] = []
        for field_name, keywords in _COL_MATCHERS.items():
            found = False
            for kw in keywords:
                for idx, c_l in enumerate(cols_lower):
                    if kw in c_l:
                        col_map[field_name] = idx
                        found = True
                        break
                if found:
                    break
            if not found:
                missing.append(field_name)

        if missing:
            logger.warning("PIT %d: columns not found for fields: %s", year, missing)

        # Filter to valid CoC rows
        coc_col_idx = col_map.get("coc_number", 0)
        coc_series = raw.iloc[:, coc_col_idx].astype(str).str.strip()
        mask = coc_series.str.match(COC_ID_PATTERN)
        dropped = (~mask).sum()
        if dropped:
            logger.debug("PIT %d: dropped %d non-CoC rows.", year, dropped)
        raw = raw[mask].reset_index(drop=True)

        # Extract fields into a clean DataFrame
        def extract(fname: str) -> pd.Series:
            idx = col_map.get(fname)
            if idx is None:
                return pd.Series([None] * len(raw), name=fname)
            return raw.iloc[:, idx].copy()

        out = pd.DataFrame({
            "year":                         year,
            "coc_number":                   extract("coc_number").astype(str).str.strip(),
            "coc_name":                     extract("coc_name").astype(str).str.strip(),
            "coc_category":                 extract("coc_category").astype(str).str.strip(),
            "count_type":                   extract("count_type").astype(str).str.strip(),
            "overall_homeless":             extract("overall_homeless"),
            "sheltered_total":              extract("sheltered_total"),
            "unsheltered_total":            extract("unsheltered_total"),
            "chronic_homeless_total":       extract("chronic_homeless_total"),
            "chronic_homeless_sheltered":   extract("chronic_homeless_sheltered"),
            "chronic_homeless_unsheltered": extract("chronic_homeless_unsheltered"),
            "chronic_individuals_total":    extract("chronic_individuals_total"),
            "missing_fields":               [missing] * len(raw),
        })

        # Normalise "None" / "nan" strings from astype(str) on NaN columns
        for str_col in ["coc_category", "count_type"]:
            out[str_col] = out[str_col].replace({"None": None, "nan": None, "<NA>": None})

        return out


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def load_pit(
    years: list[int] | None = None,
    datasets_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Load HUD PIT CoC count data as a tidy DataFrame.

    Parameters
    ----------
    years : list[int] | None
        Reporting years to include. Defaults to all available (2007–2024).
    datasets_dir : str | Path | None
        Path to the datasets directory. Defaults to ``<project_root>/datasets/``.

    Returns
    -------
    pd.DataFrame
        One row per CoC × year with population and chronic homeless counts.
    """
    return PITLoader(datasets_dir=datasets_dir).load_all(years=years)
