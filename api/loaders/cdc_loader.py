"""
cdc_loader.py — CDC WONDER Underlying Cause of Death loader.

DATASET: datasets/cdc wonder cause of death_/
         Underlying Cause of Death, 2018-2024, Single Race.xls
SOURCE:  CDC WONDER (state level, annual, 2018–2024)
PURPOSE: Provide mortality rate estimates for the deceased-state transition
         probability in the simulation pipeline.

KEY FINDINGS FROM DATASET EXPLORATION:
- File extension is .xls but the actual format is a tab-delimited text export
  from the CDC WONDER query interface — NOT a real Excel binary.
  → Must be read with pd.read_csv(..., sep='\\t').
- Actual structure: county-level aggregate (2018–2024 combined, no Year column).
  Columns: Notes, County, County Code, Deaths, Population, Crude Rate, CI bounds.
- "Notes" column is metadata — dropped.
- "Suppressed" or "Unreliable" values in numeric columns → NaN after coercion.
- County Code is a 5-digit FIPS string (e.g. '01001').
- State is embedded in County name (e.g. 'Autauga County, AL') — parsed out.
- No year column in this export — the data represents the 2018–2024 period.
  The loader assigns year=None and documents this in the output.

FIELDS EXTRACTED:
  Identifiers: county_fips (5-digit), county_name, state_abbr (parsed from county)
  Counts:      deaths (raw count), population (denominator)
  Rates:       crude_rate (per 100k, as reported by CDC)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CDC_FILE = "cdc wonder cause of death_/Underlying Cause of Death, 2018-2024, Single Race.xls"

# CDC WONDER tab-delimited exports begin with a "Notes" line before the header.
# Rows that are metadata/footer have no numeric Year value.
_NUMERIC_FIELDS: frozenset[str] = frozenset({"deaths", "population", "crude_rate"})

# Column name aliases matching the actual CDC WONDER county-level export format
_COL_ALIASES: dict[str, list[str]] = {
    "county_name": ["county"],
    "county_fips": ["county code"],
    "deaths":      ["deaths"],
    "population":  ["population"],
    "crude_rate":  ["crude rate"],
}


# ---------------------------------------------------------------------------
# Loader class
# ---------------------------------------------------------------------------

class CDCLoader:
    """
    Loads CDC WONDER cause-of-death data from a tab-delimited export file.

    Usage::

        loader = CDCLoader()
        df = loader.load_all()
    """

    def __init__(self, datasets_dir: str | Path | None = None) -> None:
        if datasets_dir is None:
            datasets_dir = Path(__file__).parent.parent.parent / "datasets"
        self.datasets_dir = Path(datasets_dir)
        self.cdc_path = self.datasets_dir / CDC_FILE

        if not self.cdc_path.exists():
            raise FileNotFoundError(
                f"CDC WONDER file not found at {self.cdc_path}."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> pd.DataFrame:
        """
        Load CDC WONDER mortality data as a tidy DataFrame.

        Returns
        -------
        pd.DataFrame
            One row per county with deaths, population, and crude_rate.
            county_fips is zero-padded to 5 characters.
            state_abbr is parsed from the county name string.
            Note: this export is a 2018–2024 aggregate — no year column.

        Notes
        -----
        - "Suppressed" and "Unreliable" values in numeric columns are coerced
          to NaN (small-count suppression by CDC).
        - Crude rate is per 100,000 population.
        """
        # Try reading as tab-delimited text (CDC WONDER export format)
        try:
            raw = pd.read_csv(
                self.cdc_path,
                sep="\t",
                dtype=str,           # read all as str; coerce numerics later
                encoding="utf-8",
            )
        except UnicodeDecodeError:
            raw = pd.read_csv(
                self.cdc_path,
                sep="\t",
                dtype=str,
                encoding="latin-1",
            )

        # Drop the CDC "Notes" metadata column if present
        raw = raw[[c for c in raw.columns if c.lower().strip() != "notes"]]

        # Normalise column names
        raw.columns = [c.strip().lower() for c in raw.columns]

        # Map to canonical field names
        col_map: dict[str, str] = {}
        for canonical, aliases in _COL_ALIASES.items():
            for alias in aliases:
                if alias in raw.columns:
                    col_map[canonical] = alias
                    break

        missing = [f for f in _COL_ALIASES if f not in col_map]
        if missing:
            logger.warning("CDC: columns not found for fields: %s", missing)

        # Filter: keep rows where County Code looks like a 5-digit FIPS
        county_code_col = col_map.get("county_fips")
        if county_code_col:
            fips_mask = raw[county_code_col].str.strip().str.match(r'^\d{5}$', na=False)
            raw = raw[fips_mask].reset_index(drop=True)
        else:
            logger.warning("CDC: 'county_fips' column not found — returning empty.")
            return pd.DataFrame()

        if raw.empty:
            logger.warning("CDC loader returned no records after filtering.")
            return pd.DataFrame()

        # Build output DataFrame
        out = pd.DataFrame()
        for canonical, source_col in col_map.items():
            out[canonical] = raw[source_col].str.strip()

        # Coerce numeric fields (suppressed/unreliable → NaN)
        for col in _NUMERIC_FIELDS:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        # Zero-pad county FIPS to 5 digits
        if "county_fips" in out.columns:
            out["county_fips"] = out["county_fips"].str.zfill(5)

        # Parse state abbreviation from county name (e.g. 'Autauga County, AL' → 'AL')
        if "county_name" in out.columns:
            out["state_abbr"] = (
                out["county_name"]
                .str.extract(r',\s*([A-Z]{2})$', expand=False)
                .str.strip()
            )

        # Note: no year column in this CDC export (2018–2024 aggregate)
        out["year"] = None
        out["data_period"] = "2018-2024"

        out = out.reset_index(drop=True)
        logger.info("CDC: loaded %d county mortality records (2018–2024 aggregate).", len(out))
        return out


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def load_cdc(datasets_dir: str | Path | None = None) -> pd.DataFrame:
    """
    Load CDC WONDER cause-of-death data as a tidy DataFrame.

    Returns
    -------
    pd.DataFrame
        One row per state × year. Numeric fields: deaths, population,
        crude_rate. "Suppressed" values are NaN.
    """
    return CDCLoader(datasets_dir=datasets_dir).load_all()
