"use client";

import { useEffect } from "react";
import { startMockDataFeed } from "@/lib/mockData";
import { useBridgeSocket } from "@/lib/useBridgeSocket";
import { useProgramEvents } from "@/lib/useProgramEvents";
import { Header } from "@/components/Header";
import { TelemetryCard } from "@/components/TelemetryCard";
import { PaymentTicker } from "@/components/PaymentTicker";
import { ComplianceTable } from "@/components/ComplianceTable";
import { TwinViewport } from "@/components/TwinViewport";
import { SystemBloomCard } from "@/components/SystemBloomCard";

const PETAL = "M 150,150 C 166,128 166,92 150,68 C 134,92 134,128 150,150";
const ANGLES = [0, 60, 120, 180, 240, 300];

/**
 * Full-viewport SVG that tiles a 2×2 checkerboard pattern:
 *   [flower | leaf]
 *   [leaf   | flower]
 * Uses mix-blend-mode:screen so dark areas vanish — only purple/green glows show.
 */
function BackgroundPattern() {
  return (
    <svg
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        zIndex: 1,
        opacity: 0.5,
        pointerEvents: "none",
        mixBlendMode: "screen",
      }}
    >
      <defs>
        {/* Soft glow filter */}
        <filter id="fg" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="1.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* ── Flower symbol ── */}
        <symbol id="fl" viewBox="0 0 300 300">
          {/* Concentric dashed rings */}
          <circle cx="150" cy="150" r="128" stroke="#A855F7" strokeOpacity="0.55" strokeWidth="3"   strokeDasharray="4 10" fill="none" />
          <circle cx="150" cy="150" r="84"  stroke="#A855F7" strokeOpacity="0.40" strokeWidth="2"   strokeDasharray="1 6"  fill="none" />
          <circle cx="150" cy="150" r="52"  stroke="#14F195" strokeOpacity="0.30" strokeWidth="1.5" strokeDasharray="1 5"  fill="none" />
          {/* 6 petals + circuit traces */}
          {ANGLES.map((a) => (
            <g key={a} transform={`rotate(${a},150,150)`} filter="url(#fg)">
              <path d={PETAL} fill="#A855F7" fillOpacity="0.10" stroke="#C084FC" strokeOpacity="0.88" strokeWidth="3.5" />
              <circle cx="150" cy="68" r="9" fill="#A855F7" />
              <line x1="150" y1="68" x2="150" y2="34" stroke="#14F195" strokeOpacity="0.90" strokeWidth="3.5" />
              <line x1="150" y1="34" x2="188" y2="34" stroke="#14F195" strokeOpacity="0.80" strokeWidth="3.5" />
              <circle cx="188" cy="34" r="7" fill="#14F195" />
            </g>
          ))}
          {/* Centre hex */}
          <polygon points="150,135 164,143 164,157 150,165 136,157 136,143"
            fill="#A855F7" fillOpacity="0.10" stroke="#C084FC" strokeOpacity="0.88" strokeWidth="3.5" />
          <circle cx="150" cy="150" r="26" fill="#A855F7" fillOpacity="0.18" />
          <circle cx="150" cy="150" r="8"  fill="#A855F7" />
          <circle cx="150" cy="150" r="4"  fill="#E9D5FF" />
        </symbol>

        {/* ── Leaf symbol (circuit-botanical) ── */}
        <symbol id="lf" viewBox="0 0 60 92">
          {/* Outer leaf shape */}
          <path d="M 30,82 C 4,66 1,30 30,4 C 59,30 56,66 30,82 Z"
            fill="#14F195" fillOpacity="0.08" stroke="#14F195" strokeOpacity="0.88" strokeWidth="1.8" />
          {/* Stem */}
          <line x1="30" y1="82" x2="30" y2="90" stroke="#14F195" strokeOpacity="0.55" strokeWidth="1.5" />
          {/* Central vein */}
          <line x1="30" y1="82" x2="30" y2="4" stroke="#14F195" strokeOpacity="0.60" strokeWidth="1.2" />
          {/* Tip node */}
          <circle cx="30" cy="4" r="3" fill="#39FF14" />
          {/* Left circuit-vein branches */}
          <polyline points="30,22 14,22 14,14" fill="none" stroke="#14F195" strokeOpacity="0.65" strokeWidth="1.1" />
          <circle cx="14" cy="14" r="2.2" fill="#14F195" />
          <polyline points="30,38 10,38 10,30" fill="none" stroke="#14F195" strokeOpacity="0.65" strokeWidth="1.1" />
          <circle cx="10" cy="30" r="2.2" fill="#14F195" />
          <polyline points="30,56 14,56 14,48" fill="none" stroke="#14F195" strokeOpacity="0.65" strokeWidth="1.1" />
          <circle cx="14" cy="48" r="2.2" fill="#14F195" />
          {/* Right circuit-vein branches */}
          <polyline points="30,28 46,28 46,20" fill="none" stroke="#14F195" strokeOpacity="0.65" strokeWidth="1.1" />
          <circle cx="46" cy="20" r="2.2" fill="#14F195" />
          <polyline points="30,46 50,46 50,38" fill="none" stroke="#14F195" strokeOpacity="0.65" strokeWidth="1.1" />
          <circle cx="50" cy="38" r="2.2" fill="#14F195" />
          <polyline points="30,63 46,63 46,55" fill="none" stroke="#14F195" strokeOpacity="0.65" strokeWidth="1.1" />
          <circle cx="46" cy="55" r="2.2" fill="#14F195" />
        </symbol>

        {/* ── 160×160 tile: 2×2 checkerboard (flower/leaf) ── */}
        <pattern id="mf" x="0" y="0" width="160" height="160" patternUnits="userSpaceOnUse">
          {/* Top-left: flower */}
          <use href="#fl" x="5"  y="5"  width="70" height="70" />
          {/* Top-right: leaf */}
          <use href="#lf" x="95" y="8"  width="44" height="67" />
          {/* Bottom-left: leaf */}
          <use href="#lf" x="11" y="88" width="44" height="67" />
          {/* Bottom-right: flower */}
          <use href="#fl" x="85" y="85" width="70" height="70" />
        </pattern>

        {/* ── Mecha-floral pattern ── */}
        <pattern id="mechaFloral" patternUnits="userSpaceOnUse" width="200" height="200">
          <circle cx="100" cy="100" r="80" fill="#14b8a6" />
          <rect x="50" y="50" width="100" height="100" fill="#A855F7" />
        </pattern>
      </defs>

      <rect width="100%" height="100%" fill="url(#mechaFloral)" />
    </svg>
  );
}

