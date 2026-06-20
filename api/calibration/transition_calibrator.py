"""
transition_calibrator.py — Markov transition probability estimation.

PURPOSE:
  Estimates empirical Markov transition probabilities from the cleaned,
  merged pipeline DataFrame. This is the only module that interprets
  SPM fields as model parameters — no transition logic belongs in loaders.

DESIGN PRINCIPLES:
  - All probabilities are computed from raw numerator/denominator columns,
    not from pre-computed percentage fields, for full auditability.
  - Structural NaN rows (denominator == 0) are excluded from estimation.
  - CoCs with fewer than MIN_EXITS_FOR_ESTIMATION exits are pooled into a
    national or category-level estimate to avoid noisy small-sample rates.
  - All outputs are annotated with the sample size and pooling level used.
  - No simulation logic lives here — this module produces parameters only.

MARKOV STATES (from DATASET_REGISTRY.md):
  S = {Stable Housing, Emergency Shelter, Unsheltered, Acute Emergency Care,
       Incarcerated, Deceased}

TRANSITION PROBABILITIES ESTIMATED HERE:
  From SPM 2 (Returns to Homelessness):
    P(Sheltered | Stable)  ≈ 12-month return rate (pct_returns_12m)
    P(Stable | Stable)     = 1 − P(Sheltered | Stable)

  From SPM 7 (Exits to Permanent Housing):
    P(Stable | Sheltered)  ≈ pct_exit_to_ph (exits to permanent housing)
    P(Stable | ES)         ≈ same metric (ES/TH/SH/RRH exits to permanent housing)

  From PIT:
    P(Unsheltered → Sheltered) is not directly observable in SPM 7 —
    approximated as (sheltered_total / overall_homeless) for a CoC × year.

  From CDC (future):
    P(Deceased | any state) is a separate mortality hazard, not estimated here yet.
    Placeholder column is included in output for downstream use.

  NOTE: These are single-step, discrete-time annual transition probabilities.
  The 12-month horizon from SPM aligns with the annual model timestep.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum number of exits required for CoC-level estimation.
# Below this, the CoC is pooled into the category or national estimate.
MIN_EXITS_FOR_ESTIMATION: int = 50

# Pooling hierarchy: coc → coc_category → national
POOLING_LEVELS: list[str] = ["coc", "coc_category", "national"]


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

@dataclass
class TransitionEstimate:
    """
    Estimated transition probabilities for one CoC × year.

    All probabilities are in [0, 1]. None indicates the estimate could not
    be computed (e.g. no data, structural NaN, insufficient sample).
    """

    # --- Key ---
    coc_number: str
    year: int
    coc_category: str | None = None

    # --- P(return to homelessness | was housed) ---
    # Source: SPM 2, 12-month cohort
    # Denominator: exits_total; Numerator: returns_12m
    p_return_12m: float | None = None
    p_return_12m_n: int | None = None       # sample size (exits_total)
    p_return_12m_pool: str = "coc"          # pooling level used

    # --- P(exit to permanent housing | in shelter/transitional) ---
    # Source: SPM 7
    # Denominator: exits_to_ph_universe; Numerator: exits_to_ph
    p_exit_to_ph: float | None = None
    p_exit_to_ph_n: int | None = None
    p_exit_to_ph_pool: str = "coc"

    # --- P(retain permanent housing | placed in PH) ---
    # Source: SPM 7
    # Denominator: ph_retention_universe; Numerator: ph_retained
    p_ph_retention: float | None = None
    p_ph_retention_n: int | None = None
    p_ph_retention_pool: str = "coc"

    # --- P(sheltered | overall homeless) — shelter utilisation rate ---
    # Source: PIT (requires PIT data in merged DataFrame)
    p_sheltered_given_homeless: float | None = None
    p_sheltered_given_homeless_n: int | None = None

    # --- Implied complementary probabilities ---
    @property
    def p_stable_given_housed(self) -> float | None:
        """P(remain stably housed | was housed at t) = 1 − p_return_12m."""
        if self.p_return_12m is None:
            return None
        return max(0.0, 1.0 - self.p_return_12m)

    # --- Placeholder for mortality hazard (future: from CDC data) ---
    p_deceased: float | None = None         # Not yet estimated

    # --- Data quality ---
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coc_number": self.coc_number,
            "year": self.year,
            "coc_category": self.coc_category,
            "p_return_12m": self.p_return_12m,
            "p_return_12m_n": self.p_return_12m_n,
            "p_return_12m_pool": self.p_return_12m_pool,
            "p_stable_given_housed": self.p_stable_given_housed,
            "p_exit_to_ph": self.p_exit_to_ph,
            "p_exit_to_ph_n": self.p_exit_to_ph_n,
            "p_exit_to_ph_pool": self.p_exit_to_ph_pool,
            "p_ph_retention": self.p_ph_retention,
            "p_ph_retention_n": self.p_ph_retention_n,
            "p_ph_retention_pool": self.p_ph_retention_pool,
            "p_sheltered_given_homeless": self.p_sheltered_given_homeless,
            "p_sheltered_given_homeless_n": self.p_sheltered_given_homeless_n,
            "p_deceased": self.p_deceased,
            "flags": self.flags,
        }


# ---------------------------------------------------------------------------
# Calibrator class
# ---------------------------------------------------------------------------

class TransitionCalibrator:
    """
    Estimates Markov transition probabilities from the merged pipeline DataFrame.

    Usage::

        from pipeline.merger import build_pipeline
        from calibration.transition_calibrator import TransitionCalibrator

        df = build_pipeline()
        calibrator = TransitionCalibrator(df)
        estimates = calibrator.estimate_all()      # list of TransitionEstimate
        df_params = calibrator.to_dataframe()      # tidy DataFrame

    Pooling:
    - If a CoC has fewer than MIN_EXITS_FOR_ESTIMATION exits, its rate is
      replaced by the weighted mean of all CoCs in the same coc_category.
    - If category-level data is also sparse, national-level pooling is used.
    - The pooling level is recorded in the ``*_pool`` fields.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        """
        Parameters
        ----------
        df : pd.DataFrame
            Merged pipeline DataFrame from PipelineMerger.build() or
            build_pipeline(). Must contain SPM columns at minimum.
        """
        self.df = df.copy()
        self._validate_input()

        # Pre-compute pooled (category and national) estimates for fallback
        self._category_pools: dict[tuple[str, int], dict[str, Any]] = {}
        self._national_pools: dict[int, dict[str, Any]] = {}
        self._build_pool_tables()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_all(self, years: list[int] | None = None) -> list[TransitionEstimate]:
        """
        Estimate transition probabilities for all CoC × year rows.

        Parameters
        ----------
        years : list[int] | None
            Subset of years to estimate. Defaults to all years in the DataFrame.

        Returns
        -------
        list[TransitionEstimate]
        """
        df = self.df
        if years is not None:
            df = df[df["year"].isin(years)]

        estimates: list[TransitionEstimate] = []
        for _, row in df.iterrows():
            est = self._estimate_row(row)
            estimates.append(est)

        logger.info(
            "TransitionCalibrator: estimated %d CoC×year transition probabilities.",
            len(estimates),
        )
        return estimates

    def to_dataframe(self, years: list[int] | None = None) -> pd.DataFrame:
        """
        Return transition estimates as a tidy DataFrame.

        Returns
        -------
        pd.DataFrame
            One row per CoC × year. Key columns: p_return_12m,
            p_stable_given_housed, p_exit_to_ph, p_ph_retention,
            p_sheltered_given_homeless, plus sample-size and pooling columns.
        """
        estimates = self.estimate_all(years=years)
        return pd.DataFrame([e.to_dict() for e in estimates])

    # ------------------------------------------------------------------
    # Row-level estimation
    # ------------------------------------------------------------------

    def _estimate_row(self, row: pd.Series) -> TransitionEstimate:
        coc_number = str(row.get("coc_number", ""))
        year = int(row.get("year", 0))
        coc_category = row.get("coc_category") or None
        flags: list[str] = []

        est = TransitionEstimate(
            coc_number=coc_number,
            year=year,
            coc_category=coc_category,
        )

        # --- P(return | housed) from SPM 2 ---
        exits_total = _safe_float(row.get("exits_total"))
        returns_12m = _safe_float(row.get("returns_12m"))

        if exits_total is not None and exits_total >= MIN_EXITS_FOR_ESTIMATION:
            if returns_12m is not None:
                est.p_return_12m = _safe_rate(returns_12m, exits_total)
                est.p_return_12m_n = int(exits_total)
                est.p_return_12m_pool = "coc"
        else:
            # Pool to category or national
            pooled = self._pool_return_12m(coc_category, year)
            if pooled is not None:
                est.p_return_12m = pooled["rate"]
                est.p_return_12m_n = pooled["n"]
                est.p_return_12m_pool = pooled["level"]
                flags.append(f"p_return_12m_pooled_to_{pooled['level']}")

        # --- P(exit to PH | sheltered) from SPM 7 ---
        ph_universe = _safe_float(row.get("exits_to_ph_universe"))
        ph_exits = _safe_float(row.get("exits_to_ph"))

        if ph_universe is not None and ph_universe >= MIN_EXITS_FOR_ESTIMATION:
            if ph_exits is not None:
                est.p_exit_to_ph = _safe_rate(ph_exits, ph_universe)
                est.p_exit_to_ph_n = int(ph_universe)
                est.p_exit_to_ph_pool = "coc"
        else:
            pooled = self._pool_exit_to_ph(coc_category, year)
            if pooled is not None:
                est.p_exit_to_ph = pooled["rate"]
                est.p_exit_to_ph_n = pooled["n"]
                est.p_exit_to_ph_pool = pooled["level"]
                flags.append(f"p_exit_to_ph_pooled_to_{pooled['level']}")

        # --- P(retain PH | placed in PH) from SPM 7 ---
        ph_ret_universe = _safe_float(row.get("ph_retention_universe"))
        ph_retained = _safe_float(row.get("ph_retained"))

        if ph_ret_universe is not None and ph_ret_universe >= MIN_EXITS_FOR_ESTIMATION:
            if ph_retained is not None:
                est.p_ph_retention = _safe_rate(ph_retained, ph_ret_universe)
                est.p_ph_retention_n = int(ph_ret_universe)
                est.p_ph_retention_pool = "coc"
        else:
            pooled = self._pool_ph_retention(coc_category, year)
            if pooled is not None:
                est.p_ph_retention = pooled["rate"]
                est.p_ph_retention_n = pooled["n"]
                est.p_ph_retention_pool = pooled["level"]
                flags.append(f"p_ph_retention_pooled_to_{pooled['level']}")

        # --- P(sheltered | homeless) from PIT data ---
        overall = _safe_float(row.get("overall_homeless"))
        sheltered = _safe_float(row.get("sheltered_total"))
        if overall is not None and overall > 0 and sheltered is not None:
            est.p_sheltered_given_homeless = _safe_rate(sheltered, overall)
            est.p_sheltered_given_homeless_n = int(overall)

        est.flags = flags
        return est

    # ------------------------------------------------------------------
    # Pool table construction
    # ------------------------------------------------------------------

    def _build_pool_tables(self) -> None:
        """Pre-compute category-level and national-level pooled estimates."""
        df = self.df

        def weighted_rate(num_col: str, denom_col: str) -> pd.Series:
            """Compute sum(num) / sum(denom) within a group, ignoring NaN."""
            return lambda g: (
                g[num_col].sum() / g[denom_col].sum()
                if g[denom_col].sum() > 0 else np.nan
            )

        # Category × year pools
        if "coc_category" in df.columns:
            for (cat, year), grp in df.groupby(["coc_category", "year"]):
                self._category_pools[(str(cat), int(year))] = {
                    "return_12m": {
                        "rate": _safe_rate(
                            grp["returns_12m"].sum(), grp["exits_total"].sum()
                        ),
                        "n": int(grp["exits_total"].sum()),
                    },
                    "exit_to_ph": {
                        "rate": _safe_rate(
                            grp["exits_to_ph"].sum(), grp["exits_to_ph_universe"].sum()
                        ),
                        "n": int(grp["exits_to_ph_universe"].sum()),
                    },
                    "ph_retention": {
                        "rate": _safe_rate(
                            grp["ph_retained"].sum(), grp["ph_retention_universe"].sum()
                        ),
                        "n": int(grp["ph_retention_universe"].sum()),
                    },
                }

        # National × year pools
        for year, grp in df.groupby("year"):
            self._national_pools[int(year)] = {
                "return_12m": {
                    "rate": _safe_rate(
                        grp["returns_12m"].sum(), grp["exits_total"].sum()
                    ),
                    "n": int(grp["exits_total"].sum()),
                },
                "exit_to_ph": {
                    "rate": _safe_rate(
                        grp["exits_to_ph"].sum(), grp["exits_to_ph_universe"].sum()
                    ),
                    "n": int(grp["exits_to_ph_universe"].sum()),
                },
                "ph_retention": {
                    "rate": _safe_rate(
                        grp["ph_retained"].sum(), grp["ph_retention_universe"].sum()
                    ),
                    "n": int(grp["ph_retention_universe"].sum()),
                },
            }

    def _pool_return_12m(
        self, coc_category: str | None, year: int
    ) -> dict[str, Any] | None:
        key = (str(coc_category), year)
        if key in self._category_pools and self._category_pools[key]["return_12m"]["n"] > 0:
            d = self._category_pools[key]["return_12m"]
            return {"rate": d["rate"], "n": d["n"], "level": "coc_category"}
        if year in self._national_pools:
            d = self._national_pools[year]["return_12m"]
            return {"rate": d["rate"], "n": d["n"], "level": "national"}
        return None

    def _pool_exit_to_ph(
        self, coc_category: str | None, year: int
    ) -> dict[str, Any] | None:
        key = (str(coc_category), year)
        if key in self._category_pools and self._category_pools[key]["exit_to_ph"]["n"] > 0:
            d = self._category_pools[key]["exit_to_ph"]
            return {"rate": d["rate"], "n": d["n"], "level": "coc_category"}
        if year in self._national_pools:
            d = self._national_pools[year]["exit_to_ph"]
            return {"rate": d["rate"], "n": d["n"], "level": "national"}
        return None

    def _pool_ph_retention(
        self, coc_category: str | None, year: int
    ) -> dict[str, Any] | None:
        key = (str(coc_category), year)
        if key in self._category_pools and self._category_pools[key]["ph_retention"]["n"] > 0:
            d = self._category_pools[key]["ph_retention"]
            return {"rate": d["rate"], "n": d["n"], "level": "coc_category"}
        if year in self._national_pools:
            d = self._national_pools[year]["ph_retention"]
            return {"rate": d["rate"], "n": d["n"], "level": "national"}
        return None

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(self) -> None:
        required = ["year", "coc_number", "exits_total", "returns_12m",
                    "exits_to_ph_universe", "exits_to_ph"]
        missing = [c for c in required if c not in self.df.columns]
        if missing:
            logger.warning(
                "TransitionCalibrator: required columns missing from input: %s. "
                "Some estimates will be NaN.",
                missing,
            )


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> float | None:
    """Convert value to float, returning None on failure or NaN."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _safe_rate(numerator: Any, denominator: Any) -> float | None:
    """Compute numerator / denominator safely, returning None on invalid input."""
    n = _safe_float(numerator)
    d = _safe_float(denominator)
    if n is None or d is None or d == 0.0:
        return None
    rate = n / d
    # Clamp to [0, 1] — rates should not exceed 1.0
    return float(max(0.0, min(1.0, rate)))


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def calibrate_transitions(
    df: pd.DataFrame,
    years: list[int] | None = None,
) -> pd.DataFrame:
    """
    Estimate Markov transition probabilities from a merged pipeline DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Output from build_pipeline() or PipelineMerger.build().
    years : list[int] | None
        Subset of years to estimate. Defaults to all years in df.

    Returns
    -------
    pd.DataFrame
        One row per CoC × year with estimated transition probabilities.
        Key columns:
        - p_return_12m          : P(return to homelessness within 12m | housed)
        - p_stable_given_housed : 1 − p_return_12m
        - p_exit_to_ph          : P(exit to permanent housing | sheltered)
        - p_ph_retention        : P(retain PH ≥6mo | placed in PH)
        - p_sheltered_given_homeless : fraction of homeless who are sheltered
        - *_n                   : sample size for each estimate
        - *_pool                : pooling level ("coc", "coc_category", "national")
        - flags                 : list of data quality annotations
    """
    return TransitionCalibrator(df).to_dataframe(years=years)
