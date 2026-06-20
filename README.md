# QuietCost — The Cost of Doing Nothing

> **USAII Global AI Hackathon 2026 · Challenge 6: AI for Systems & Society**  
> Direction A: The Cost of Doing Nothing Simulator

[![Next.js](https://img.shields.io/badge/Next.js-15.0-black?logo=next.js)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python)](https://python.org/)
[![License](https://img.shields.io/badge/license-Private-red)](#)

---

## What Is QuietCost?

**QuietCost** is a transparent, auditable fiscal simulation platform that helps municipal decision-makers understand the **long-term financial consequences of delaying supportive housing interventions** for people experiencing chronic homelessness.

The core question it answers:

> *"How much more does it cost taxpayers if we wait 3 years before acting, compared to acting today?"*

It uses a **Discrete-Time Markov State Transition Model** with **1,000 Monte Carlo simulation runs** to produce probability ranges — never single-point forecasts. All outputs include uncertainty bands calibrated from real HUD data.

---

## Key Principles

| Principle | Implementation |
|-----------|---------------|
| **Transparency** | All assumptions are documented and visible in the UI |
| **No black boxes** | Full methodology page, preprocessing audit trail |
| **Human-in-the-loop** | No automated policy decisions — ever |
| **Range estimates only** | Every output shown as a probability band |
| **Responsible AI** | Auto-disables when data is stale or unreliable |
| **Responsible AI (Gemini)** | AI summaries are clearly labeled and grounded in model outputs |

---

## Screenshots

The platform is a full-stack Next.js + FastAPI web application with a dark glassmorphism aesthetic.

| Page | Description |
|------|-------------|
| **Home** | Landing page with live sample KPIs and feature overview |
| **Simulation** | Main simulation runner with scenario controls and AI-generated policy brief |
| **Dashboard** | Overview of all scenario results and key metrics |
| **Data Health** | Real-time monitoring of 11 registered datasets |
| **Methodology** | Full technical documentation of the model |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Frontend (Vercel)                           │
│          Next.js 15 · React 19 · TypeScript                 │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────┐  │
│  │  /home   │  │ /simulate│  │ /dashboard │  │/data-hlth│  │
│  └──────────┘  └────┬─────┘  └────────────┘  └──────────┘  │
│                     │ fetch /api/simulation/run             │
└─────────────────────┼───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│              Backend (Hugging Face Spaces)                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Data Pipeline (builds once at startup)             │   │
│  │  HUD PIT Count → TransitionCalibrator → per-CoC     │   │
│  │  lookup table + national-pool fallback               │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│  ┌──────────────────────▼──────────────────────────────┐   │
│  │  MarkovSimulation                                   │   │
│  │  • 6-state Discrete-Time Markov Chain               │   │
│  │  • 1,000 Monte Carlo iterations                     │   │
│  │  • 10-year horizon (monthly time-steps)             │   │
│  │  • NP-COD = cost(scenario) − cost(act_now)          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│               AI Summary Layer (Gemini API)                 │
│  Simulation results → Gemini 3.1 Flash-Lite → Plain-lang    │
│  policy brief with examples, risks, and actionable steps    │
└─────────────────────────────────────────────────────────────┘
```

---

## The Simulation Model

### Six Markov States

| State | Annual Cost | Risk Level |
|-------|------------|------------|
| Stable Housing | $12,000/yr | Low |
| Emergency Shelter | $25,000/yr | Moderate |
| Street Homelessness | $45,000/yr | High |
| Jail / Justice System | $60,000/yr | Very High |
| Acute Healthcare (ER) | $85,000/yr | Critical |
| Deceased | Absorbing | Terminal |

### Three Scenarios

1. **Act Now** — Immediate Permanent Supportive Housing (PSH) rollout (delay = 0 years)
2. **Delay Intervention** — Wait 1–10 years before acting
3. **Do Nothing** — No intervention for the full 10-year horizon (delay = 10 years)

### Invisible Population Multipliers

PIT Counts systematically undercount unsheltered individuals (Culhane et al., 2020). QuietCost surfaces three estimates:

| Estimate | Multiplier |
|---------|-----------|
| Low | 0.80× |
| Medium | 1.00× |
| High | 1.50× |

### Net Present Cost of Delay (NP-CoD)

```
NP-CoD = Cumulative 10-yr cost(scenario) − Cumulative 10-yr cost(act_now)
```

This is the additional taxpayer burden attributable **specifically to the delay**. It is always computed from two full Monte Carlo runs (baseline + scenario), never hardcoded.

---

## Datasets (11 Registered)

| # | Dataset | Source | Purpose |
|---|---------|--------|---------|
| 1 | System-Performance-Measures-Data.xlsx | HUD | Transition probability calibration |
| 2 | ED_Visits_Age_Group_2023.csv | Healthcare Utilization | ER cost estimates |
| 3 | CoC_AwardComp_NatlTerrDC_2024.pdf | HUD | PSH funding & cost proxy |
| 4 | CoC_HIC_NatlTerrDC_2025.pdf | HUD Housing Inventory | Shelter capacity |
| 5 | HUD PIT Count | HUD | Baseline population counts |
| 6 | Vera Institute Incarceration | Vera Institute | Jail cost estimates |
| 7 | CDC WONDER Cause of Death | CDC | Mortality rate calibration |
| 8 | HUD Fair Market Rents | HUD | PSH cost baseline |
| 9 | USPS ZIP-FIPS Crosswalk | USPS | Geographic standardization |
| 10 | NHGIS Census Boundaries | NHGIS | Geographic harmonization |
| 11 | NSDUH Detailed Tables 2024 | SAMHSA | Behavioral health assumptions |

---

## Tech Stack

### Frontend

| Library | Version | Purpose |
|---------|---------|---------|
| Next.js | 15.0.0 | React framework (App Router) |
| React | 19.0.0 | UI library |
| TypeScript | 5.4 | Type safety |
| Tailwind CSS | 3.4 | Utility CSS |
| Framer Motion | 11.0 | Animations & transitions |
| Recharts | 2.12 | Area charts & data visualisation |
| Zustand | 4.5 | Global state (simulation results) |
| Lucide React | 0.360 | Icon system |

### Backend

| Library | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.110.0 | REST API + OpenAPI docs |
| Uvicorn | 0.29.0 | ASGI server |
| Pandas | 2.2.1 | Data manipulation |
| NumPy | 1.26.4 | Numerical computing |
| SciPy | 1.12.0 | Statistical utilities |
| Pydantic | 2.6.4 | Request/response validation |
| Pandera | 0.18.3 | DataFrame schema validation |
| openpyxl | 3.1.2 | Excel file reading |

### AI

| Service | Model | Purpose |
|---------|-------|---------|
| Google Gemini API | gemini-3.1-flash-lite | Post-simulation AI policy brief |

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 18.0.0
- **Python** ≥ 3.9
- **npm** ≥ 9.0.0
- **Gemini API Key** (optional, for AI summaries — get one free at [Google AI Studio](https://aistudio.google.com/))

### 1. Clone & Install

```bash
git clone <repo-url>
cd nothing-sim-pvt

# Install frontend dependencies
npm install --legacy-peer-deps
```

### 2. Configure Environment

Create a `.env.local` file in the project root:

```env
# Optional: enables AI-generated policy briefs after each simulation
NEXT_PUBLIC_GEMINI_API_KEY=your_gemini_api_key_here

# Backend API base URL (default: http://localhost:8000)
NEXT_PUBLIC_API_URL=http://localhost:8000
```

> **Note:** The Gemini API key is optional. Without it, the simulation will show a template-based brief that works completely offline. The key is prefixed `NEXT_PUBLIC_` because it is used client-side. For production, consider routing Gemini calls through the backend instead.

### 3. Run the Backend

```bash
cd api

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install Python dependencies
pip install -r requirements.txt

# Start the API server
uvicorn main:app --reload --port 8000
```

API docs available at: **http://localhost:8000/docs**

### 4. Run the Frontend

In a new terminal (from the project root):

```bash
npm run dev
```

App available at: **http://localhost:3000**

### Windows: One-Click Launch

Use the provided `launch.bat` to start both servers simultaneously.

---

## Production Deployment

### 1. Deploy the Backend to Hugging Face Spaces

The backend API is deployed as a Docker space on Hugging Face.

1. Ensure you have the `huggingface_hub` Python package installed.
2. Authenticate using `huggingface-cli login`.
3. Go to your Hugging Face Space settings and add your private dataset token as the `HF_TOKEN` secret.
4. Run the upload script from the project root to push the `api/` folder:

```bash
python upload_space.py
```

### 2. Deploy the Frontend to Vercel

The frontend is a standard Next.js application hosted on Vercel.

1. Install the Vercel CLI: `npm i -g vercel`.
2. Link your project to Vercel using `vercel link`.
3. Make sure to configure the Vercel environment variables:
   - `BACKEND_URL`: Set this to the URL of your Hugging Face Space (e.g., `https://ujwwal-quietcost-api.hf.space`).
   - `NEXT_PUBLIC_GEMINI_API_KEY`: Set this to your Gemini API key.
4. Deploy the project:

```bash
vercel deploy --prod
```

---

## Project Structure

```
nothing-sim-pvt/
├── app/                          # Next.js App Router pages
│   ├── layout.tsx                # Root layout (nav, background, fonts)
│   ├── globals.css               # Design system (glass, orbs, tokens)
│   ├── page.tsx                  # Landing / home page
│   ├── simulation/page.tsx       # Main simulation runner
│   ├── dashboard/page.tsx        # Results dashboard
│   ├── data-health/page.tsx      # Dataset health monitor
│   └── methodology/page.tsx      # Technical methodology
├── api/                          # FastAPI backend
│   ├── main.py                   # App entrypoint + routes
│   ├── simulation.py             # Markov + Monte Carlo engine
│   ├── data_pipeline.py          # Dataset ingestion & mock pipeline
│   ├── calibration/              # Transition probability calibration
│   ├── loaders/                  # Per-dataset file loaders
│   ├── pipeline/                 # Data merging & SPM processing
│   └── requirements.txt          # Python dependencies
├── components/
│   └── Navigation.tsx            # Sidebar navigation component
├── lib/
│   └── store.ts                  # Zustand global state store
├── DATASET_REGISTRY.md           # Full dataset registry & project rules
├── REQUIREMENTS.md               # Detailed setup instructions
├── package.json
└── README.md                     # This file
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_GEMINI_API_KEY` | Optional | Gemini API key for AI policy briefs. Free tier available. Without this key, a template-based brief is shown. |
| `NEXT_PUBLIC_API_URL` | Optional | Backend URL. Defaults to `http://localhost:8000`. |

---

## Responsible AI Design

QuietCost is built with the following safety constraints **hard-coded**:

- ✅ **No individual decisions** — the model operates at population level only
- ✅ **No single-point forecasts** — every output is a probability range
- ✅ **Auto-disable** — simulation is blocked when data is older than 18 months, missingness exceeds 25%, or population falls below 100
- ✅ **Transparent assumptions** — all assumptions are visible, documented, and auditable in the UI
- ✅ **AI transparency** — Gemini summaries are clearly labelled as AI-generated and grounded only in the model's own output data
- ✅ **Human-in-the-loop** — the platform provides information, never recommendations or decisions

---

## API Reference

The backend exposes a self-documenting OpenAPI interface at **http://localhost:8000/docs**.

### `POST /api/simulation/run`

Runs the full Markov simulation for a given scenario.

**Request body:**
```json
{
  "scenario": "act_now | delay | do_nothing",
  "delay_years": 3,
  "invisible_population_estimate": "low | medium | high",
  "coc_number": "national"
}
```

**Response includes:**
- `projections` — year-by-year population and cost arrays
- `np_cod` — Net Present Cost of Delay (median)
- `confidence_interval` — 80% CI bounds on NP-CoD
- `total_10yr_cost_median` — 10-year cumulative cost (p50)
- `calibrated_params` — the transition probabilities used

### `GET /api/data-health`

Returns dataset health status, drift flags, and pipeline metadata.

---

## Common Issues

| Issue | Solution |
|-------|---------|
| `'next' is not recognized` | Run `npm install --legacy-peer-deps` |
| npm peer dependency conflicts | Use `--legacy-peer-deps` flag (React 19 + lucide-react) |
| Python `ModuleNotFoundError` | Activate venv first: `source venv/bin/activate` |
| Port 3000 already in use | `npm run dev -- -p 3001` |
| Port 8000 already in use | `uvicorn main:app --port 8001` |
| Gemini API key not working | Ensure key is prefixed `NEXT_PUBLIC_` in `.env.local` |

---

## Methodology

The full technical methodology is available at **http://localhost:3000/methodology** once the app is running. It covers:

- Markov state transition matrix construction
- Monte Carlo simulation methodology
- HUD SPM calibration pipeline
- NP-CoD calculation derivation
- Invisible population multiplier rationale
- Data quality and safety thresholds

---

## License

This project is **private** and was created for the USAII Global AI Hackathon 2026. All rights reserved.

---

*QuietCost does not make policy decisions. It does not determine individual eligibility. It does not automate policy. Humans remain responsible for all final decisions.*