export default function DashboardPage() {
  // Mock feed runs immediately so the dashboard is never empty.
  // When the bridge connects (Phase 3), real data overrides mock telemetry
  // and real events are prepended to payments + compliance lists.
  useEffect(() => {
    const stop = startMockDataFeed();
    return stop;
  }, []);

  // Live bridge WebSocket — connects to ws://localhost:8766/ws, reconnects
  // automatically with exponential backoff. No-ops gracefully if bridge is offline.
  useBridgeSocket();

  // On-chain Anchor event subscription — no-op if NEXT_PUBLIC_PROGRAM_ID
  // or NEXT_PUBLIC_HELIUS_RPC_URL is unset (safe in pre-deploy / mock mode).
  useProgramEvents();

  return (
    <div className="relative min-h-screen overflow-hidden lg:h-screen" style={{ backgroundColor: "#070B14" }}>

      {/* ── Ambient bioluminescent blobs (z=0) ── */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden" style={{ zIndex: 0 }} aria-hidden>
        <div className="absolute -top-32 -left-32 w-[750px] h-[750px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(168,85,247,0.28) 0%, transparent 65%)", filter: "blur(80px)" }} />
        <div className="absolute top-1/4 -right-40 w-[600px] h-[600px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(20,241,149,0.16) 0%, transparent 65%)", filter: "blur(100px)" }} />
        <div className="absolute -bottom-40 left-1/4 w-[800px] h-[500px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(99,102,241,0.16) 0%, transparent 65%)", filter: "blur(120px)" }} />
        <div className="absolute -bottom-20 -right-20 w-[500px] h-[500px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(168,85,247,0.18) 0%, transparent 65%)", filter: "blur(70px)" }} />
      </div>

      {/* ── Mechafloral tiling pattern (z=1, screen blend) ── */}
      <BackgroundPattern />

      {/* ── App content (z=2, above pattern) ── */}
      <div className="relative flex min-h-screen flex-col overflow-hidden lg:h-full" style={{ zIndex: 2 }}>
        <Header />

        <main className="relative flex-1 overflow-y-auto p-4 lg:overflow-hidden lg:p-5">
          <div className="grid min-h-0 grid-cols-1 gap-5 lg:h-full lg:grid-cols-[320px_1fr_400px]">

            {/* Left — joint telemetry */}
            <div className="flex min-h-0 flex-col">
              <TelemetryCard />
            </div>

            {/* Centre — digital twin viewport */}
            <div className="flex h-full min-h-0 flex-col">
              <TwinViewport />
            </div>

            {/* Right — bloom + payments + compliance */}
            <div className="flex min-h-0 flex-col gap-5">
              <div className="h-[110px] shrink-0">
                <SystemBloomCard />
              </div>
              <div className="min-h-0 flex-1">
                <PaymentTicker />
              </div>
              <div className="min-h-0 flex-[1.35]">
                <ComplianceTable />
              </div>
            </div>

          </div>
        </main>
      </div>
    </div>
  );
}
