"""
ed_loader.py — Emergency Department (ED) visits cost lookup loader.

DATASET: datasets/ED_Visits_Age_Group_2023.csv
SOURCE:  Healthcare Utilization Dataset (national, 2023)
PURPOSE: Provide static ED cost parameters for the acute healthcare cost
         component of the simulation pipeline.

KEY FINDINGS FROM DATASET EXPLORATION:
- Small file: 6 rows × 4 columns.
- Granularity: national, age-group level (not geographic).
- Two cost fields: average hospital charges and average hospital costs
  (costs ≈ actual cost to hospital; charges ≈ billed amount).
- This is a STATIC LOOKUP TABLE, not a time-series loader.
  It does not iterate over years or geographies.
- Age groups: 0yr, 1–17, 18–44, 45–64, 65–84, 85+.

FIELDS EXTRACTED:
  type_of_ed_visit: visit classification (treat-and-release, etc.)
  age_group:        age band string
  avg_charge_usd:   average hospital charges per ED visit (USD)
  avg_cost_usd:     average hospital costs per ED visit (USD)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ED_FILE = "ED_Visits_Age_Group_2023.csv"

_COL_RENAMES: dict[str, str] = {
    "Type_of_ED_Visit":                          "type_of_ed_visit",
    "Age_Group":                                  "age_group",
    "Average_Hospital_Charges_per_ED_Visit_USD":  "avg_charge_usd",
    "Average_Hospital_Costs_per_ED_Visit_USD":    "avg_cost_usd",
}

_NUMERIC_FIELDS: frozenset[str] = frozenset({"avg_charge_usd", "avg_cost_usd"})


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class EDLoader:
    """
    Loads the ED visits cost lookup table.

    Usage::

        loader = EDLoader()
        df = loader.load_all()

        # Typical usage: get the cost for 18–44 treat-and-release visits
        cost = loader.get_cost(age_group="Age 18-44 years", cost_type="avg_cost_usd")
    """

    def __init__(self, datasets_dir: str | Path | None = None) -> None:
        if datasets_dir is None:
            datasets_dir = Path(__file__).parent.parent.parent / "datasets"
        self.datasets_dir = Path(datasets_dir)
        self.ed_path = self.datasets_dir / ED_FILE

        if not self.ed_path.exists():
            raise FileNotFoundError(
                f"ED visits file not found at {self.ed_path}."
            )

        self._df: pd.DataFrame | None = None  # cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> pd.DataFrame:
        """
        Load the ED cost lookup table.

        Returns
        -------
        pd.DataFrame
            6 rows × 4 columns: type_of_ed_visit, age_group,
            avg_charge_usd, avg_cost_usd.
        """
        if self._df is not None:
            return self._df

        df = pd.read_csv(self.ed_path)

        # Rename columns to canonical names
        rename_map = {}
        for src_col in df.columns:
            for original, canonical in _COL_RENAMES.items():
                if src_col.strip() == original:
                    rename_map[src_col] = canonical
                    break
        df = df.rename(columns=rename_map)

        for col in _NUMERIC_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Normalise string columns
        for col in ["type_of_ed_visit", "age_group"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        self._df = df.reset_index(drop=True)
        logger.info("ED: loaded %d cost lookup rows.", len(self._df))
        return self._df

    def get_cost(
        self,
        age_group: str | None = None,
        visit_type: str | None = None,
        cost_type: str = "avg_cost_usd",
    ) -> float | None:
        """
        Look up a specific cost value from the table.

        Parameters
        ----------
        age_group : str | None
            Age band string, e.g. ``"Age 18-44 years"``. If None, returns
            the mean across all age groups.
        visit_type : str | None
            Visit classification filter, e.g. ``"Treat-and-release ED visits"``.
            If None, no filter is applied.
        cost_type : str
            ``"avg_cost_usd"`` (default) or ``"avg_charge_usd"``.

        Returns
        -------
        float | None
            The matched cost value, or None if no match found.
        """
        df = self.load_all()
        if cost_type not in df.columns:
            logger.warning("ED: cost_type %r not found.", cost_type)
            return None

        mask = pd.Series([True] * len(df))
        if age_group is not None:
            mask &= df["age_group"].str.lower() == age_group.lower()
        if visit_type is not None:
            mask &= df["type_of_ed_visit"].str.lower() == visit_type.lower()

        matched = df[mask][cost_type]
        if matched.empty:
            logger.warning(
                "ED: no match for age_group=%r, visit_type=%r.", age_group, visit_type
            )
            return None
        return float(matched.mean())


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def load_ed(datasets_dir: str | Path | None = None) -> pd.DataFrame:
    """
    Load the ED visits cost lookup table.

    Returns
    -------
    pd.DataFrame
        6 rows: one per age group. Columns: type_of_ed_visit, age_group,
        avg_charge_usd, avg_cost_usd.
    """
    return EDLoader(datasets_dir=datasets_dir).load_all()
