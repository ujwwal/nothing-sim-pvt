"""
spm_loader.py — HUD System Performance Measures (SPM) loader.

DATASET: datasets/System-Performance-Measures-Data.xlsx
SOURCE:  HUD (Continuum of Care level, annual, 2015–2024)
PURPOSE: Produce a clean, standardised CoC × year DataFrame for the unified
         data pipeline. No model assumptions are made here.

KEY FINDINGS FROM DATASET EXPLORATION:
- One sheet per reporting year (2015–2024), sheet name = str(year).
- Two-row merged headers: row 0 = SPM group label (spans across merged cells),
  row 1 = sub-metric name. Handled by normalising the MultiIndex.
- Schema change: 2015 has 46 columns; 2016+ has 96 columns (SPM 2 was split
  by program type: SO / ES / TH / SH / PH / All).
  → Column mapping uses keyword matching, not positional indexing.
- Header layout change: 2015–2018 place identifier labels (State, CoC) in
  row 1 (sub); 2019+ place them in row 0 (group). Both variants are matched.
- Structural NaNs: when a CoC reports 0 exits for a program type, the
  corresponding percentage columns are NaN — not missing, but mathematically
  undefined (0/0). These must NOT be imputed.
  → Per-row `structural_nan_fields` list documents which fields are affected.
- Identifier: 'HUD CoC Number' (positional col 2) matches [A-Z]{2}-\\d{3}\\w?.
  One known non-standard value: MO-604K — kept as-is.
- No footer/total rows observed. All rows are valid CoC records.
- CoC count per year: ~386–405.

FIELDS EXTRACTED:
  Identifiers:     state, coc_number, coc_name, coc_category
  SPM 1 (Length):  los_avg_days, los_median_days
  SPM 2 (Returns): exits_total, returns_{6m,12m,24m}, pct_returns_{6m,12m,24m}
  SPM 7 (Housing): exits_to_ph_universe, exits_to_ph, pct_exit_to_ph,
                   ph_retention_universe, ph_retained, pct_ph_retention
  DQ flags:        structural_nan_fields, missing_fields
"""

from __future__ import annotations

import logging
import re
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPM_FILE_NAME = "System-Performance-Measures-Data.xlsx"

# CoC identifier pattern — the primary key for each row.
COC_ID_PATTERN = re.compile(r"^[A-Z]{2}-\d{3}\w?$")

# ---------------------------------------------------------------------------
# Column-matching utilities
# ---------------------------------------------------------------------------
# Maps canonical field name → ordered list of (group_keyword, sub_keyword).
# Both keywords are matched as case-insensitive substrings.
# An empty string ("") for either keyword matches anything.
# The first matching column (left-to-right) wins.
_COL_MATCHERS: dict[str, list[tuple[str, str]]] = {
    # Identifiers — two layout variants across years:
    #   2015–2018: label is in the sub-row (row 1), group is unnamed.
    #   2019+:     label is in the group-row (row 0), sub is empty.
    "state":                [("",  "state"),             ("state", "")],
    "coc_name":             [("",  "continuum of care"), ("continuum of care", "")],
    "coc_number":           [("",  "hud coc number"),    ("hud coc number", "")],
    "coc_category":         [("",  "ahar part 1"),       ("ahar part 1", "")],

    # SPM 1 — Length of Time Homeless
    "los_avg_days":         [("spm 1",       "es-sh-th avg"),
                             ("bed coverage", "es-sh-th avg"),
                             ("bed coverage", "es-sh avg")],
    "los_median_days":      [("spm 1",       "es-sh-th median"),
                             ("bed coverage", "es-sh-th median"),
                             ("bed coverage", "es-sh median")],

    # SPM 2 — Returns to Homelessness (aggregate "all" group preferred;
    #          2015 only has undivided SPM 1/2 structure as fallback)
    "exits_total":          [("spm 2 (all)", "total persons exited"),
                             ("spm 1",       "total persons exited"),
                             ("spm 2",       "total persons exited")],
    "returns_6m":           [("spm 2 (all)", "returns in 6 mths"),
                             ("spm 1",       "returns in 6 mths"),
                             ("spm 2",       "returns in 6 mths")],
    "returns_12m":          [("spm 2 (all)", "returns in 12 mths"),
                             ("spm 1",       "returns in 12 mths"),
                             ("spm 2",       "returns in 12 mths")],
    "returns_24m":          [("spm 2 (all)", "returns in 24 mths"),
                             ("spm 2",       "returns in 24 mths")],
    "pct_returns_6m":       [("spm 2 (all)", "percent returns in 6"),
                             ("spm 2",       "percent returns in 6")],
    "pct_returns_12m":      [("spm 2 (all)", "percent returns in 12"),
                             ("spm 2",       "percent returns in 12")],
    "pct_returns_24m":      [("spm 2 (all)", "percent returns in 24"),
                             ("spm 2",       "percent returns in 24")],

    # SPM 7 — Exits to / Retention in Permanent Housing
    "exits_to_ph_universe": [("spm 7", "total persons exiting es, th, sh, ph-rrh"),
                             ("spm 5", "total persons exiting es, th")],
    "exits_to_ph":          [("spm 7", "to permanent housing"),
                             ("spm 5", "to permanent housing")],
    "pct_exit_to_ph":       [("spm 7", "successful  es"),         # double-space in source
                             ("spm 7", "successful es"),
                             ("spm 7", "percent with successful exit"),  # 2015 label
                             ("spm 5", "percent with successful")],
    "ph_retention_universe":[("spm 7", "exiting ph or remaining in ph"),
                             ("spm 7", "exiting ph (but not including ph-rrh)")],
    "ph_retained":          [("spm 7", "remained in ph"),
                             ("spm 7", "residing in ph for 6mos"),
                             ("spm 7", "exiting ph (but not including ph-rrh) residing")],
    "pct_ph_retention":     [("spm 7", "successful ph retention"),
                             ("spm 7", "successful retention or exit")],
}

