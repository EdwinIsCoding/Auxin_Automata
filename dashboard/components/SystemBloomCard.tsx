"use client";

import { useMemo } from "react";
import { Leaf, Sparkles } from "lucide-react";
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
    <section className="card-surface h-full overflow-hidden px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Leaf className="h-4 w-4" style={{ color: "#14F195" }} />
          <span className="text-[10px] font-bold tracking-[0.2em] uppercase text-gradient-purple-green">
            System Bloom
          </span>
        </div>
        <Sparkles className="h-3.5 w-3.5" style={{ color: "#C084FC" }} />
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
