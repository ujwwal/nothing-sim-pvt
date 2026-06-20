"""
quality_gate.py — Data quality checks and simulation bypass conditions.

PURPOSE:
  Enforces the Responsible AI constraints defined in DATASET_REGISTRY.md:
  - Missingness > 25% in critical fields → disable simulation
  - Data older than 18 months → warn
  - Sub-population < 100 individuals → block simulation run
  - Structural NaN rate > threshold → surface to dashboard

  Also computes a basic Population Stability Index (PSI) for drift detection.

DESIGN:
  All checks are stateless functions that return typed results. They do not
  mutate the DataFrame. The caller (API layer or dashboard) decides what to
  do with the result (warn, block, log).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from pipeline.schema import CRITICAL_FIELDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (from DATASET_REGISTRY.md)
# ---------------------------------------------------------------------------

MAX_MISSINGNESS_PCT: float = 0.25     # 25% — triggers simulation disable
MAX_DATA_AGE_DAYS: int = 548          # ~18 months
MIN_COHORT_SIZE: int = 100            # below this → block simulation
PSI_WARN_THRESHOLD: float = 0.10     # mild distribution shift
PSI_ALERT_THRESHOLD: float = 0.20    # structural shift → recommend retraining


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class QualityCheckResult:
    """Result of a single quality check."""
    check_name: str
    passed: bool
    severity: str           # "info", "warning", "error"
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        icon = {"info": "ℹ", "warning": "⚠", "error": "✗"}.get(self.severity, "?")
        return f"{icon} [{self.check_name}] {self.message}"


@dataclass
class GateDecision:
    """
    Final go/no-go decision from the quality gate.

    Attributes
    ----------
    simulation_enabled : bool
        False if any hard-block condition is triggered.
    checks : list[QualityCheckResult]
        All individual check results.
    block_reasons : list[str]
        Human-readable reasons if simulation is disabled.
    """
    simulation_enabled: bool
    checks: list[QualityCheckResult] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return any(c.severity == "warning" for c in self.checks)

    @property
    def has_errors(self) -> bool:
        return any(c.severity == "error" for c in self.checks)

    def summary(self) -> str:
        lines = [
            f"Simulation enabled: {self.simulation_enabled}",
            f"Checks run: {len(self.checks)}",
        ]
        if self.block_reasons:
            lines.append("Block reasons:")
            lines.extend(f"  - {r}" for r in self.block_reasons)
        lines.extend(str(c) for c in self.checks if c.severity != "info")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_missingness(
    df: pd.DataFrame,
    fields: list[str] | None = None,
    threshold: float = MAX_MISSINGNESS_PCT,
) -> QualityCheckResult:
    """
    Check whether critical fields exceed the missingness threshold.

    Parameters
    ----------
    df : pd.DataFrame
        Merged pipeline DataFrame.
    fields : list[str] | None
        Fields to check. Defaults to CRITICAL_FIELDS from schema.
    threshold : float
        Missingness fraction that triggers a block (default 0.25).

    Returns
    -------
    QualityCheckResult
        severity="error" if any critical field exceeds threshold.
    """
    check_fields = fields or CRITICAL_FIELDS
    present = [f for f in check_fields if f in df.columns]
    missing = [f for f in check_fields if f not in df.columns]

    missingness: dict[str, float] = {}
    violations: list[str] = []
    for col in present:
        rate = df[col].isna().mean()
        missingness[col] = round(rate, 4)
        if rate > threshold:
            violations.append(f"{col} ({rate:.1%})")

    passed = len(violations) == 0
    severity = "error" if not passed else ("warning" if missing else "info")
    message = (
        f"Missingness OK — all critical fields below {threshold:.0%}."
        if passed
        else f"Critical fields exceed {threshold:.0%} missingness: {violations}"
    )
    if missing:
        message += f" [Columns not in DataFrame: {missing}]"

    return QualityCheckResult(
        check_name="missingness",
        passed=passed,
        severity=severity,
        message=message,
        details={"missingness_by_field": missingness, "violations": violations},
    )


def check_data_age(
    df: pd.DataFrame,
    year_col: str = "year",
    reference_date: date | None = None,
    max_age_days: int = MAX_DATA_AGE_DAYS,
) -> QualityCheckResult:
    """
    Check whether the most recent year in the data is within the age limit.

    Parameters
    ----------
    df : pd.DataFrame
    year_col : str
        Column containing the reporting year.
    reference_date : date | None
        Reference date for age calculation. Defaults to today.
    max_age_days : int
        Maximum allowed data age in days (default ~18 months).

    Returns
    -------
    QualityCheckResult
    """
    ref = reference_date or date.today()
    if year_col not in df.columns or df.empty:
        return QualityCheckResult(
            check_name="data_age",
            passed=False,
            severity="warning",
            message=f"Column '{year_col}' not found or DataFrame is empty.",
        )

    max_year = int(df[year_col].max())
    # Assume data for year Y is released in mid-year Y+1; use Jan 1 of Y+1 as proxy
    data_date = date(max_year + 1, 1, 1)
    age_days = (ref - data_date).days
    passed = age_days <= max_age_days

    return QualityCheckResult(
        check_name="data_age",
        passed=passed,
        severity="warning" if not passed else "info",
        message=(
            f"Most recent data year: {max_year}. "
            f"Estimated age: ~{age_days} days "
            f"({'exceeds' if not passed else 'within'} {max_age_days}-day limit)."
        ),
        details={"max_year": max_year, "estimated_age_days": age_days},
    )


def check_cohort_size(
    df: pd.DataFrame,
    population_col: str = "exits_total",
    min_size: int = MIN_COHORT_SIZE,
) -> QualityCheckResult:
    """
    Check whether any CoC × year cohort falls below the minimum population.

    Uses ``exits_total`` (always available from SPM) as the cohort size proxy
    by default. Set ``population_col`` to ``"overall_homeless"`` if PIT data
    is joined and a raw population count is preferred.

    Simulation must be blocked for sub-populations below this threshold to
    prevent overfitting and preserve individual privacy.

    Parameters
    ----------
    df : pd.DataFrame
    population_col : str
        Column containing the cohort population count.
    min_size : int
        Minimum allowed cohort size (default 100).

    Returns
    -------
    QualityCheckResult
        severity="error" if any row falls below the threshold.
    """
    if population_col not in df.columns:
        return QualityCheckResult(
            check_name="cohort_size",
            passed=True,   # cannot check — treat as pass but warn
            severity="warning",
            message=f"Column '{population_col}' not found; cohort size check skipped.",
        )

    # Rows with NaN population are "no data" — flag separately from genuine sub-threshold
    nan_rows     = df[df[population_col].isna()]
    present_rows = df[df[population_col].notna()]
    below        = present_rows[present_rows[population_col] < min_size]

    passed = len(below) == 0
    details: dict[str, Any] = {
        "n_below_threshold": len(below),
        "n_no_data":         len(nan_rows),
        "threshold":         min_size,
    }
    if len(nan_rows) > 0 and passed:
        # Some CoCs have no population data at all — warn but don't block
        return QualityCheckResult(
            check_name="cohort_size",
            passed=True,
            severity="warning",
            message=(
                f"All cohorts with data meet minimum size ({min_size}), but "
                f"{len(nan_rows)} CoC(s) have no {population_col} data (no data ≠ zero)."
            ),
            details=details,
        )
    return QualityCheckResult(
        check_name="cohort_size",
        passed=passed,
        severity="error" if not passed else "info",
        message=(
            f"All cohorts meet minimum size ({min_size})."
            if passed
            else f"{len(below)} cohorts have fewer than {min_size} individuals."
        ),
        details=details,
    )


def check_structural_nans(
    df: pd.DataFrame,
    structural_col: str = "structural_nan_fields",
) -> QualityCheckResult:
    """
    Report the proportion of rows with structural NaN flags.

    This is informational — structural NaNs are expected and valid.
    High rates may indicate a systemic data reporting issue.
    """
    if structural_col not in df.columns:
        return QualityCheckResult(
            check_name="structural_nans",
            passed=True,
            severity="info",
            message="structural_nan_fields column not present; check skipped.",
        )

    has_structural = df[structural_col].apply(
        lambda x: isinstance(x, list) and len(x) > 0
    )
    rate = has_structural.mean()
    return QualityCheckResult(
        check_name="structural_nans",
        passed=True,   # structural NaNs are always valid
        severity="info",
        message=(
            f"{has_structural.sum()} rows ({rate:.1%}) have structural NaN fields. "
            "These are valid 'not applicable' values — do not impute."
        ),
        details={"structural_nan_row_count": int(has_structural.sum()), "rate": round(rate, 4)},
    )


def compute_psi(
    reference: pd.Series,
    current: pd.Series,
    n_bins: int = 10,
) -> float:
    """
    Compute Population Stability Index between a reference and current distribution.

    PSI < 0.1  → no significant change
    PSI 0.1–0.2 → moderate change, investigate
    PSI > 0.2  → significant shift, recommend retraining

    Parameters
    ----------
    reference : pd.Series
        Reference (baseline) distribution of a numeric feature.
    current : pd.Series
        Current distribution of the same feature.
    n_bins : int
        Number of equal-width bins for discretisation.

    Returns
    -------
    float
        PSI value. Returns NaN if calculation fails.
    """
    try:
        ref_clean = reference.dropna()
        cur_clean = current.dropna()
        if len(ref_clean) < 10 or len(cur_clean) < 10:
            return float("nan")

        # Bin edges from reference distribution
        _, edges = np.histogram(ref_clean, bins=n_bins)
        # Add epsilon to edges to ensure all values fall in a bin
        edges[0] -= 1e-9
        edges[-1] += 1e-9

        ref_counts, _ = np.histogram(ref_clean, bins=edges)
        cur_counts, _ = np.histogram(cur_clean, bins=edges)

        ref_pct = ref_counts / ref_counts.sum()
        cur_pct = cur_counts / cur_counts.sum()

        # Replace zeros to avoid log(0)
        ref_pct = np.where(ref_pct == 0, 1e-6, ref_pct)
        cur_pct = np.where(cur_pct == 0, 1e-6, cur_pct)

        psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
        return float(psi)
    except Exception as exc:  # noqa: BLE001
        logger.debug("PSI computation failed: %s", exc)
        return float("nan")


# ---------------------------------------------------------------------------
# Master gate
# ---------------------------------------------------------------------------

def run_quality_gate(
    df: pd.DataFrame,
    reference_df: pd.DataFrame | None = None,
    psi_fields: list[str] | None = None,
    external_shock: bool = False,
) -> GateDecision:
    """
    Run all quality checks and return a go/no-go gate decision.

    Parameters
    ----------
    df : pd.DataFrame
        Merged pipeline DataFrame to evaluate.
    reference_df : pd.DataFrame | None
        Historical reference DataFrame for PSI drift detection.
        If None, PSI checks are skipped.
    psi_fields : list[str] | None
        Numeric fields to compute PSI on. Defaults to key SPM fields.
    external_shock : bool
        If True, simulation is hard-blocked regardless of data quality.
        Used during pandemics, natural disasters, etc.

    Returns
    -------
    GateDecision
        Contains simulation_enabled flag, all check results, and block reasons.
    """
    checks: list[QualityCheckResult] = []
    block_reasons: list[str] = []

    # --- Hard block: external shock override ---
    if external_shock:
        return GateDecision(
            simulation_enabled=False,
            checks=[],
            block_reasons=["External shock flag is active. System is in Manual Stress-Testing mode."],
        )

    # --- Missingness check (hard block if exceeded) ---
    miss_check = check_missingness(df)
    checks.append(miss_check)
    if not miss_check.passed:
        block_reasons.append(
            f"Critical field missingness exceeds {MAX_MISSINGNESS_PCT:.0%} threshold."
        )

    # --- Data age check (advisory warning only) ---
    checks.append(check_data_age(df))

    # --- Cohort size check (hard block if any below threshold) ---
    cohort_check = check_cohort_size(df)
    checks.append(cohort_check)
    if not cohort_check.passed:
        block_reasons.append(
            f"One or more cohorts have fewer than {MIN_COHORT_SIZE} individuals."
        )

    # --- Structural NaN report (informational) ---
    checks.append(check_structural_nans(df))

    # --- PSI drift detection (advisory) ---
    if reference_df is not None:
        default_psi_fields = [
            "overall_homeless", "chronic_homeless_total",
            "pct_returns_12m", "pct_exit_to_ph",
        ]
        fields_to_check = psi_fields or default_psi_fields
        for fname in fields_to_check:
            if fname in df.columns and fname in reference_df.columns:
                psi_val = compute_psi(reference_df[fname], df[fname])
                if not pd.isna(psi_val):
                    if psi_val > PSI_ALERT_THRESHOLD:
                        sev = "warning"
                        msg = (
                            f"PSI={psi_val:.3f} for '{fname}' — structural shift detected "
                            f"(>{PSI_ALERT_THRESHOLD}). Recommend model retraining."
                        )
                    elif psi_val > PSI_WARN_THRESHOLD:
                        sev = "warning"
                        msg = f"PSI={psi_val:.3f} for '{fname}' — moderate shift. Investigate."
                    else:
                        sev = "info"
                        msg = f"PSI={psi_val:.3f} for '{fname}' — stable."
                    checks.append(QualityCheckResult(
                        check_name=f"psi_{fname}",
                        passed=True,
                        severity=sev,
                        message=msg,
                        details={"psi": psi_val, "field": fname},
                    ))

    simulation_enabled = len(block_reasons) == 0
    decision = GateDecision(
        simulation_enabled=simulation_enabled,
        checks=checks,
        block_reasons=block_reasons,
    )

    if not simulation_enabled:
        logger.error("Quality gate BLOCKED simulation:\n%s", decision.summary())
    elif decision.has_warnings:
        logger.warning("Quality gate passed with warnings:\n%s", decision.summary())
    else:
        logger.info("Quality gate passed. Simulation enabled.")

    return decision