# Numeric fields — dtype enforcement after DataFrame construction.
_NUMERIC_FIELDS: frozenset[str] = frozenset({
    "los_avg_days", "los_median_days",
    "exits_total", "returns_6m", "returns_12m", "returns_24m",
    "pct_returns_6m", "pct_returns_12m", "pct_returns_24m",
    "exits_to_ph_universe", "exits_to_ph", "pct_exit_to_ph",
    "ph_retention_universe", "ph_retained", "pct_ph_retention",
})

# Percentage fields whose NaN is structurally valid (denominator == 0).
_STRUCTURAL_NAN_DENOMINATORS: dict[str, str] = {
    "pct_returns_6m":   "exits_total",
    "pct_returns_12m":  "exits_total",
    "pct_returns_24m":  "exits_total",
    "pct_exit_to_ph":   "exits_to_ph_universe",
    "pct_ph_retention": "ph_retention_universe",
}


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

@dataclass
class SPMRecord:
    """One SPM observation: a single CoC for a single reporting year."""

    # --- Identifiers ---
    year: int
    state: str
    coc_number: str        # e.g. "CA-600"
    coc_name: str
    coc_category: str | None = None

    # --- SPM 1: Length of time homeless (days spent in ES/SH/TH) ---
    los_avg_days: float | None = None
    los_median_days: float | None = None

    # --- SPM 2: Returns to homelessness (aggregate, all program types) ---
    exits_total: float | None = None
    returns_6m: float | None = None
    returns_12m: float | None = None
    returns_24m: float | None = None
    pct_returns_6m: float | None = None    # NaN = structural when exits_total == 0
    pct_returns_12m: float | None = None   # NaN = structural
    pct_returns_24m: float | None = None   # NaN = structural

    # --- SPM 7: Exits to / retention in permanent housing ---
    exits_to_ph_universe: float | None = None  # persons exiting ES/TH/SH/PH-RRH
    exits_to_ph: float | None = None            # subset exiting to permanent destinations
    pct_exit_to_ph: float | None = None         # NaN = structural when universe == 0
    ph_retention_universe: float | None = None  # persons in/exiting PH (excl. RRH)
    ph_retained: float | None = None            # subset retained ≥6mo or permanent exit
    pct_ph_retention: float | None = None       # NaN = structural

    # --- Data quality flags ---
    structural_nan_fields: list[str] = field(default_factory=list)
    # ^ NaN fields where denominator == 0 (valid "not applicable", do not impute)
    missing_fields: list[str] = field(default_factory=list)
    # ^ Fields whose source column was not found in this year's sheet (schema drift)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Loader class
# ---------------------------------------------------------------------------

