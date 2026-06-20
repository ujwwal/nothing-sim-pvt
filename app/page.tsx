"use client";
import React from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { ArrowRight, Activity, BarChart2, Database, GitBranch, Shield, TrendingDown } from 'lucide-react';

/* ── Animation variants ─────────────────────────────────────────────────── */
const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 24 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.65, delay, ease: [0.22, 1, 0.36, 1] },
});

const fadeIn = (delay = 0) => ({
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  transition: { duration: 0.5, delay },
});

/* ── Feature card data ──────────────────────────────────────────────────── */
const FEATURES = [
  {
    icon: GitBranch,
    color: '#4f8fff',
    title: 'Markov Simulation',
    desc: '6-state discrete-time model with 1,000 Monte Carlo runs — never a single-point forecast.',
  },
  {
    icon: BarChart2,
    color: '#a855f7',
    title: 'Cost of Inaction',
    desc: 'Quantifies the net present cost of delaying PSH interventions across shelter, healthcare, and justice.',
  },
  {
    icon: Database,
    color: '#22d3ee',
    title: 'Data Health',
    desc: 'Auto-discovers 11 registered datasets. Monitors drift, staleness, and missingness in real time.',
  },
  {
    icon: Shield,
    color: '#34d399',
    title: 'Responsible AI',
    desc: 'Human-in-the-loop by design. Hard bypasses for stale data. No automated policy decisions.',
  },
  {
    icon: TrendingDown,
    color: '#f59e0b',
    title: 'Range Estimates',
    desc: 'All outputs shown as probability ranges — never exact. Invisible population multipliers surfaced.',
  },
  {
    icon: Activity,
    color: '#f472b6',
    title: 'Decision Briefs',
    desc: 'AI-generated plain-language summaries help non-technical policymakers understand the model output.',
  },
];

/* ── Stat ticker ────────────────────────────────────────────────────────── */
const STATS = [
  { label: 'Datasets Registered', value: '11' },
  { label: 'Monte Carlo Runs', value: '1,000' },
  { label: 'Simulation Horizon', value: '10 yrs' },
  { label: 'Markov States', value: '6' },
];

