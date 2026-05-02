"use client";

/**
 * TreasuryPanel
 * -------------
 * AI Treasury Agent output display. Shows burn rate, runway, budget split,
 * and recommended actions from the bridge's treasury analysis.
 *
 * Visual structure:
 *   1. Header with "AI Treasury" + Sparkles icon
 *   2. Three metric cards: Burn Rate | Runway | Budget Split
 *   3. AI summary text
 *   4. Recommended Actions list with priority badges
 */

import { useAuxinStore } from "@/lib/store";
import type { RecommendedAction } from "@/lib/store";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { Sparkles, Zap, Clock, PieChart as PieIcon } from "lucide-react";
import { motion } from "framer-motion";

// ── Colour helpers ─────────────────────────────────────────────────────────────

const RUNWAY_COLOURS = {
  healthy:  "#14b8a6",
  warning:  "#f59e0b",
  critical: "#ef4444",
} as const;

const PRIORITY_CONFIG = {
  low:      { bg: "rgba(20,184,166,0.12)",  text: "#14b8a6",  label: "LOW" },
  medium:   { bg: "rgba(245,158,11,0.12)",  text: "#f59e0b",  label: "MED" },
  high:     { bg: "rgba(249,115,22,0.12)",  text: "#f97316",  label: "HIGH" },
  critical: { bg: "rgba(239,68,68,0.15)",   text: "#ef4444",  label: "CRIT" },
} as const;

const BUDGET_COLOURS = ["#14b8a6", "#a855f7", "#6b7280"];

// ── Formatters ─────────────────────────────────────────────────────────────────

function formatLamports(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function formatRunway(hours: number): string {
  if (hours > 9999) return "∞";
  if (hours >= 48) return `${Math.round(hours / 24)}d`;
  return `${hours.toFixed(1)}h`;
}

// ── Skeleton ───────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="animate-pulse p-4 space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-16 rounded-xl bg-white/5" />
        ))}
      </div>
      <div className="h-12 rounded-lg bg-white/5" />
      <div className="space-y-2">
        {[1, 2].map((i) => (
          <div key={i} className="h-10 rounded-lg bg-white/5" />
        ))}
      </div>
    </div>
  );
}

// ── Metric card ────────────────────────────────────────────────────────────────

function MetricCard({
  icon,
  label,
  value,
  sub,
  colour,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  colour: string;
}) {
  return (
    <div
      className="rounded-xl p-3 flex flex-col gap-1.5"
      style={{
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.07)",
      }}
    >
      <div className="flex items-center gap-1.5">
        <span style={{ color: colour }}>{icon}</span>
        <span className="text-[10px] tracking-widest uppercase" style={{ color: "#6b7280" }}>
          {label}
        </span>
      </div>
      <span className="text-lg font-bold tabular-nums" style={{ color: colour }}>
        {value}
      </span>
      {sub && <span className="text-[10px]" style={{ color: "#6b7280" }}>{sub}</span>}
    </div>
  );
}

// ── Budget donut ───────────────────────────────────────────────────────────────

