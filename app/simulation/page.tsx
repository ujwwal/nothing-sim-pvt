"use client";
import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useSimulationStore } from '@/lib/store';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area, ReferenceLine } from 'recharts';
import { Play, Activity, AlertCircle } from 'lucide-react';

export default function SimulationPage() {
  const { scenario, delayYears, setScenario, setDelayYears, results } = useSimulationStore();
  const [isRunning, setIsRunning] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const runSimulation = async () => {
    setIsRunning(true);
    setErrorMsg(null);
    try {
      // 1. Run baseline (delay = 0)
      const resBaseline = await fetch('http://localhost:8000/api/simulation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ coc_id: 'CA-600', year: 2023, delay_years: 0 })
      });
      if (!resBaseline.ok) {
         const err = await resBaseline.json();
         throw new Error(err.detail || "Baseline simulation failed");
      }
      const baselineData = await resBaseline.json();

      // 2. Run delayed (delay = chosen)
      const resDelayed = await fetch('http://localhost:8000/api/simulation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ coc_id: 'CA-600', year: 2023, delay_years: delayYears })
      });
      if (!resDelayed.ok) {
         const err = await resDelayed.json();
         throw new Error(err.detail || "Delayed simulation failed");
      }
      const delayedData = await resDelayed.json();

      // 3. Run do nothing (delay = 999)
      const resDoNothing = await fetch('http://localhost:8000/api/simulation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ coc_id: 'CA-600', year: 2023, delay_years: 999 })
      });
      if (!resDoNothing.ok) {
         const err = await resDoNothing.json();
         throw new Error(err.detail || "Do Nothing simulation failed");
      }
      const doNothingData = await resDoNothing.json();

      // Merge projections for charting side-by-side cost
      const mergedProjections = delayedData.projections.map((p: any, i: number) => {
         const b = baselineData.projections[i];
         const d = doNothingData.projections[i];
         return {
            month: p.month,
            delayed_cost: p.cost_median / 1000000,
            delayed_cost_lower: p.cost_lower_80 / 1000000,
            delayed_cost_upper: p.cost_upper_80 / 1000000,
            baseline_cost: b.cost_median / 1000000,
            baseline_cost_lower: b.cost_lower_80 / 1000000,
            baseline_cost_upper: b.cost_upper_80 / 1000000,
            donothing_cost: d.cost_median / 1000000,
            donothing_cost_lower: d.cost_lower_80 / 1000000,
            donothing_cost_upper: d.cost_upper_80 / 1000000,
            population: p.population_median
         };
      });

      const costOfInaction = doNothingData.np_cod - baselineData.np_cod;

      useSimulationStore.getState().setResults({
         np_cod: delayedData.np_cod,
         baseline_np_cod: baselineData.np_cod,
         donothing_np_cod: doNothingData.np_cod,
         cost_of_inaction: costOfInaction,
         projections: mergedProjections,
         delay_years: delayYears,
         final_pop: delayedData.projections[119].population_median
      });

    } catch (err: any) {
      setErrorMsg(err.message);
      useSimulationStore.getState().setResults(null);
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-col lg:flex-row h-full gap-6 w-full max-w-[1600px] mx-auto">
      {/* LEFT: Controls (30%) */}
      <motion.div 
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        className="w-full lg:w-[30%] glass-card rounded-3xl p-6 flex flex-col gap-6"
      >
        <h2 className="text-2xl font-semibold">Simulation Controls</h2>
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-400 mb-2">Scenario Strategy</label>
            <select 
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-white focus:ring-2 focus:ring-blue-500 outline-none"
            >
              <option value="act_now">Act Now (Immediate Intervention)</option>
              <option value="delay">Delay Intervention</option>
              <option value="do_nothing">Wait and See (Status Quo)</option>
            </select>
          </div>

          {scenario === 'delay' && (
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-2">Intervention Delay (Years): {delayYears}</label>
              <input 
                type="range" 
                min="1" max="10" 
                value={delayYears} 
                onChange={(e) => setDelayYears(Number(e.target.value))}
                className="w-full accent-blue-500" 
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-2">Invisible Population Estimate</label>
            <div className="flex gap-2">
              {['low', 'medium', 'high'].map((opt) => (
                <button
                  key={opt}
                  className="flex-1 capitalize py-2 rounded-lg text-sm font-medium border border-slate-700 hover:bg-slate-800 transition-colors"
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
        </div>

        <button 
          onClick={runSimulation}
          disabled={isRunning}
          className="mt-auto w-full py-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-xl font-medium transition-all shadow-lg flex items-center justify-center gap-2"
        >
          {isRunning ? "Running Monte Carlo..." : <><Play size={18} /> Execute Simulation</>}
        </button>
      </motion.div>

      {/* RIGHT: Results (70%) */}
      <motion.div 
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        className="w-full lg:w-[70%] glass-card rounded-3xl p-6 flex flex-col min-h-[500px]"
      >
        <h2 className="text-2xl font-semibold mb-6">Projections & Fiscal Impact</h2>

        {errorMsg && (
          <div className="bg-red-500/10 border border-red-500/50 rounded-xl p-4 mb-6 flex items-start gap-3 shadow-lg">
             <AlertCircle className="text-red-400 mt-0.5 shrink-0" size={20} />
             <div>
               <h3 className="text-red-400 font-semibold">Simulation Blocked</h3>
               <p className="text-red-300 text-sm mt-1">{errorMsg}</p>
             </div>
          </div>
        )}
        
        {!results && !isRunning && !errorMsg ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
            <Activity size={48} className="mb-4 opacity-50" />
            <p>Configure your scenario and run the simulation to see results.</p>
          </div>
        ) : results ? (
          <div className="flex-1 h-full flex flex-col gap-6">
            <div className="h-1/2 w-full min-h-[300px]">
               <h3 className="text-sm font-medium text-slate-400 mb-2">Cumulative Taxpayer Cost (Act Now vs Delayed vs Do Nothing)</h3>
               <ResponsiveContainer width="100%" height="100%">
                 <AreaChart data={results.projections}>
                   <XAxis dataKey="month" stroke="#64748b" tickFormatter={(val) => `M${val}`} />
                   <YAxis stroke="#64748b" tickFormatter={(val) => `$${val.toFixed(0)}M`} />
                   <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }} />
                   
                   <ReferenceLine x={results.delay_years * 12} stroke="#f59e0b" strokeDasharray="3 3" label={{ position: 'top', value: 'Intervention', fill: '#f59e0b', fontSize: 12 }} />
                   
                   {/* Baseline */}
                   <Area type="monotone" dataKey="baseline_cost_upper" stackId="1" stroke="none" fill="#10b981" fillOpacity={0.1} />
                   <Line type="monotone" dataKey="baseline_cost" stroke="#10b981" strokeWidth={2} strokeDasharray="5 5" name="Act Now" />
                   <Area type="monotone" dataKey="baseline_cost_lower" stackId="2" stroke="none" fill="transparent" />

                   {/* Delayed */}
                   <Area type="monotone" dataKey="delayed_cost_upper" stackId="3" stroke="none" fill="#f59e0b" fillOpacity={0.1} />
                   <Line type="monotone" dataKey="delayed_cost" stroke="#f59e0b" strokeWidth={3} name={`Delay ${results.delay_years} Years`} />
                   <Area type="monotone" dataKey="delayed_cost_lower" stackId="4" stroke="none" fill="transparent" />

                   {/* Do Nothing */}
                   <Area type="monotone" dataKey="donothing_cost_upper" stackId="5" stroke="none" fill="#ef4444" fillOpacity={0.1} />
                   <Line type="monotone" dataKey="donothing_cost" stroke="#ef4444" strokeWidth={2} strokeDasharray="3 3" name="Do Nothing" />
                   <Area type="monotone" dataKey="donothing_cost_lower" stackId="6" stroke="none" fill="transparent" />
                 </AreaChart>
               </ResponsiveContainer>
            </div>
            
            {results.cost_of_inaction >= 0 && (
              <p className="text-slate-300 text-center mb-2 mt-2 text-lg">
                 Waiting {results.delay_years} years to intervene will cost [City] an additional <span className="font-bold text-red-400">${(results.cost_of_inaction / 1000000).toFixed(1)} million</span> compared to acting today.
              </p>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-auto">
               <div className="p-4 bg-emerald-950/30 rounded-2xl border border-emerald-500/50">
                 <p className="text-sm text-emerald-400">Total Cost (Act Now)</p>
                 <p className="text-2xl font-bold text-emerald-300 mt-1">${(results.baseline_np_cod / 1000000).toFixed(1)}M</p>
               </div>
               <div className="p-4 bg-amber-950/30 rounded-2xl border border-amber-500/50">
                 <p className="text-sm text-amber-400">Total Cost (Delay {results.delay_years}y)</p>
                 <p className="text-2xl font-bold text-amber-300 mt-1">${(results.np_cod / 1000000).toFixed(1)}M</p>
               </div>
               <div className="p-4 bg-red-950/30 rounded-2xl border border-red-500/50">
                 <p className="text-sm text-red-400">Total Cost (Do Nothing)</p>
                 <p className="text-2xl font-bold text-red-300 mt-1">${(results.donothing_np_cod / 1000000).toFixed(1)}M</p>
               </div>
               <div className="p-4 bg-red-950/50 rounded-2xl border border-red-500 shadow-lg flex flex-col justify-center">
                 <p className="text-sm text-red-300 font-semibold">Cost of Inaction</p>
                 {results.cost_of_inaction < 0 ? (
                   <p className="text-sm font-bold text-red-500 mt-2 bg-red-950/50 p-2 rounded border border-red-500/30">
                     Model error: check intervention direction
                   </p>
                 ) : (
                   <p className="text-3xl font-bold text-red-400 mt-1">
                     +${(results.cost_of_inaction / 1000000).toFixed(1)}M
                   </p>
                 )}
               </div>
            </div>
          </div>
        ) : null}
      </motion.div>
    </div>
  );
}