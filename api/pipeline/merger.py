"""
merger.py — Unified data pipeline merge layer.

PURPOSE:
  Joins all loader outputs into a single pipeline DataFrame keyed on
  (coc_number, year). Handles the geographic alignment between CoC-level
  (SPM, PIT) and state-level (CDC) data. County-level joins (Vera, FMR)
  require a CoC → county crosswalk that is not yet available — those
  sections are stubs with clear TODO markers.

MERGE STRATEGY:
  Primary spine: SPM CoC × year (most complete, 2015–2024)
  Left-join PIT: (coc_number, year)   — adds population counts
  Left-join CDC: (state, year)         — adds state-level mortality
  [Stub] Vera:   needs CoC→county map  — adds incarceration costs
  Static lookup: ED cost table         — scalar parameters, not row-joined

DESIGN:
  - The merge never drops SPM rows — all left-joins preserve the spine.
  - Columns from joined tables are suffixed with their source tag to avoid
    name collisions (e.g. coc_name_pit, coc_name_spm).
  - A `pipeline_flags` list column accumulates any merge warnings per row.
  - All joins are performed on normalised keys (lowercased strings, no
    leading/trailing whitespace).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.schema import validate_loader_output

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_coc(series: pd.Series) -> pd.Series:
    """Uppercase and strip CoC number strings for reliable joining."""
    return series.astype(str).str.strip().str.upper()


def _normalise_state(series: pd.Series) -> pd.Series:
    """Uppercase 2-letter state abbreviations."""
    return series.astype(str).str.strip().str.upper()


# ---------------------------------------------------------------------------
# Main merger
# ---------------------------------------------------------------------------

class PipelineMerger:
    """
    Joins all loader outputs into the unified pipeline DataFrame.

    Usage::

        merger = PipelineMerger()
        df = merger.build(
            df_spm=load_spm(),
            df_pit=load_pit(),
            df_cdc=load_cdc(),
        )
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        df_spm: pd.DataFrame,
        df_pit: pd.DataFrame | None = None,
        df_cdc: pd.DataFrame | None = None,
        df_vera: pd.DataFrame | None = None,   # stub — needs crosswalk
    ) -> pd.DataFrame:
        """
        Build the merged pipeline DataFrame.

        Parameters
        ----------
        df_spm : pd.DataFrame
            Output from load_spm(). This is the primary spine.
        df_pit : pd.DataFrame | None
            Output from load_pit(). Left-joined on (coc_number, year).
        df_cdc : pd.DataFrame | None
            Output from load_cdc(). Left-joined on (state, year).
        df_vera : pd.DataFrame | None
            Output from load_vera(). Stub — requires CoC→county crosswalk.

        Returns
        -------
        pd.DataFrame
            Merged DataFrame. One row per CoC × year (SPM spine preserved).
        """
        # --- Validate inputs ---
        validate_loader_output(df_spm, "spm")
        if df_pit is not None:
            validate_loader_output(df_pit, "pit_coc")
        if df_cdc is not None:
            validate_loader_output(df_cdc, "cdc")

        # --- Start from SPM spine ---
        df = df_spm.copy()
        df["coc_number"] = _normalise_coc(df["coc_number"])
        df["pipeline_flags"] = [[] for _ in range(len(df))]

        # --- Join PIT ---
        if df_pit is not None:
            df = self._join_pit(df, df_pit)

        # --- Join CDC mortality ---
        if df_cdc is not None:
            df = self._join_cdc(df, df_cdc)

        # --- Vera stub ---
        if df_vera is not None:
            logger.warning(
                "Vera join requested but CoC→county crosswalk is not available. "
                "Vera data will not be merged. Provide a crosswalk file to enable this join."
            )
            df = self._flag_rows(df, "vera_join_skipped_no_crosswalk")

        logger.info(
            "Pipeline merge complete: %d CoC×year records, %d columns.",
            len(df), len(df.columns),
        )
        return df

    # ------------------------------------------------------------------
    # Join methods
    # ------------------------------------------------------------------

    def _join_pit(self, df: pd.DataFrame, df_pit: pd.DataFrame) -> pd.DataFrame:
        """Left-join PIT data on (coc_number, year)."""
        pit = df_pit.copy()
        pit["coc_number"] = _normalise_coc(pit["coc_number"])

        # Select PIT columns to bring in (exclude columns already on spine)
        pit_cols = [
            "coc_number", "year",
            "count_type",
            "overall_homeless", "sheltered_total", "unsheltered_total",
            "chronic_homeless_total", "chronic_homeless_sheltered",
            "chronic_homeless_unsheltered", "chronic_individuals_total",
        ]
        # Only include columns that actually exist in the PIT output
        pit_cols = [c for c in pit_cols if c in pit.columns]
        pit_subset = pit[pit_cols].copy()

        before = len(df)
        df = df.merge(pit_subset, on=["coc_number", "year"], how="left", suffixes=("", "_pit"))
        after = len(df)

        if after != before:
            logger.warning(
                "PIT join produced %d rows (expected %d). Check for duplicate keys.",
                after, before,
            )
            df = self._flag_rows(df, "pit_join_row_count_change")

        # Count unmatched rows
        unmatched = df["overall_homeless"].isna().sum() if "overall_homeless" in df.columns else 0
        if unmatched > 0:
            logger.info("PIT join: %d SPM rows had no matching PIT record.", unmatched)

        logger.info("PIT joined: %d columns added.", len(pit_cols) - 2)
        return df

    def _join_cdc(self, df: pd.DataFrame, df_cdc: pd.DataFrame) -> pd.DataFrame:
        """
        Left-join CDC mortality data on county_fips.

        NOTE: The current CDC export is a 2018–2024 aggregate with no year
        column. It is joined on county_fips only. This requires a CoC→county
        crosswalk (not yet available), so this join is currently a stub that
        logs a warning and returns the DataFrame unchanged.

        TODO: When the CoC→county crosswalk is available, aggregate CDC
        county data to CoC level and join on coc_number.
        """
        logger.warning(
            "CDC join skipped: CDC data is county-level with no year column. "
            "A CoC→county crosswalk is required to aggregate CDC to the CoC "
            "spine. This will be enabled once the crosswalk file is available."
        )
        df = self._flag_rows(df, "cdc_join_skipped_no_crosswalk")
        return df

    @staticmethod
    def _flag_rows(df: pd.DataFrame, flag: str) -> pd.DataFrame:
        """Append a flag string to every row's pipeline_flags list."""
        if "pipeline_flags" in df.columns:
            df["pipeline_flags"] = df["pipeline_flags"].apply(
                lambda lst: (lst if isinstance(lst, list) else []) + [flag]
            )
        return df


