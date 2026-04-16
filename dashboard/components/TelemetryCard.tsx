"use client";

import { useAuxinStore } from "@/lib/store";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { AlertTriangle, Loader2, Zap } from "lucide-react";

// Alternating purple / teal sparkline colors per joint index
const JOINT_COLORS = ["#A855F7", "#14b8a6", "#A855F7", "#14b8a6", "#A855F7", "#14b8a6", "#A855F7"];

function JointRow({
  name,
  angle,
  torque,
  history,
  isAnomaly,
  index,
}: {
  name: string;
  angle: number;
  torque: number;
  history: { t: number; angle: number; torque: number }[];
  isAnomaly: boolean;
  index: number;
}) {
  const accentColor = isAnomaly ? "#ef4444" : JOINT_COLORS[index % JOINT_COLORS.length];
  const isPurple = !isAnomaly && index % 2 === 0;

  return (
    <div
      className="flex items-center gap-3 rounded-2xl px-3 py-2 transition-all duration-300"
      style={{
        backgroundColor: isAnomaly
          ? "rgba(239,68,68,0.07)"
          : isPurple
          ? "rgba(168,85,247,0.05)"
          : "rgba(20,184,166,0.04)",
        borderLeft: `2px solid ${accentColor}${isAnomaly ? "cc" : "60"}`,
        boxShadow: isAnomaly
          ? "0 0 14px -4px rgba(239,68,68,0.35)"
          : isPurple
          ? "inset 0 0 20px -10px rgba(168,85,247,0.15)"
          : "none",
      }}
    >
      {/* Joint label */}
      <span
        className="w-6 text-xs font-mono font-bold shrink-0 tracking-widest"
        style={{ color: accentColor }}
      >
        {name}
      </span>

      {/* Angle */}
      <div className="w-20 shrink-0">
        <p className="text-[10px] leading-none tracking-wider uppercase" style={{ color: "#3d4663" }}>
          angle
        </p>
        <p className="text-xs font-mono tabular-nums" style={{ color: "#e2e8f0" }}>
          {angle >= 0 ? "+" : ""}
          {angle.toFixed(1)}°
        </p>
      </div>

      {/* Torque */}
      <div className="w-20 shrink-0">
        <p className="text-[10px] leading-none tracking-wider uppercase" style={{ color: "#3d4663" }}>
          torque
        </p>
        <p className="text-xs font-mono tabular-nums" style={{ color: "#e2e8f0" }}>
          {torque >= 0 ? "+" : ""}
          {torque.toFixed(1)} Nm
        </p>
      </div>

      {/* Sparkline */}
      <div className="flex-1 h-8">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <ReferenceLine y={0} stroke="rgba(30,40,70,0.8)" strokeDasharray="2 2" />
            <Line
              type="monotone"
              dataKey="angle"
              stroke={accentColor}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "rgba(10,14,28,0.92)",
                border: `1px solid ${accentColor}40`,
                borderRadius: 12,
                fontSize: 10,
                color: "#f1f5f9",
              }}
              itemStyle={{ color: accentColor }}
              labelStyle={{ display: "none" }}
              formatter={(v: number) => [`${v.toFixed(1)}°`, "angle"]}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function TelemetryCard() {
  const telemetry = useAuxinStore((s) => s.telemetry);
  const isLoading = useAuxinStore((s) => s.isLoading);
  const error = useAuxinStore((s) => s.error);

  if (error) {
    return (
      <div className="card-surface glow-red-card flex flex-col items-center justify-center gap-3 p-8 h-full">
        <AlertTriangle className="h-8 w-8 animate-pulse" style={{ color: "#ef4444" }} />
        <p className="text-sm tracking-wider" style={{ color: "#94a3b8" }}>
          Telemetry stream error
        </p>
        <p className="text-xs font-mono" style={{ color: "#ef4444" }}>
          {error}
        </p>
      </div>
    );
  }

  if (isLoading || !telemetry) {
    return (
      <div className="card-surface flex flex-col items-center justify-center gap-3 p-8 h-full">
        <Loader2 className="h-6 w-6 animate-spin" style={{ color: "#A855F7" }} />
        <p className="text-sm tracking-wider" style={{ color: "#64748b" }}>
          Connecting to telemetry source…
        </p>
      </div>
    );
  }

  const tsStr = new Date(telemetry.timestamp).toISOString().slice(11, 23);

  return (
    <div
      className={`card-surface flex flex-col h-full overflow-hidden transition-all duration-500 ${
        telemetry.hasAnomaly ? "glow-red-card" : ""
      }`}
    >
      {/* Card header */}
      <div className="card-header-purple flex items-center justify-between px-4 py-3 shrink-0">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4" style={{ color: "#A855F7" }} />
          <span className="text-xs font-bold tracking-[0.22em] uppercase" style={{ color: "#C084FC" }}>
            Joint Telemetry
          </span>
        </div>
        <div className="flex items-center gap-2">
          {telemetry.hasAnomaly && (
            <span
              className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full tracking-widest uppercase"
              style={{
                backgroundColor: "rgba(239,68,68,0.12)",
                color: "#ef4444",
                border: "1px solid rgba(239,68,68,0.35)",
              }}
            >
              <AlertTriangle className="h-3 w-3" />
              {telemetry.anomalyJoint}
            </span>
          )}
          <span className="text-[10px] font-mono tabular-nums" style={{ color: "#3d4663" }}>
            {tsStr}
          </span>
        </div>
      </div>

      {/* Joints */}
      <div className="scroll-tech flex flex-1 flex-col gap-1.5 overflow-y-auto p-3">
        {telemetry.joints.map((joint, i) => (
          <JointRow
            key={joint.name}
            {...joint}
            index={i}
            isAnomaly={telemetry.hasAnomaly && telemetry.anomalyJoint === joint.name}
          />
        ))}
      </div>
    </div>
  );
}
