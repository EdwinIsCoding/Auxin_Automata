"use client";

/**
 * RiskGauge
 * ---------
 * Real-time Machine Health Score (0–100) displayed as a radial gauge.
 *
 * The gauge arc is pure SVG — no Recharts RadialBarChart — so the grade
 * letter, score number, and arc are all in the same coordinate space and
 * can never collide.  Framer Motion animates pathLength (0→score/100) on
 * the score arc so it always sits exactly on the track.
 */

import { useAuxinStore } from "@/lib/store";
import type { RiskBreakdown } from "@/lib/store";
import { LineChart, Line, ResponsiveContainer, Tooltip } from "recharts";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { motion } from "framer-motion";

// ── Colour helpers ─────────────────────────────────────────────────────────────

function scoreColour(score: number): string {
  if (score >= 80) return "#14b8a6";
  if (score >= 60) return "#22d3ee";
  if (score >= 40) return "#f59e0b";
  return "#ef4444";
}

function gradeColour(grade: string): string {
  if (grade === "A") return "#14b8a6";
  if (grade === "B") return "#22d3ee";
  if (grade === "C") return "#f59e0b";
  return "#ef4444";
}

const TREND_ICONS = {
  improving: <TrendingUp  className="h-3.5 w-3.5" style={{ color: "#14b8a6" }} />,
  stable:    <Minus       className="h-3.5 w-3.5" style={{ color: "#9ca3af" }} />,
  declining: <TrendingDown className="h-3.5 w-3.5" style={{ color: "#ef4444" }} />,
} as const;

const TREND_COLOURS = {
  improving: "#14b8a6",
  stable:    "#9ca3af",
  declining: "#ef4444",
} as const;

// ── SVG gauge geometry ─────────────────────────────────────────────────────────
//
// Arc centre:  (CX, CY)
// Stroke radius R, stroke width SW.
// Score=0 end: math angle START_DEG (bottom-left, ~7 o'clock).
// Score=100 end: math angle END_DEG  (bottom-right, ~5 o'clock).
// The arc goes clockwise in screen coords (sweep-flag=1) through the top.
// Total span: START_DEG − END_DEG = 220°.

const CX = 100, CY = 112, R = 76, SW = 14;
const START_DEG = 200, END_DEG = -20;

function pt(deg: number, r = R): [number, number] {
  const rad = (deg * Math.PI) / 180;
  return [
    parseFloat((CX + r * Math.cos(rad)).toFixed(3)),
    parseFloat((CY - r * Math.sin(rad)).toFixed(3)),  // y flipped in SVG
  ];
}

const [sx, sy] = pt(START_DEG);   // start of arc (score = 0, bottom-left)
const [ex, ey] = pt(END_DEG);     // end of arc   (score = 100, bottom-right)

// large-arc-flag=1  → 220° arc (> 180°)
// sweep-flag=1      → clockwise in SVG screen coords → passes through the top
const ARC_D = `M ${sx} ${sy} A ${R} ${R} 0 1 1 ${ex} ${ey}`;

// ── Gauge SVG ──────────────────────────────────────────────────────────────────

function ScoreGauge({ score, grade }: { score: number; grade: string }) {
  const arcColour  = scoreColour(score);
  const textColour = gradeColour(grade);

  return (
    // viewBox shows y 28–152 (the arc top is ~32, endpoints at ~141, text at ~145)
    <svg viewBox="0 28 200 124" className="w-full" aria-label={`Health score ${Math.round(score)}, grade ${grade}`}>
      {/* Background track */}
      <path
        d={ARC_D}
        fill="none"
        stroke="rgba(255,255,255,0.07)"
        strokeWidth={SW}
        strokeLinecap="round"
      />

      {/* Score arc — animates from 0 to score/100 of the path length */}
      <motion.path
        d={ARC_D}
        fill="none"
        stroke={arcColour}
        strokeWidth={SW}
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: score / 100 }}
        transition={{ duration: 1.0, ease: "easeOut" }}
        style={{ filter: `drop-shadow(0 0 6px ${arcColour}88)` }}
      />

      {/* Grade letter */}
      <text
        x={CX}
        y={CY - 6}
        textAnchor="middle"
        dominantBaseline="auto"
        fill={textColour}
        fontSize={42}
        fontWeight={900}
        style={{ fontFamily: "inherit" }}
      >
        {grade}
      </text>

      {/* Numeric score */}
      <text
        x={CX}
        y={CY + 16}
        textAnchor="middle"
        dominantBaseline="auto"
        fill={arcColour}
        fontSize={15}
        fontWeight={700}
        style={{ fontFamily: "inherit" }}
      >
        {Math.round(score)}
      </text>

      {/* Label */}
      <text
        x={CX}
        y={CY + 30}
        textAnchor="middle"
        dominantBaseline="auto"
        fill="#4b5563"
        fontSize={8}
        letterSpacing={2}
        style={{ fontFamily: "inherit" }}
      >
        HEALTH SCORE
      </text>

      {/* Min / max tick labels */}
      <text x={sx - 4} y={sy + 12} textAnchor="middle" fill="#374151" fontSize={8}>0</text>
      <text x={ex + 4} y={ey + 12} textAnchor="middle" fill="#374151" fontSize={8}>100</text>
    </svg>
  );
}

// ── Skeleton ───────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="flex flex-col items-center gap-4 animate-pulse p-4">
      <div className="w-40 h-36 rounded-full bg-white/5" />
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
          animate={{ width: `${bd.score}%` }}
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
  const trendColour = TREND_COLOURS[trend] ?? "#9ca3af";

  return (
    <GaugeShell>
      {/* ── Radial gauge ── */}
      <div className="px-6 pt-3 pb-1">
        <ScoreGauge score={overall_score} grade={grade} />
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
            style={{
              backgroundColor: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.06)",
            }}
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

// ── Shell ──────────────────────────────────────────────────────────────────────

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
