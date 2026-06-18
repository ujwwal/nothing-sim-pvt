"""
vera_loader.py — Vera Institute of Justice incarceration trends loader.

DATASET: datasets/vera institute incarcenation/incarceration_trends_county.csv
SOURCE:  Vera Institute (county level, annual, 1970–2026)
PURPOSE: Provide jail and prison population counts for the incarceration cost
         component of the simulation pipeline.

KEY FINDINGS FROM DATASET EXPLORATION:
- Large CSV: ~128,500 rows × 164 columns.
- Granularity: one row per county × year.
- Primary key: (year, county_fips) — county_fips is a 5-digit integer FIPS code.
- Years span 1970–2026; pipeline scope is 2007–2024.
- Key fields: total_jail_pop, total_prison_pop, and their per-100k rates.
- Many cells are NaN for earlier years (data collection gaps) or suppressed
  small-county values — these are genuine missingness, not structural.
- county_fips must be zero-padded to 5 digits to join with other datasets.

FIELDS EXTRACTED:
  Identifiers: year, county_fips (zero-padded str), county_name, state_abbr
  Jail:        total_jail_pop, total_jail_pop_rate (per 100k)
  Prison:      total_prison_pop, total_prison_pop_rate (per 100k)
  Capacity:    jail_rated_capacity
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERA_COUNTY_FILE = "vera institute incarcenation/incarceration_trends_county.csv"

# Source columns to load (avoids reading all 164 columns into memory)
_USE_COLS: list[str] = [
    "year",
    "county_fips",
    "county_name",
    "state_abbr",
    "total_jail_pop",
    "total_prison_pop",
    "total_jail_pop_rate",
    "total_prison_pop_rate",
    "jail_rated_capacity",
]

_NUMERIC_FIELDS: frozenset[str] = frozenset({
    "total_jail_pop", "total_prison_pop",
    "total_jail_pop_rate", "total_prison_pop_rate",
    "jail_rated_capacity",
})

# Default year range aligned with simulation pipeline scope
_DEFAULT_MIN_YEAR = 2007
_DEFAULT_MAX_YEAR = 2024


# ---------------------------------------------------------------------------
# Loader class
# ---------------------------------------------------------------------------

class VeraLoader:
    """
    Loads Vera Institute county-level incarceration data.

    Usage::

        loader = VeraLoader()
        df = loader.load_all()              # 2007–2024 by default
        df = loader.load_all(years=[2019, 2020])
    """

    def __init__(self, datasets_dir: str | Path | None = None) -> None:
        if datasets_dir is None:
            datasets_dir = Path(__file__).parent.parent.parent / "datasets"
        self.datasets_dir = Path(datasets_dir)
        self.vera_path = self.datasets_dir / VERA_COUNTY_FILE

        if not self.vera_path.exists():
            raise FileNotFoundError(
                f"Vera county CSV not found at {self.vera_path}."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(
        self,
        years: list[int] | None = None,
        min_year: int = _DEFAULT_MIN_YEAR,
        max_year: int = _DEFAULT_MAX_YEAR,
    ) -> pd.DataFrame:
        """
        Load Vera incarceration data as a tidy DataFrame.

        Parameters
        ----------
        years : list[int] | None
            Explicit list of years to include. If None, uses the
            ``min_year``–``max_year`` range (default 2007–2024).
        min_year, max_year : int
            Inclusive year bounds when ``years`` is None.

        Returns
        -------
        pd.DataFrame
            One row per county × year. county_fips is zero-padded to
            5 characters (string) for consistent joining.

        Notes
        -----
        - NaN values in jail/prison counts are genuine missingness (small
          counties, data gaps) — candidates for imputation downstream.
        - county_fips is stored as a zero-padded string (e.g. "06037")
          for reliable joining with other FIPS-keyed datasets.
        """
        # Only load the columns we need — avoids 164-column memory overhead
        available_cols = self._available_columns()
        cols_to_load = [c for c in _USE_COLS if c in available_cols]
        missing_source_cols = [c for c in _USE_COLS if c not in available_cols]
        if missing_source_cols:
            logger.warning("Vera: source columns not found: %s", missing_source_cols)

        df = pd.read_csv(
            self.vera_path,
            usecols=cols_to_load,
            dtype={"county_fips": str},  # preserve leading zeros
        )

        # Year filtering
        if years is not None:
            df = df[df["year"].isin(years)]
        else:
            df = df[(df["year"] >= min_year) & (df["year"] <= max_year)]

        # Drop rows with no FIPS
        before = len(df)
        df = df[df["county_fips"].notna() & (df["county_fips"].str.strip() != "")]
        if len(df) < before:
            logger.debug("Vera: dropped %d rows with null county_fips.", before - len(df))

        # Normalise FIPS to 5-char zero-padded string
        df["county_fips"] = df["county_fips"].str.strip().str.zfill(5)

        # Enforce numeric types
        for col in _NUMERIC_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.reset_index(drop=True)

        logger.info(
            "Vera: loaded %d county×year records (%d–%d).",
            len(df),
            int(df["year"].min()) if len(df) else 0,
            int(df["year"].max()) if len(df) else 0,
        )
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _available_columns(self) -> set[str]:
        """Read only the header row to discover available columns."""
        header = pd.read_csv(self.vera_path, nrows=0)
        return set(header.columns)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def load_vera(
    years: list[int] | None = None,
    datasets_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Load Vera Institute county-level incarceration data as a tidy DataFrame.

    Parameters
    ----------
    years : list[int] | None
        Explicit year list. Defaults to 2007–2024 range.
    datasets_dir : str | Path | None
        Path to the datasets directory. Defaults to ``<project_root>/datasets/``.

    Returns
    -------
    pd.DataFrame
        One row per county × year with jail and prison population fields.
        county_fips is a zero-padded 5-character string.
    """
    return VeraLoader(datasets_dir=datasets_dir).load_all(years=years)
