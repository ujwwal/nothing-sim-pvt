import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

# Configuration
N_SIMULATIONS = 1000
HORIZON_MONTHS = 120

# Monthly Cost Schedule
# Stable Housing (PSH): $89/night
# Emergency Shelter: $35/night
# Street/Unsheltered: $40/night
# Incarcerated: $129/night
# Acute ER Care: $974/visit (assume 1 visit = 3 days)
# Deceased: $0

DAYS_IN_MONTH = 30.4375

MONTHLY_COSTS = np.array([
    0.0,                  # 0: Stable Housing (Intervention cost tracked separately; stops penalty accumulation)
    35 * DAYS_IN_MONTH,   # 1: Emergency Shelter
    40 * DAYS_IN_MONTH,   # 2: Street/Unsheltered
    129 * DAYS_IN_MONTH,  # 3: Jail
    974.0,                # 4: Acute Healthcare (flat cost per month they are in state)
    0.0                   # 5: Deceased
])

STATE_NAMES = [
    "Stable Housing",
    "Emergency Shelter",
    "Street Homelessness",
    "Jail",
    "Acute Healthcare",
    "Deceased"
]

class MarkovSimulation:
    def __init__(self, n_simulations: int = N_SIMULATIONS, horizon_months: int = HORIZON_MONTHS):
        self.n_simulations = n_simulations
        self.horizon_months = horizon_months
        self.n_states = 6
        
    def _annual_to_monthly(self, p_annual: np.ndarray) -> np.ndarray:
        """
        Convert annual transition matrix to monthly using:
        P_monthly = 1 - (1 - P_annual)^(1/12) applied to off-diagonals.
        Diagonals are then adjusted so rows sum to 1.
        """
        p_monthly = np.zeros_like(p_annual)
        for i in range(self.n_states):
            for j in range(self.n_states):
                if i != j:
                    p_monthly[i, j] = 1.0 - (1.0 - p_annual[i, j]) ** (1/12.0)
                    
        # Adjust diagonals to sum to 1
        for i in range(self.n_states):
            row_sum = np.sum(p_monthly[i, :])
            # Handle float imprecision or >1 row sums
            if row_sum > 1.0:
                p_monthly[i, :] = p_monthly[i, :] / row_sum
                p_monthly[i, i] = 0.0
            else:
                p_monthly[i, i] = 1.0 - row_sum
                
        return p_monthly
        
    def generate_transition_matrix(self, row: pd.Series, delay_years: int = 0) -> np.ndarray:
        """
        Builds the base annual transition matrix from a CoC's transition parameters,
        converts to monthly, and applies intervention delays.
        """
        # Extract calibrated parameters (with fallbacks if NaN)
        p_return_12m = float(row.get("p_return_12m", 0.10))
        if np.isnan(p_return_12m): p_return_12m = 0.10
        
        p_exit_to_ph = float(row.get("p_exit_to_ph", 0.35))
        if np.isnan(p_exit_to_ph): p_exit_to_ph = 0.35
        
        p_ph_retention = float(row.get("p_ph_retention", 0.90))
        if np.isnan(p_ph_retention): p_ph_retention = 0.90
        
        # Base annual transition matrix (P_annual)
        # States: 0=Stable, 1=Shelter, 2=Street, 3=Jail, 4=ER, 5=Deceased
        P_ann = np.zeros((self.n_states, self.n_states))
        
        # From Stable Housing
        P_ann[0, 1] = p_return_12m * 0.7  # Returns mostly to shelter
        P_ann[0, 2] = p_return_12m * 0.3  # Some returns to street
        P_ann[0, 5] = 0.01  # Base mortality
        P_ann[0, 0] = max(0, 1.0 - P_ann[0, 1] - P_ann[0, 2] - P_ann[0, 5])
        
        # From Emergency Shelter
        P_ann[1, 0] = p_exit_to_ph
        P_ann[1, 2] = 0.20  # Flow to street
        P_ann[1, 3] = 0.05  # Flow to jail
        P_ann[1, 4] = 0.05  # Flow to ER
        P_ann[1, 5] = 0.02  # Mortality
        P_ann[1, 1] = max(0, 1.0 - np.sum(P_ann[1, [0,2,3,4,5]]))
        
        # From Street
        P_ann[2, 0] = p_exit_to_ph * 0.5  # Harder to exit directly from street
        P_ann[2, 1] = 0.25  # Flow to shelter
        P_ann[2, 3] = 0.10  # Flow to jail
        P_ann[2, 4] = 0.10  # Flow to ER
        P_ann[2, 5] = 0.04  # Higher mortality on street
        P_ann[2, 2] = max(0, 1.0 - np.sum(P_ann[2, [0,1,3,4,5]]))
        
        # From Jail (Assumed short stays, mostly return to street/shelter)
        P_ann[3, 0] = 0.05
        P_ann[3, 1] = 0.30
        P_ann[3, 2] = 0.50
        P_ann[3, 4] = 0.05
        P_ann[3, 5] = 0.01
        P_ann[3, 3] = max(0, 1.0 - np.sum(P_ann[3, [0,1,2,4,5]]))
        
        # From ER
        P_ann[4, 0] = 0.05
        P_ann[4, 1] = 0.40
        P_ann[4, 2] = 0.40
        P_ann[4, 3] = 0.05
        P_ann[4, 5] = 0.05
        P_ann[4, 4] = max(0, 1.0 - np.sum(P_ann[4, [0,1,2,3,5]]))
        
        # Deceased is absorbing
        P_ann[5, 5] = 1.0
        
        # Convert to monthly
        P_month = self._annual_to_monthly(P_ann)
        
        # Apply delay penalty (if delay_years > 0, the probability of exiting to PH is reduced to 0 during the delay)
        # We handle the time-dependent delay dynamically in the run loop, but here we just return the base matrices.
        return P_month

    def run_scenario(self, row: pd.Series, delay_years: int = 0) -> Dict[str, Any]:
        """
        Runs the Monte Carlo simulation for 1000 paths over 120 months.
        """
        P_base = self.generate_transition_matrix(row, delay_years=0)
        
        # If there's a delay, we create a worsened matrix for the delay period
        P_delayed = np.copy(P_base)
        if delay_years > 0:
            # Zero out exits to permanent housing from shelter and street during delay
            for i in [1, 2, 3, 4]:
                exit_prob = P_delayed[i, 0]
                P_delayed[i, 0] = 0.0
                # redistribute to staying in current state
                P_delayed[i, i] += exit_prob
                
        delay_months = delay_years * 12

        # Initial Population distribution
        overall_homeless = float(row.get("overall_homeless", 1000))
        if np.isnan(overall_homeless): overall_homeless = 1000
        
        sheltered = float(row.get("sheltered_total", overall_homeless * 0.4))
        if np.isnan(sheltered): sheltered = overall_homeless * 0.4
        
        unsheltered = overall_homeless - sheltered
        
        # Starting state vector: all in Shelter (1) or Street (2)
        initial_pop = np.array([0, int(sheltered), int(unsheltered), 0, 0, 0], dtype=np.int32)
        
        # To avoid a slow python loop for multinomials over 1000 paths * 120 months * 6 states,
        # we will use the property that sum of multinomials is multinomial. 
        # But each path has its own state vector. 
        # We will loop over time steps and paths, which takes ~ 1-2 seconds in numpy.
        
        # paths[path_idx, month, state]
        history = np.zeros((self.n_simulations, self.horizon_months, self.n_states), dtype=np.int32)
        
        # Initialize month 0
        history[:, 0, :] = initial_pop
        
        # Monte Carlo loop
        for t in range(1, self.horizon_months):
            P_current = P_delayed if t <= delay_months else P_base
            
            # For each path
            for path_idx in range(self.n_simulations):
                current_state = history[path_idx, t-1, :]
                
                next_state = np.zeros(self.n_states, dtype=np.int32)
                for s in range(self.n_states):
                    pop_in_s = current_state[s]
                    if pop_in_s > 0:
                        if s == 5: # Absorbing state optimization
                            next_state[5] += pop_in_s
                        else:
                            transitions = np.random.multinomial(pop_in_s, P_current[s, :])
                            next_state += transitions
                
                history[path_idx, t, :] = next_state
                
        # Compute costs (paths, months)
        # multiply history (paths, months, states) by MONTHLY_COSTS (states) -> sum over states
        path_costs = np.sum(history * MONTHLY_COSTS, axis=2)
        
        # Cumulative costs over time (paths, months)
        cumulative_costs = np.cumsum(path_costs, axis=1)
        
        # Final cumulative cost per path
        final_costs = cumulative_costs[:, -1]
        
        # Aggregation across paths for output
        results = []
        for t in range(self.horizon_months):
            # Population bounds (Total Homeless = Shelter + Street + Jail + ER)
            # Basically sum of states 1, 2, 3, 4
            homeless_pop = np.sum(history[:, t, 1:5], axis=1)
            cost_t = cumulative_costs[:, t]
            
            results.append({
                "month": t,
                "year": 2024 + (t // 12),
                
                "population_median": float(np.median(homeless_pop)),
                "population_lower_80": float(np.percentile(homeless_pop, 10)),
                "population_upper_80": float(np.percentile(homeless_pop, 90)),
                "population_lower_95": float(np.percentile(homeless_pop, 2.5)),
                "population_upper_95": float(np.percentile(homeless_pop, 97.5)),
                
                "cost_median": float(np.median(cost_t)),
                "cost_lower_80": float(np.percentile(cost_t, 10)),
                "cost_upper_80": float(np.percentile(cost_t, 90)),
                "cost_lower_95": float(np.percentile(cost_t, 2.5)),
                "cost_upper_95": float(np.percentile(cost_t, 97.5))
            })
            
        return {
            "scenario": "delay" if delay_years > 0 else "act_now",
            "delay_years": delay_years,
            "np_cod": float(np.median(final_costs)),
            "projections": results,
            "final_cost_ci": {
                "lower_80": float(np.percentile(final_costs, 10)),
                "upper_80": float(np.percentile(final_costs, 90)),
                "lower_95": float(np.percentile(final_costs, 2.5)),
                "upper_95": float(np.percentile(final_costs, 97.5)),
            }
        }