function BudgetDonut({
  inference,
  reserve,
  buffer,
}: {
  inference: number;
  reserve: number;
  buffer: number;
}) {
  const data = [
    { name: "Inference", value: inference },
    { name: "Reserve",   value: reserve },
    { name: "Buffer",    value: buffer },
  ];

  return (
    <div
      className="rounded-xl p-3 flex items-center gap-3"
      style={{
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.07)",
      }}
    >
      <div className="flex items-center gap-1">
        <PieIcon className="h-3.5 w-3.5" style={{ color: "#6b7280" }} />
        <span className="text-[10px] tracking-widest uppercase" style={{ color: "#6b7280" }}>
          Budget
        </span>
      </div>
      <div className="w-12 h-12 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} innerRadius="55%" outerRadius="90%" dataKey="value" strokeWidth={0}>
              {data.map((_, i) => (
                <Cell key={i} fill={BUDGET_COLOURS[i]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "#111827",
                border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: 6,
                fontSize: 11,
              }}
              formatter={(v: number, name: string) => [`${v.toFixed(1)}%`, name]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex-1 space-y-0.5">
        {data.map((d, i) => (
          <div key={d.name} className="flex items-center gap-1.5">
            <div className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: BUDGET_COLOURS[i] }} />
            <span className="text-[10px]" style={{ color: "#9ca3af" }}>{d.name}</span>
            <span className="ml-auto text-[10px] tabular-nums font-semibold" style={{ color: BUDGET_COLOURS[i] }}>
              {d.value.toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Action item ────────────────────────────────────────────────────────────────

function ActionItem({ action }: { action: RecommendedAction }) {
  const cfg = PRIORITY_CONFIG[action.priority] ?? PRIORITY_CONFIG.medium;

  return (
    <motion.div
      className="rounded-lg p-2.5 flex items-start gap-2.5"
      style={{
        background: "rgba(255,255,255,0.02)",
        border: `1px solid rgba(255,255,255,0.06)`,
      }}
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
    >
      {/* Priority badge */}
      <span
        className="text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded shrink-0 mt-0.5"
        style={{ background: cfg.bg, color: cfg.text }}
      >
        {cfg.label}
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[12px] font-medium" style={{ color: "#e5e7eb" }}>
            {action.action.replace(/_/g, " ")}
          </span>
          {action.auto_executable && (
            <span
              className="text-[9px] font-bold tracking-widest uppercase px-1 py-0.5 rounded"
              style={{
                background: "rgba(168,85,247,0.12)",
                color: "#a855f7",
                border: "1px solid rgba(168,85,247,0.2)",
              }}
            >
              AUTO
            </span>
          )}
        </div>
        <p className="text-[11px] mt-0.5 leading-relaxed" style={{ color: "#6b7280" }}>
          {action.reasoning}
        </p>
      </div>
    </motion.div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function TreasuryPanel() {
  const analysis = useAuxinStore((s) => s.treasuryAnalysis);

  return (
    <div
      className="relative rounded-2xl overflow-hidden flex flex-col h-full"
      style={{
        background: "linear-gradient(160deg, rgba(17,24,39,0.95) 0%, rgba(7,11,20,0.98) 100%)",
        border: "1px solid rgba(168,85,247,0.15)",
        boxShadow: "0 0 40px -10px rgba(168,85,247,0.10)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
      >
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" style={{ color: "#a855f7" }} />
          <span className="text-xs font-semibold tracking-widest uppercase" style={{ color: "#9ca3af" }}>
            AI Treasury
          </span>
        </div>
        {analysis?.used_fallback && (
          <span className="text-[10px]" style={{ color: "#6b7280" }}>(heuristic)</span>
        )}
      </div>

      {/* Content */}
      {!analysis ? (
        <Skeleton />
      ) : (
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {/* ── Metric cards row ── */}
          <div className="grid grid-cols-2 gap-2">
            <MetricCard
              icon={<Zap className="h-3.5 w-3.5" />}
              label="Burn Rate"
              value={`${formatLamports(analysis.burn_rate_lamports_per_hour)}/hr`}
              sub="lamports per hour"
              colour="#f59e0b"
            />
            <MetricCard
              icon={<Clock className="h-3.5 w-3.5" />}
              label="Runway"
              value={formatRunway(analysis.runway_hours)}
              sub={analysis.runway_status}
              colour={RUNWAY_COLOURS[analysis.runway_status]}
            />
          </div>

          {/* Budget donut */}
          <BudgetDonut
            inference={analysis.budget_allocation.inference}
            reserve={analysis.budget_allocation.reserve}
            buffer={analysis.budget_allocation.buffer}
          />

          {/* AI summary */}
          {analysis.summary && (
            <div
              className="rounded-xl p-3"
              style={{
                background: "rgba(168,85,247,0.06)",
                border: "1px solid rgba(168,85,247,0.12)",
              }}
            >
              <p className="text-[12px] leading-relaxed" style={{ color: "#c4b5fd" }}>
                {analysis.summary}
              </p>
            </div>
          )}

          {/* Recommended actions */}
          {analysis.recommended_actions.length > 0 && (
            <div className="space-y-1.5">
              <span
                className="text-[10px] tracking-widest uppercase font-medium"
                style={{ color: "#6b7280" }}
              >
                Recommended Actions
              </span>
              {analysis.recommended_actions.map((action, i) => (
                <ActionItem key={`${action.action}-${i}`} action={action} />
              ))}
            </div>
          )}

          {/* Anomaly flags */}
          {analysis.anomaly_flags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {analysis.anomaly_flags.map((flag) => (
                <span
                  key={flag}
                  className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                  style={{
                    background: "rgba(239,68,68,0.12)",
                    color: "#ef4444",
                    border: "1px solid rgba(239,68,68,0.2)",
                  }}
                >
                  ⚠ {flag.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
