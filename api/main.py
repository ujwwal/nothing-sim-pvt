from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from contextlib import asynccontextmanager
import logging

from api.pipeline.merger import build_pipeline
from api.pipeline.quality_gate import run_quality_gate
from api.calibration.transition_calibrator import calibrate_transitions
from api.simulation import MarkovSimulation

logger = logging.getLogger(__name__)

# --- Singleton State ---
class AppState:
    df_merged: pd.DataFrame = pd.DataFrame()
    df_params: pd.DataFrame = pd.DataFrame()
    gate_decision = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load datasets and run pipeline
    logger.info("Initializing Aegis-Sim Data Pipeline...")
    
    # We load standard years to ensure a consistent spine
    # FMR / Vera datasets are processed automatically if present
    state.df_merged = build_pipeline(spm_years=[2022, 2023, 2024], pit_years=[2022, 2023, 2024])
    
    # Run the quality gate to compute drift/missingness
    state.gate_decision = run_quality_gate(state.df_merged)
    
    # Compute Markov parameters for all CoCs
    state.df_params = calibrate_transitions(state.df_merged)
    
    logger.info(f"Pipeline ready. Processed {len(state.df_merged)} CoC-year records.")
    yield
    # Shutdown logic
    state.df_merged = pd.DataFrame()
    state.df_params = pd.DataFrame()


app = FastAPI(title="Aegis-Sim API", description="Simulation & Data API for Aegis-Sim", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Aegis-Sim API is running", "records_loaded": len(state.df_merged)}

@app.get("/api/data-health")
def get_data_health():
    if state.gate_decision is None:
        raise HTTPException(status_code=503, detail="Pipeline still initializing")
        
    return {
        "simulation_enabled": state.gate_decision.simulation_enabled,
        "block_reasons": state.gate_decision.block_reasons,
        "checks": [
            {
                "name": c.check_name,
                "passed": c.passed,
                "severity": c.severity,
                "message": c.message,
                "details": c.details
            } for c in state.gate_decision.checks
        ]
    }

class SimulationRequest(BaseModel):
    coc_id: str
    year: int
    scenario: str = "delay"
    delay_years: int = 0
    invisible_population_estimate: str = "medium"
    exogenous_shock: bool = False

@app.post("/api/simulation/run")
def run_simulation(req: SimulationRequest):
    if req.exogenous_shock:
        raise HTTPException(
            status_code=400, 
            detail="Exogenous System Shock mode active. Switch to Manual Stress-Testing."
        )

    # Filter for specific CoC and year
    row_spm = state.df_merged[(state.df_merged['coc_number'] == req.coc_id) & (state.df_merged['year'] == req.year)]
    if row_spm.empty:
        raise HTTPException(status_code=404, detail=f"Data not found for CoC {req.coc_id} in {req.year}")
        
    # Check CoC-specific missingness (missingness > 25% for critical fields)
    from api.pipeline.quality_gate import check_missingness, check_cohort_size
    
    miss_check = check_missingness(row_spm)
    if not miss_check.passed:
        raise HTTPException(
            status_code=400, 
            detail="Data Insufficiency: missingness threshold exceeded. Simulation blocked."
        )
        
    cohort_check = check_cohort_size(row_spm)
    if not cohort_check.passed:
        raise HTTPException(
            status_code=400, 
            detail="Sub-population Threshold Violation: cohort too small. Simulation blocked."
        )
        
    row_spm_s = row_spm.iloc[0]
        
    # Get parameters
    row_param = state.df_params[(state.df_params['coc_number'] == req.coc_id) & (state.df_params['year'] == req.year)]
    if row_param.empty:
        raise HTTPException(status_code=404, detail="Parameters not calculated for this CoC")
        
    row_param_s = row_param.iloc[0]
    
    # Combine original data + parameters to feed the engine
    combined_data = pd.concat([row_spm_s, row_param_s])
    
    sim = MarkovSimulation()
    results = sim.run_scenario(combined_data, delay_years=req.delay_years)
    
    # The output format is already designed to match the prompt specifications
    return results