export default function LandingPage() {
  return (
    <div className="max-w-6xl mx-auto pb-16 space-y-20">

      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <section className="pt-8 flex flex-col items-center text-center">
        {/* Headline */}
        <motion.h1
          {...fadeUp(0.15)}
          className="text-6xl md:text-8xl font-semibold tracking-tight leading-none mb-6"
        >
          <span className="gradient-text">The Cost of</span>
          <br />
          <span className="text-white/90">Doing Nothing</span>
        </motion.h1>

        {/* Sub-headline */}
        <motion.p
          {...fadeUp(0.25)}
          className="text-lg md:text-xl text-slate-400 font-light max-w-2xl leading-relaxed mb-12"
        >
          QuietCost helps municipal decision-makers understand the long-term fiscal consequences
          of delaying supportive housing interventions for people experiencing chronic homelessness.
        </motion.p>

        {/* CTA row */}
        <motion.div {...fadeUp(0.35)} className="flex flex-col sm:flex-row gap-3">
          <Link
            href="/simulation"
            className="btn-primary px-7 py-3.5 rounded-2xl flex items-center gap-2 text-sm"
          >
            Run Simulation <ArrowRight size={16} />
          </Link>
          <Link
            href="/dashboard"
            className="btn-glass px-7 py-3.5 rounded-2xl flex items-center gap-2 text-sm"
          >
            View Dashboard <BarChart2 size={16} />
          </Link>
          <Link
            href="/data-health"
            className="btn-glass px-7 py-3.5 rounded-2xl flex items-center gap-2 text-sm"
          >
            Explore Data <Database size={16} />
          </Link>
        </motion.div>

        {/* Stats strip */}
        <motion.div
          {...fadeUp(0.45)}
          className="mt-14 grid grid-cols-2 sm:grid-cols-4 gap-px rounded-2xl overflow-hidden"
          style={{ background: 'rgba(255,255,255,0.05)' }}
        >
          {STATS.map((s, i) => (
            <div
              key={i}
              className="px-8 py-5 text-center"
              style={{ background: 'rgba(10,10,22,0.6)', backdropFilter: 'blur(12px)' }}
            >
              <p className="text-2xl font-semibold gradient-text">{s.value}</p>
              <p className="text-xs text-slate-500 mt-1">{s.label}</p>
            </div>
          ))}
        </motion.div>
      </section>

      {/* ── Hero visual — prismatic glass panel ─────────────────────────── */}
      <motion.div {...fadeUp(0.5)} className="relative">
        <div
          className="glass glass-prismatic rounded-3xl overflow-hidden"
          style={{ padding: '2px' }}
        >
          <div
            className="rounded-3xl p-8"
            style={{ background: 'linear-gradient(135deg, rgba(10,10,22,0.8), rgba(5,5,18,0.9))' }}
          >
            <div className="grid grid-cols-3 gap-4 mb-6">
              {[
                { label: 'Net Present Cost of Delay', value: '$12.4M – $18.7M', color: '#ef4444', sub: '80% CI · 3-yr delay scenario' },
                { label: 'Population at Year 10',     value: '1,420 – 2,140',  color: '#f59e0b', sub: 'Chronic homeless, mid estimate' },
                { label: 'Intervention Savings',      value: '$6.1M – $9.3M',  color: '#34d399', sub: 'vs. Do Nothing scenario' },
              ].map((kpi, i) => (
                <div
                  key={i}
                  className="rounded-2xl p-4"
                  style={{ background: `${kpi.color}10`, border: `1px solid ${kpi.color}25` }}
                >
                  <p className="text-[11px] text-slate-400 mb-2">{kpi.label}</p>
                  <p className="text-xl font-bold" style={{ color: kpi.color }}>{kpi.value}</p>
                  <p className="text-[9px] text-slate-600 mt-1">{kpi.sub}</p>
                </div>
              ))}
            </div>

            {/* Mini chart bars */}
            <div className="space-y-2">
              <p className="text-[10px] text-slate-600 uppercase tracking-wider font-semibold mb-3">Projected Annual System Cost — 10yr</p>
              {[
                { year: '2025', low: 42, mid: 52, high: 64 },
                { year: '2026', low: 46, mid: 58, high: 72 },
                { year: '2027', low: 51, mid: 65, high: 80 },
                { year: '2028', low: 56, mid: 72, high: 89 },
                { year: '2029', low: 60, mid: 78, high: 97 },
                { year: '2030', low: 63, mid: 83, high: 103 },
              ].map((row, i) => (
                <div key={i} className="flex items-center gap-3 text-[10px]">
                  <span className="text-slate-600 w-8">{row.year}</span>
                  <div className="flex-1 h-4 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)' }}>
                    <motion.div
                      className="h-full rounded-full relative"
                      style={{ background: 'rgba(79,143,255,0.12)', width: `${row.high}%` }}
                      initial={{ width: 0 }}
                      animate={{ width: `${row.high}%` }}
                      transition={{ duration: 0.8, delay: 0.6 + i * 0.07, ease: [0.22,1,0.36,1] }}
                    >
                      <motion.div
                        className="absolute top-0 left-0 h-full rounded-full"
                        style={{ background: 'linear-gradient(90deg, #4f8fff, #a855f7)', width: `${(row.mid/row.high)*100}%` }}
                        initial={{ width: 0 }}
                        animate={{ width: `${(row.mid/row.high)*100}%` }}
                        transition={{ duration: 0.6, delay: 0.7 + i * 0.07 }}
                      />
                    </motion.div>
                  </div>
                  <span className="text-slate-500 w-12 text-right">${row.mid}M</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Floating label */}
        <div
          className="absolute -top-3 left-8 badge badge-violet"
        >
          Sample Output · 3-Year Delay Scenario
        </div>
      </motion.div>

      {/* ── Features grid ───────────────────────────────────────────────── */}
      <section>
        <motion.div {...fadeUp(0.1)} className="text-center mb-10">
          <h2 className="text-3xl font-semibold text-white/90 mb-3">How QuietCost Works</h2>
          <p className="text-slate-400 max-w-xl mx-auto text-sm">
            A transparent, auditable simulation stack built on peer-reviewed methods — not a black box.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f, i) => {
            const Icon = f.icon;
            return (
              <motion.div
                key={i}
                {...fadeUp(0.1 + i * 0.06)}
                whileHover={{ y: -4, transition: { duration: 0.2 } }}
                className="glass-interactive rounded-2xl p-5 cursor-default"
              >
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center mb-4"
                  style={{
                    background: `${f.color}18`,
                    border: `1px solid ${f.color}30`,
                    boxShadow: `0 0 16px ${f.color}15`,
                  }}
                >
                  <Icon size={18} style={{ color: f.color }} />
                </div>
                <h3 className="text-base font-semibold text-white mb-1.5">{f.title}</h3>
                <p className="text-sm text-slate-500 leading-relaxed">{f.desc}</p>
              </motion.div>
            );
          })}
        </div>
      </section>

      {/* ── Responsible AI strip ─────────────────────────────────────────── */}
      <motion.section {...fadeUp(0.1)}>
        <div
          className="rounded-2xl p-6"
          style={{
            background: 'linear-gradient(135deg, rgba(52,211,153,0.06), rgba(34,211,238,0.04))',
            border: '1px solid rgba(52,211,153,0.15)',
          }}
        >
          <div className="flex flex-col md:flex-row items-start md:items-center gap-5">
            <div
              className="w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(52,211,153,0.15)', border: '1px solid rgba(52,211,153,0.3)' }}
            >
              <Shield size={22} style={{ color: '#34d399' }} />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-white mb-1">Responsible AI by Design</h3>
              <p className="text-sm text-slate-400 leading-relaxed">
                QuietCost does <strong className="text-slate-200">not</strong> make policy decisions or determine individual eligibility.
                All projections include uncertainty ranges. The simulator disables itself when data is older than 18 months,
                missingness exceeds 25%, or population falls below 100. Humans remain responsible for all final decisions.
              </p>
            </div>
            <Link href="/methodology" className="btn-glass px-5 py-2.5 rounded-xl text-sm whitespace-nowrap flex-shrink-0">
              Read Methodology →
            </Link>
          </div>
        </div>
      </motion.section>

    </div>
  );
}