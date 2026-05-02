"use client";

/**
 * RiskGauge
 * ---------
 * Real-time Machine Health Score (0–100) displayed as a radial gauge.
 * Subscribes to the Zustand store for RiskReport updates broadcast from the bridge.
 *
 * Visual structure:
 *   1. Radial gauge arc (Recharts RadialBarChart) with grade inside
 *   2. Four dimension progress bars (Financial Health, Operational Stability, etc.)
 *   3. 7-day trend sparkline (tiny LineChart)
 *   4. Trend label (improving / stable / declining)
 */

import { useAuxinStore } from "@/lib/store";
import type { RiskBreakdown } from "@/lib/store";
import {
  RadialBarChart,
  RadialBar,
  LineChart,
  Line,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// ── Colour helpers ─────────────────────────────────────────────────────────────

function scoreColour(score: number): string {
  if (score >= 80) return "#14b8a6"; // teal  → A
  if (score >= 60) return "#22d3ee"; // cyan  → B
  if (score >= 40) return "#f59e0b"; // amber → C
  return "#ef4444";                  // red   → D/F
}

function gradeColour(grade: string): string {
  if (grade === "A") return "#14b8a6";
  if (grade === "B") return "#22d3ee";
  if (grade === "C") return "#f59e0b";
  return "#ef4444";
}

const TREND_ICONS = {
  improving: <TrendingUp className="h-3.5 w-3.5" style={{ color: "#14b8a6" }} />,
  stable:    <Minus      className="h-3.5 w-3.5" style={{ color: "#9ca3af" }} />,
  declining: <TrendingDown className="h-3.5 w-3.5" style={{ color: "#ef4444" }} />,
} as const;

const TREND_COLOURS = {
  improving: "#14b8a6",
  stable:    "#9ca3af",
  declining: "#ef4444",
} as const;

// ── Skeleton ───────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="flex flex-col items-center gap-4 animate-pulse p-4">
      <div className="w-40 h-40 rounded-full bg-white/5" />
      <div className="w-full space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-4 rounded bg-white/5" style={{ width: `${70 + i * 5}%` }} />
        ))}
      </div>
      <div className="w-full h-10 rounded bg-white/5" />
    </div>
  );
}

// ── Dimension progress bar ─────────────────────────────────────────────────────

function DimensionBar({ bd }: { bd: RiskBreakdown }) {
  const pct = bd.score;
  const colour = scoreColour(bd.score);

  return (
    <div className="space-y-0.5">
      <div className="flex justify-between items-center">
        <span className="text-[11px] font-medium" style={{ color: "#9ca3af" }}>
          {bd.category}
        </span>
        <div className="flex items-center gap-1">
          <span className="text-[10px]" style={{ color: "#6b7280" }}>
            {(bd.weight * 100).toFixed(0)}%
          </span>
          <span className="text-[12px] font-semibold tabular-nums" style={{ color: colour }}>
            {bd.score.toFixed(0)}
          </span>
        </div>
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden"
        style={{ backgroundColor: "rgba(255,255,255,0.06)" }}
      >
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: colour }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function RiskGauge() {
  const riskReport = useAuxinStore((s) => s.riskReport);

  if (!riskReport) return <GaugeShell><Skeleton /></GaugeShell>;

  const { overall_score, grade, breakdown, trend, trend_data } = riskReport;
  const colour = scoreColour(overall_score);
  const trendColour = TREND_COLOURS[trend] ?? "#9ca3af";

  // Recharts RadialBarChart needs data in [{ value }] format, 0-100
  const gaugeData = [{ value: overall_score, fill: colour }];

  return (
    <GaugeShell>
      {/* ── Radial gauge ── */}
      <div className="relative flex items-center justify-center h-44">
        <ResponsiveContainer width="100%" height={176}>
          <RadialBarChart
            cx="50%"
            cy="70%"
            innerRadius="70%"
            outerRadius="95%"
            barSize={12}
            data={gaugeData}
            startAngle={200}
            endAngle={-20}
          >
            {/* Track (background arc) — separate RadialBar at 100 for correct rendering */}
            <RadialBar
              dataKey="value"
              data={[{ value: 100, fill: "rgba(255,255,255,0.06)" }]}
              cornerRadius={6}
              isAnimationActive={false}
            />
            {/* Score arc */}
            <RadialBar
              dataKey="value"
              cornerRadius={6}
              isAnimationActive
              animationDuration={800}
              animationEasing="ease-out"
            />
          </RadialBarChart>
        </ResponsiveContainer>

        {/* ── Grade / score overlay ── */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pb-4">
          <AnimatePresence mode="wait">
            <motion.span
              key={grade}
              className="text-5xl font-black tabular-nums leading-none"
              style={{ color: gradeColour(grade) }}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.35 }}
            >
              {grade}
            </motion.span>
          </AnimatePresence>
          <AnimatePresence mode="wait">
            <motion.span
              key={overall_score}
              className="text-lg font-bold tabular-nums"
              style={{ color: colour }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            >
              {overall_score.toFixed(0)}
            </motion.span>
          </AnimatePresence>
          <span className="text-[10px] tracking-widest uppercase mt-0.5" style={{ color: "#6b7280" }}>
            Health Score
          </span>
        </div>
      </div>

      {/* ── Dimension bars ── */}
      <div className="px-4 space-y-2.5 pb-3">
        {breakdown.map((bd) => (
          <DimensionBar key={bd.category} bd={bd} />
        ))}
      </div>

      {/* ── Trend sparkline ── */}
      {trend_data.length > 0 && (
        <div className="px-4 pb-4">
          <div
            className="rounded-lg p-2"
            style={{ backgroundColor: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] tracking-widest uppercase" style={{ color: "#6b7280" }}>
                7-Day Trend
              </span>
              <div className="flex items-center gap-1">
                {TREND_ICONS[trend]}
                <span className="text-[10px] font-semibold capitalize" style={{ color: trendColour }}>
                  {trend}
                </span>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={36}>
              <LineChart data={trend_data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke={trendColour}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "#111827",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                  labelFormatter={(l) => l}
                  formatter={(v: number) => [v.toFixed(1), "Score"]}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </GaugeShell>
  );
}

function GaugeShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="relative rounded-2xl overflow-hidden flex flex-col h-full"
      style={{
        background: "linear-gradient(160deg, rgba(17,24,39,0.95) 0%, rgba(7,11,20,0.98) 100%)",
        border: "1px solid rgba(20,184,166,0.15)",
        boxShadow: "0 0 40px -10px rgba(20,184,166,0.12)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-4 py-3 shrink-0"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
      >
        <div
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: "#14b8a6", boxShadow: "0 0 6px rgba(20,184,166,0.6)" }}
        />
        <span className="text-xs font-semibold tracking-widest uppercase" style={{ color: "#9ca3af" }}>
          Machine Health
        </span>
      </div>
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  );
}
