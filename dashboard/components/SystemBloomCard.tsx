"use client";

import { useMemo } from "react";
import { Info, Leaf } from "lucide-react";
import { useAuxinStore } from "@/lib/store";

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function SystemBloomCard() {
  const telemetry = useAuxinStore((s) => s.telemetry);
  const payments = useAuxinStore((s) => s.payments);
  const complianceLogs = useAuxinStore((s) => s.complianceLogs);

  const { motionScore, payFlow, safetyBloom } = useMemo(() => {
    const avgTorque =
      telemetry && telemetry.joints.length > 0
        ? telemetry.joints.reduce((acc, joint) => acc + Math.abs(joint.torque), 0) / telemetry.joints.length
        : 0;
    const lastMinutePayments = payments.filter((p) => Date.now() - p.timestamp < 60_000).length;
    const critCount = complianceLogs.filter((log) => log.severity === 3).length;

    return {
      motionScore: clampPercent((avgTorque / 8) * 100),
      payFlow: clampPercent((lastMinutePayments / 8) * 100),
      safetyBloom: clampPercent(100 - critCount * 20),
    };
  }, [telemetry, payments, complianceLogs]);

  return (
    <section className="card-surface relative h-full overflow-visible px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Leaf className="h-4 w-4" style={{ color: "#14F195" }} />
          <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-gradient-purple-green">
            System Bloom
          </span>
        </div>
        <div className="group relative">
          <button
            type="button"
            className="rounded-full p-1 transition-colors hover:bg-white/[0.06]"
            style={{ color: "#C084FC" }}
            aria-label="Explain system bloom signals"
          >
            <Info className="h-3.5 w-3.5" />
          </button>
          <div
            className="absolute right-0 top-7 z-50 w-80 rounded-xl border px-3 py-2.5 text-[11px] leading-relaxed opacity-0 shadow-lg transition-all duration-150 group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:translate-y-0 group-focus-within:opacity-100"
            style={{
              borderColor: "rgba(168,85,247,0.34)",
              backgroundColor: "rgba(10,14,26,0.78)",
              backdropFilter: "blur(10px)",
              WebkitBackdropFilter: "blur(10px)",
              color: "#cbd5e1",
              transform: "translateY(4px)",
              boxShadow: "0 10px 30px rgba(0,0,0,0.45), 0 0 18px rgba(168,85,247,0.22)",
            }}
          >
            <span style={{ color: "#14b8a6" }}>Motion</span>: average joint torque load across active joints.
            <br />
            <span style={{ color: "#14F195" }}>Flow</span>: payment event activity observed in the last 60 seconds.
            <br />
            <span style={{ color: "#A855F7" }}>Safety</span>: inverse of current critical compliance count (higher is healthier).
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "motion", value: motionScore, color: "#14b8a6" },
          { label: "flow", value: payFlow, color: "#14F195" },
          { label: "safety", value: safetyBloom, color: "#A855F7" },
        ].map((metric) => (
          <div key={metric.label} className="rounded-xl border px-2 py-1.5" style={{ borderColor: `${metric.color}33` }}>
            <p className="mb-1 text-[9px] uppercase tracking-[0.16em]" style={{ color: "#64748b" }}>
              {metric.label}
            </p>
            <div className="h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: "rgba(51,65,85,0.5)" }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${metric.value}%`, backgroundColor: metric.color }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
