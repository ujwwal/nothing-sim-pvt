"""
schema.py — Unified schema contract for the Aegis-Sim data pipeline.

PURPOSE:
  Defines the canonical column names, types, and validation rules that every
  loader must conform to before entering the merge layer. Also provides the
  typed output schema for the fully merged pipeline DataFrame.

DESIGN PRINCIPLES:
  - Each loader produces a "loader output" DataFrame with source-specific
    columns. schema.py does NOT force all loaders to share a single table —
    it defines the *identity columns* they must all carry, and the merge
    target schema that results after joining.
  - Validation is advisory (logs warnings) rather than hard-failing, so the
    pipeline degrades gracefully when individual datasets have gaps.
  - The geographic unit is heterogeneous: SPM and PIT use CoC number;
    Vera and CDC use county/state FIPS. The merger handles the join.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required identity columns per loader
# ---------------------------------------------------------------------------
# Each loader's output DataFrame must contain these columns (may be NaN for
# schema-drift cases, but the column must exist).

REQUIRED_COLS: dict[str, list[str]] = {
    "spm":     ["year", "coc_number", "state"],
    "pit_coc": ["year", "coc_number", "coc_name"],
    "vera":    ["year", "county_fips", "state_abbr"],
    "cdc":     ["county_fips", "county_name", "deaths"],
    "ed":      ["age_group", "avg_cost_usd"],
}

# ---------------------------------------------------------------------------
# Merged pipeline output schema
# ---------------------------------------------------------------------------
# After all loaders are joined, the merged DataFrame has this column contract.
# Columns are grouped by source. All numeric columns are float64.
# String/identifier columns are object dtype.

MERGED_SCHEMA: dict[str, dict[str, Any]] = {
    # --- Identifiers ---
    "year":                           {"dtype": "int",   "source": "all"},
    "coc_number":                     {"dtype": "str",   "source": "spm/pit"},
    "coc_name":                       {"dtype": "str",   "source": "pit"},
    "coc_category":                   {"dtype": "str",   "source": "pit/spm"},
    "state":                          {"dtype": "str",   "source": "spm"},
    # --- SPM 2: Returns to homelessness ---
    "exits_total":                    {"dtype": "float", "source": "spm"},
    "returns_6m":                     {"dtype": "float", "source": "spm"},
    "returns_12m":                    {"dtype": "float", "source": "spm"},
    "returns_24m":                    {"dtype": "float", "source": "spm"},
    "pct_returns_6m":                 {"dtype": "float", "source": "spm"},
    "pct_returns_12m":                {"dtype": "float", "source": "spm"},
    "pct_returns_24m":                {"dtype": "float", "source": "spm"},
    # --- SPM 7: Housing exits ---
    "exits_to_ph_universe":           {"dtype": "float", "source": "spm"},
    "exits_to_ph":                    {"dtype": "float", "source": "spm"},
    "pct_exit_to_ph":                 {"dtype": "float", "source": "spm"},
    "ph_retention_universe":          {"dtype": "float", "source": "spm"},
    "ph_retained":                    {"dtype": "float", "source": "spm"},
    "pct_ph_retention":               {"dtype": "float", "source": "spm"},
    # --- SPM 1: Length of homelessness ---
    "los_avg_days":                   {"dtype": "float", "source": "spm"},
    "los_median_days":                {"dtype": "float", "source": "spm"},
    # --- PIT: Population counts ---
    "overall_homeless":               {"dtype": "float", "source": "pit"},
    "sheltered_total":                {"dtype": "float", "source": "pit"},
    "unsheltered_total":              {"dtype": "float", "source": "pit"},
    "chronic_homeless_total":         {"dtype": "float", "source": "pit"},
    "chronic_homeless_sheltered":     {"dtype": "float", "source": "pit"},
    "chronic_homeless_unsheltered":   {"dtype": "float", "source": "pit"},
    "chronic_individuals_total":      {"dtype": "float", "source": "pit"},
    # --- Vera: Incarceration (county → CoC aggregated) ---
    "total_jail_pop":                 {"dtype": "float", "source": "vera"},
    "total_prison_pop":               {"dtype": "float", "source": "vera"},
    "total_jail_pop_rate":            {"dtype": "float", "source": "vera"},
    # --- CDC: Mortality ---
    "deaths":                         {"dtype": "float", "source": "cdc"},
    "population":                     {"dtype": "float", "source": "cdc"},
    "crude_rate":                     {"dtype": "float", "source": "cdc"},
    # --- Data quality ---
    "structural_nan_fields":          {"dtype": "list",  "source": "spm"},
    "missing_fields":                 {"dtype": "list",  "source": "spm/pit"},
    "pipeline_flags":                 {"dtype": "list",  "source": "pipeline"},
}

# Critical fields for simulation — missingness checked by quality gate
CRITICAL_FIELDS: list[str] = [
    "exits_total",
    "returns_12m",
    "pct_returns_12m",
    "exits_to_ph_universe",
    "exits_to_ph",
    "pct_exit_to_ph",
    "overall_homeless",
    "chronic_homeless_total",
]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of schema validation for one loader's output."""
    source: str
    passed: bool
    missing_cols: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "✓ PASS" if self.passed else "✗ FAIL"
        parts = [f"[{self.source}] {status}"]
        if self.missing_cols:
            parts.append(f"  Missing columns: {self.missing_cols}")
        for w in self.warnings:
            parts.append(f"  Warning: {w}")
        return "\n".join(parts)


def validate_loader_output(df: pd.DataFrame, source: str) -> ValidationResult:
    """
    Validate that a loader's output DataFrame has the required identity columns.

    Parameters
    ----------
    df : pd.DataFrame
        Output from a loader (e.g. load_spm(), load_pit()).
    source : str
        Loader source key: one of 'spm', 'pit_coc', 'vera', 'cdc', 'ed'.

    Returns
    -------
    ValidationResult
        Contains pass/fail status, missing columns, and warnings.
    """
    required = REQUIRED_COLS.get(source, [])
    missing = [c for c in required if c not in df.columns]
    warnings_list: list[str] = []

    if df.empty:
        warnings_list.append("DataFrame is empty.")

    # Check for null identifiers in required columns
    for col in required:
        if col in df.columns:
            null_count = df[col].isna().sum()
            if null_count > 0:
                warnings_list.append(
                    f"Column '{col}' has {null_count} null values "
                    f"({null_count / len(df):.1%} of rows)."
                )

    passed = len(missing) == 0
    result = ValidationResult(
        source=source,
        passed=passed,
        missing_cols=missing,
        warnings=warnings_list,
    )

    if not passed:
        logger.error("Schema validation FAILED for '%s': %s", source, result)
    elif warnings_list:
        logger.warning("Schema validation passed with warnings for '%s': %s",
                       source, result)
    else:
        logger.info("Schema validation passed for '%s'.", source)

    return result


def validate_all(loader_outputs: dict[str, pd.DataFrame]) -> dict[str, ValidationResult]:
    """
    Validate all loader outputs in one call.

    Parameters
    ----------
    loader_outputs : dict[str, pd.DataFrame]
        Mapping of source key → DataFrame (e.g. {"spm": df_spm, "pit_coc": df_pit}).

    Returns
    -------
    dict[str, ValidationResult]
    """
    return {src: validate_loader_output(df, src) for src, df in loader_outputs.items()}
