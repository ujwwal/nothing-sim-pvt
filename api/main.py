from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import json

app = FastAPI(title="Aegis-Sim API", description="Simulation & Data API for Aegis-Sim")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Aegis-Sim API is running"}

@app.get("/api/data-health")
def get_data_health():
    from api.data_pipeline import MockDataPipeline
    pipeline = MockDataPipeline()
    info = pipeline.inspect_directory()
    
    return {
        "status": info.get("status", "operational"),
        "datasets_monitored": info.get("discovered_count", 0),
        "registry": info.get("registry", []),
        "drift_detected": False,
        "missing_data_pct": 5.2
    }

class SimulationRequest(BaseModel):
    scenario: str
    delay_years: int = 0
    invisible_population_estimate: str = "medium"

@app.post("/api/simulation/run")
def run_simulation(req: SimulationRequest):
    # Placeholder for Markov Model + Monte Carlo
    # Returns median, 80% CI, 95% CI
    return {
        "scenario": req.scenario,
        "delay_years": req.delay_years,
        "np_cod": 12500000.0, # Net Present Cost of Delay
        "projections": [
            {"year": 2024, "cost": 5000000, "population": 850},
            {"year": 2025, "cost": 5250000, "population": 880},
            {"year": 2026, "cost": 5600000, "population": 910},
        ],
        "confidence_interval": {
            "lower_80": 11000000.0,
            "upper_80": 14000000.0
        }
    }