# ---------------------------------------------------------------------------
# State FIPS → abbreviation lookup
# ---------------------------------------------------------------------------

_FIPS_TO_ABBREV: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}


def _fips_to_abbrev(fips_series: pd.Series) -> pd.Series:
    """Map a Series of 2-digit state FIPS codes to 2-letter abbreviations."""
    normalised = fips_series.astype(str).str.strip().str.zfill(2)
    return normalised.map(_FIPS_TO_ABBREV)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def build_pipeline(
    datasets_dir: str | Path | None = None,
    spm_years: list[int] | None = None,
    pit_years: list[int] | None = None,
) -> pd.DataFrame:
    """
    Convenience function: load all available datasets and merge them.

    Parameters
    ----------
    datasets_dir : str | Path | None
        Override path to the datasets directory.
    spm_years : list[int] | None
        Years to load from SPM. Defaults to all (2015–2024).
    pit_years : list[int] | None
        Years to load from PIT. Defaults to all (2007–2024).

    Returns
    -------
    pd.DataFrame
        Merged pipeline DataFrame with all available columns.

    Notes
    -----
    - Vera join is automatically skipped (CoC→county crosswalk not available).
    - FMR is deferred (openpyxl incompatibility — see implementation_plan.md).
    - NHGIS join is deferred (blocked by same crosswalk requirement as Vera).
    """
    # Import here to avoid circular imports at module level
    from loaders.spm_loader import load_spm
    from loaders.pit_loader import load_pit
    from loaders.cdc_loader import load_cdc

    kwargs: dict[str, Any] = {}
    if datasets_dir:
        kwargs["datasets_dir"] = datasets_dir

    df_spm = load_spm(years=spm_years, **kwargs)

    try:
        df_pit = load_pit(years=pit_years, **kwargs)
    except Exception as exc:
        logger.warning("PIT load failed — merging without PIT data: %s", exc)
        df_pit = None

    try:
        df_cdc = load_cdc(**kwargs)
    except Exception as exc:
        logger.warning("CDC load failed — merging without CDC data: %s", exc)
        df_cdc = None

    return PipelineMerger().build(df_spm=df_spm, df_pit=df_pit, df_cdc=df_cdc)