class SPMLoader:
    """
    Loads and normalises all annual sheets from the HUD SPM workbook.

    Produces a clean, standardised CoC × year DataFrame. No model assumptions
    or derived transition probabilities are computed here — that is the
    responsibility of the calibration layer.

    Usage::

        loader = SPMLoader()
        df = loader.load_all()                      # all years
        df = loader.load_all(years=[2020, 2021])    # subset

    Resilience guarantees:
    - Missing sheets are skipped with a WARNING.
    - Columns absent in a given year produce NaN (not an error) and are logged
      in the per-row `missing_fields` list.
    - Structural NaNs are preserved and documented; never imputed.
    """

    def __init__(self, datasets_dir: str | Path | None = None) -> None:
        if datasets_dir is None:
            datasets_dir = Path(__file__).parent.parent.parent / "datasets"
        self.datasets_dir = Path(datasets_dir)
        self.spm_path = self.datasets_dir / SPM_FILE_NAME

        if not self.spm_path.exists():
            raise FileNotFoundError(
                f"SPM workbook not found at {self.spm_path}. "
                "Ensure datasets/System-Performance-Measures-Data.xlsx is present."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def available_years(self) -> list[int]:
        """Return the list of reporting years present in the workbook."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            xl = pd.ExcelFile(self.spm_path, engine="openpyxl")
        years: list[int] = []
        for name in xl.sheet_names:
            try:
                years.append(int(name.strip()))
            except ValueError:
                logger.debug("Skipping non-year sheet: %r", name)
        return sorted(years)

    def load_all(self, years: list[int] | None = None) -> pd.DataFrame:
        """
        Load SPM data for the given years and return as a tidy DataFrame.

        Parameters
        ----------
        years : list[int] | None
            Subset of years to load. Defaults to all available years.

        Returns
        -------
        pd.DataFrame
            One row per CoC × year. Columns mirror SPMRecord fields.

        Notes
        -----
        NaN semantics:
        - Structural NaNs (pct_* columns where denominator == 0) are preserved
          as NaN and documented in the ``structural_nan_fields`` column.
          **Do not impute these** — they represent "not applicable".
        - Schema-drift NaNs (column not found in this year's sheet) are also
          NaN and documented in the ``missing_fields`` column.
          These *may* be candidates for imputation downstream.
        """
        records = self._load_records(years=years)
        if not records:
            logger.warning("SPM loader returned no records.")
            return pd.DataFrame()

        df = pd.DataFrame([r.to_dict() for r in records])

        for col in _NUMERIC_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(
            "SPM: loaded %d CoC×year records across %d years.",
            len(df),
            df["year"].nunique() if "year" in df else 0,
        )
        return df

    # ------------------------------------------------------------------
    # Internal record loading
    # ------------------------------------------------------------------

    def _load_records(
        self,
        years: list[int] | None = None,
    ) -> list[SPMRecord]:
        target_years = years if years is not None else self.available_years()
        records: list[SPMRecord] = []
        for year in target_years:
            try:
                year_records = self._load_year(year)
                records.extend(year_records)
                logger.info("SPM %d: loaded %d CoC records.", year, len(year_records))
            except Exception as exc:  # noqa: BLE001
                logger.warning("SPM %d: failed to load — %s", year, exc)
        return records

    def _load_year(self, year: int) -> list[SPMRecord]:
        """Load and parse a single year sheet."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = pd.read_excel(
                self.spm_path,
                sheet_name=str(year),
                header=[0, 1],
                engine="openpyxl",
            )

        raw.columns = self._normalise_multiindex(raw.columns)
        raw = self._filter_valid_coc_rows(raw, year)
        if raw.empty:
            logger.warning("SPM %d: no valid CoC rows after filtering.", year)
            return []

        col_map = self._build_col_map(raw.columns, year)

        return [self._parse_row(row, col_map, year) for _, row in raw.iterrows()]

    # ------------------------------------------------------------------
    # Header normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_multiindex(columns: pd.MultiIndex) -> list[tuple[str, str]]:
        """
        Flatten the two-level MultiIndex to a list of (group, sub) tuples.

        - Strips pandas ``Unnamed: N_level_M`` placeholders → "".
        - Collapses internal whitespace/newlines to a single space.
        - Forward-fills group labels across merged-cell spans so that
          e.g. "SPM 2 (All)" correctly covers all its sub-columns.
        """
        def clean(val: Any) -> str:
            s = str(val) if not pd.isna(val) else ""
            s = re.sub(r"Unnamed: \d+_level_\d+", "", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        groups, subs = [], []
        for lvl0, lvl1 in columns:
            groups.append(clean(lvl0))
            subs.append(clean(lvl1))

        # Forward-fill non-empty group labels
        last_group = ""
        filled: list[str] = []
        for g in groups:
            if g:
                last_group = g
            filled.append(last_group)

        return list(zip(filled, subs))

    # ------------------------------------------------------------------
    # Row filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_valid_coc_rows(df: pd.DataFrame, year: int) -> pd.DataFrame:
        """
        Keep only rows whose CoC Number (positional col 2) matches the
        expected pattern. Guards against future footnote/total rows.
        """
        if df.shape[1] < 3:
            return df
        coc_series = df.iloc[:, 2].astype(str).str.strip()
        mask = coc_series.str.match(COC_ID_PATTERN)
        dropped = (~mask).sum()
        if dropped:
            logger.debug("SPM %d: dropped %d non-CoC rows.", year, dropped)
        return df[mask].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Column mapping
    # ------------------------------------------------------------------

    def _build_col_map(
        self,
        normalised_cols: list[tuple[str, str]],
        year: int,
    ) -> dict[str, int]:
        """
        Build ``{canonical_field: column_index}`` via fuzzy keyword matching.

        Rules:
        - Both group_kw and sub_kw must appear as case-insensitive substrings.
        - An empty keyword ("") matches any value.
        - First matching column wins (left-to-right).
        - Unmatched fields are logged and absent from the returned dict.
        """
        cols_lower = [(g.lower(), s.lower()) for g, s in normalised_cols]
        col_map: dict[str, int] = {}
        missing: list[str] = []

        for field_name, matchers in _COL_MATCHERS.items():
            found = False
            for grp_kw, sub_kw in matchers:
                grp_kw_l, sub_kw_l = grp_kw.lower(), sub_kw.lower()
                for idx, (g_l, s_l) in enumerate(cols_lower):
                    grp_match = (not grp_kw_l) or (grp_kw_l in g_l)
                    sub_match = (not sub_kw_l) or (sub_kw_l in s_l)
                    if grp_match and sub_match:
                        col_map[field_name] = idx
                        found = True
                        break
                if found:
                    break
            if not found:
                missing.append(field_name)

        if missing:
            logger.warning("SPM %d: columns not found for fields: %s", year, missing)
        return col_map

    # ------------------------------------------------------------------
    # Row parsing
    # ------------------------------------------------------------------

    def _parse_row(
        self,
        row: pd.Series,
        col_map: dict[str, int],
        year: int,
    ) -> SPMRecord:
        """Parse a single DataFrame row into an SPMRecord."""

        def get(fname: str) -> Any:
            idx = col_map.get(fname)
            return None if (idx is None or pd.isna(row.iloc[idx])) else row.iloc[idx]

        def get_float(fname: str) -> float | None:
            v = get(fname)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def get_str(fname: str) -> str:
            v = get(fname)
            return str(v).strip() if v is not None else ""

        # Tag structural NaNs: pct field is NaN AND denominator == 0
        structural_nan: list[str] = []
        for pct_field, denom_field in _STRUCTURAL_NAN_DENOMINATORS.items():
            if get(pct_field) is None:
                denom = get_float(denom_field)
                if denom is not None and denom == 0.0:
                    structural_nan.append(pct_field)

        missing_fields = [f for f in _COL_MATCHERS if f not in col_map]

        return SPMRecord(
            year=year,
            state=get_str("state"),
            coc_number=get_str("coc_number"),
            coc_name=get_str("coc_name"),
            coc_category=get_str("coc_category") or None,
            los_avg_days=get_float("los_avg_days"),
            los_median_days=get_float("los_median_days"),
            exits_total=get_float("exits_total"),
            returns_6m=get_float("returns_6m"),
            returns_12m=get_float("returns_12m"),
            returns_24m=get_float("returns_24m"),
            pct_returns_6m=get_float("pct_returns_6m"),
            pct_returns_12m=get_float("pct_returns_12m"),
            pct_returns_24m=get_float("pct_returns_24m"),
            exits_to_ph_universe=get_float("exits_to_ph_universe"),
            exits_to_ph=get_float("exits_to_ph"),
            pct_exit_to_ph=get_float("pct_exit_to_ph"),
            ph_retention_universe=get_float("ph_retention_universe"),
            ph_retained=get_float("ph_retained"),
            pct_ph_retention=get_float("pct_ph_retention"),
            structural_nan_fields=structural_nan,
            missing_fields=missing_fields,
        )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def load_spm(
    years: list[int] | None = None,
    datasets_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Load HUD System Performance Measures data as a tidy DataFrame.

    Parameters
    ----------
    years : list[int] | None
        Reporting years to include (e.g. ``[2020, 2021, 2022]``).
        Defaults to all available years (2015–2024).
    datasets_dir : str | Path | None
        Path to the datasets directory. Defaults to ``<project_root>/datasets/``.

    Returns
    -------
    pd.DataFrame
        One row per CoC × year. 20 SPM fields + 2 DQ flag columns.
        NaN semantics are documented in ``SPMLoader.load_all()``.
    """
    return SPMLoader(datasets_dir=datasets_dir).load_all(years=years)
