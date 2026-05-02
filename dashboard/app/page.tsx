"use client";

import { useEffect, useState } from "react";
import { startMockDataFeed } from "@/lib/mockData";
import { useBridgeSocket } from "@/lib/useBridgeSocket";
import { useProgramEvents } from "@/lib/useProgramEvents";
import { Header } from "@/components/Header";
import { TelemetryCard } from "@/components/TelemetryCard";
import { PaymentTicker } from "@/components/PaymentTicker";
import { ComplianceTable } from "@/components/ComplianceTable";
import { TwinViewport } from "@/components/TwinViewport";
import { SystemBloomCard } from "@/components/SystemBloomCard";
import { RiskGauge } from "@/components/RiskGauge";
import { TreasuryPanel } from "@/components/TreasuryPanel";
import { InvoiceDownloader } from "@/components/InvoiceDownloader";

/**
 * "Auxin Circuit Bloom" — a tiling 6-armed mechanical snowflake.
 *
 * Identity encoded in geometry:
 *   • 3 purple arms (0°/120°/240°) → Solana-diamond tips   (blockchain nodes)
 *   • 3 teal arms   (60°/180°/300°) → botanical leaf-buds  (auxin growth tips)
 *   • PCB via-dots at arm midpoints                         (robotic joints)
 *   • Hexagonal hub at centre                               (chain / agent node)
 *   • Concentric dashed rings                               (signal propagation)
 *
 * mix-blend-mode:screen keeps it invisible over pure black, visible only
 * where the background has any luminance — giving "discrete but distinct."
 */
function BackgroundPattern() {
  const purpleAngles = [0, 120, 240];
  const tealAngles   = [60, 180, 300];

  return (
    <svg
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        zIndex: 1,
        opacity: 0.58,
        pointerEvents: "none",
        mixBlendMode: "screen",
      }}
    >
      <defs>
        {/* Subtle glow — diffuses the hard edges of each trace */}
        <filter id="bloom-glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="0.9" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/*
          220×220 tile — centred at (110,110).
          Arm geometry (all in local space before rotate):
            start  : r = 18  (just outside hub ring)
            mid via: r = 46
            tip    : r = 76
        */}
        <pattern id="auxinCircuit" patternUnits="userSpaceOnUse" width="220" height="220">

          {/* ── Signal-propagation rings ── */}
          <circle cx="110" cy="110" r="95"
            stroke="#A855F7" strokeOpacity="0.07" strokeWidth="0.9"
            strokeDasharray="3 11" fill="none" />
          <circle cx="110" cy="110" r="62"
            stroke="#14b8a6" strokeOpacity="0.07" strokeWidth="0.9"
            strokeDasharray="2 8" fill="none" />
          <circle cx="110" cy="110" r="32"
            stroke="#C084FC" strokeOpacity="0.10" strokeWidth="0.8"
            fill="none" />

          {/* ── Purple arms → Solana-diamond tips ── */}
          {purpleAngles.map((angle) => (
            <g key={`p${angle}`}
               transform={`translate(110,110) rotate(${angle})`}
               filter="url(#bloom-glow)">
              {/* PCB trace */}
              <line x1="18" y1="0" x2="76" y2="0"
                stroke="#A855F7" strokeOpacity="0.46" strokeWidth="1.3" />
              {/* Mid via — filled circle + crossbar */}
              <circle cx="46" cy="0" r="2.8"
                fill="#A855F7" fillOpacity="0.50" />
              <line x1="46" y1="-4.5" x2="46" y2="4.5"
                stroke="#A855F7" strokeOpacity="0.30" strokeWidth="1" />
              {/* Solana-style ◇ diamond tip */}
              <polygon points="76,-4 83,0 76,4 69,0"
                fill="#C084FC" fillOpacity="0.55"
                stroke="#C084FC" strokeOpacity="0.38" strokeWidth="0.6" />
              {/* Bright node at diamond apex */}
              <circle cx="83" cy="0" r="1.8"
                fill="#E9D5FF" fillOpacity="0.55" />
            </g>
          ))}

          {/* ── Teal arms → auxin leaf-bud tips ── */}
          {tealAngles.map((angle) => (
            <g key={`t${angle}`}
               transform={`translate(110,110) rotate(${angle})`}
               filter="url(#bloom-glow)">
              {/* PCB trace */}
              <line x1="18" y1="0" x2="76" y2="0"
                stroke="#14b8a6" strokeOpacity="0.42" strokeWidth="1.3" />
              {/* Mid via */}
              <circle cx="46" cy="0" r="2.8"
                fill="#14b8a6" fillOpacity="0.44" />
              <line x1="46" y1="-4.5" x2="46" y2="4.5"
                stroke="#14b8a6" strokeOpacity="0.26" strokeWidth="1" />
              {/* Auxin leaf-bud — teardrop pointing outward */}
              <path d="M76,-5 C85,-5 90,0 85,5 C82,5 76,5 76,-5Z"
                fill="#14F195" fillOpacity="0.30"
                stroke="#14F195" strokeOpacity="0.44" strokeWidth="0.8" />
              {/* Central leaf vein */}
              <line x1="76" y1="0" x2="89" y2="0"
                stroke="#14F195" strokeOpacity="0.32" strokeWidth="0.8" />
              {/* Tip node */}
              <circle cx="90" cy="0" r="1.5"
                fill="#14F195" fillOpacity="0.50" />
            </g>
          ))}

          {/* ── Hexagonal agent hub at centre ── */}
          {/* Outer hex glow ring */}
          <polygon points="110,97 121,104 121,116 110,123 99,116 99,104"
            fill="#A855F7" fillOpacity="0.07"
            stroke="#C084FC" strokeOpacity="0.48" strokeWidth="1.5" />
          {/* Inner filled circle */}
          <circle cx="110" cy="110" r="7.5"
            fill="#A855F7" fillOpacity="0.16" />
          {/* Core node */}
          <circle cx="110" cy="110" r="3.5"
            fill="#C084FC" fillOpacity="0.62" />
          {/* Hot-spot */}
          <circle cx="110" cy="110" r="1.5"
            fill="#E9D5FF" fillOpacity="0.90" />

        </pattern>
      </defs>

      <rect width="100%" height="100%" fill="url(#auxinCircuit)" />
    </svg>
  );
}

export default function DashboardPage() {
  const [isTwinFocus, setIsTwinFocus] = useState(false);
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

  useEffect(() => {
    if (!isTwinFocus) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsTwinFocus(false);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isTwinFocus]);

  return (
    <div className="relative min-h-screen overflow-hidden lg:h-screen" style={{ backgroundColor: "#070B14" }}>

      {/* ── Ambient bioluminescent blobs (z=0) ── */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden" style={{ zIndex: 0 }} aria-hidden>
        <div className="blob-a absolute -top-32 -left-32 w-[750px] h-[750px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(168,85,247,0.32) 0%, transparent 65%)", filter: "blur(80px)" }} />
        <div className="blob-b absolute top-1/4 -right-40 w-[600px] h-[600px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(20,241,149,0.20) 0%, transparent 65%)", filter: "blur(100px)" }} />
        <div className="blob-c absolute -bottom-40 left-1/4 w-[800px] h-[500px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(99,102,241,0.20) 0%, transparent 65%)", filter: "blur(120px)" }} />
        <div className="blob-d absolute -bottom-20 -right-20 w-[500px] h-[500px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(168,85,247,0.22) 0%, transparent 65%)", filter: "blur(70px)" }} />
        <div className="blob-e absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[560px] h-[560px] rounded-full"
          style={{ background: "radial-gradient(circle, rgba(99,102,241,0.08) 0%, transparent 65%)", filter: "blur(140px)" }} />
      </div>

      {/* ── Mechafloral tiling pattern (z=1, screen blend) ── */}
      <BackgroundPattern />

      {/* ── App content (z=2, above pattern) ── */}
      <div className="relative flex min-h-screen flex-col overflow-hidden lg:h-full" style={{ zIndex: 2 }}>

        {/* Header — with InvoiceDownloader on the right */}
        <div className="flex items-center gap-3 pr-4 shrink-0">
          <div className="flex-1 min-w-0">
            <Header />
          </div>
          <div className="hidden lg:block">
            <InvoiceDownloader />
          </div>
        </div>

        <main
          className={`relative flex-1 overflow-y-auto p-3 transition-all duration-300 lg:overflow-hidden lg:p-4 ${
            isTwinFocus ? "blur-md saturate-75" : ""
          }`}
        >
          <div className="flex flex-col gap-4 min-h-0 lg:h-full">

            {/* ── Row 1: Hero — RiskGauge + TreasuryPanel ── */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_2fr] shrink-0" style={{ minHeight: 320, maxHeight: 400 }}>
              <div className="min-h-0">
                <RiskGauge />
              </div>
              <div className="min-h-0">
                <TreasuryPanel />
              </div>
            </div>

            {/* ── Row 2: TelemetryCard + TwinViewport + PaymentTicker ── */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[290px_1fr_350px] flex-1 min-h-0">

              {/* Left — joint telemetry */}
              <div className="flex min-h-0 min-w-0 flex-col">
                <TelemetryCard />
              </div>

              {/* Centre — digital twin viewport */}
              <div className="flex h-full min-h-0 min-w-0 flex-col">
                <TwinViewport onToggleFocusMode={() => setIsTwinFocus(true)} />
              </div>

              {/* Right — bloom + payments */}
              <div className="flex min-h-0 min-w-0 flex-col gap-4 overflow-hidden">
                <div className="relative z-30 h-[86px] shrink-0">
                  <SystemBloomCard />
                </div>
                <div className="relative z-10 min-h-0 flex-1 overflow-hidden">
                  <PaymentTicker />
                </div>
              </div>

            </div>

            {/* ── Row 3: ComplianceTable (full width) ── */}
            <div className="shrink-0" style={{ minHeight: 180 }}>
              <ComplianceTable />
            </div>

          </div>
        </main>

        {isTwinFocus && (
          <>
            <div className="pointer-events-none fixed inset-0 bg-black/35" style={{ zIndex: 30 }} aria-hidden />
            <div className="fixed inset-3 z-40 lg:inset-6">
              <TwinViewport isFocusMode onToggleFocusMode={() => setIsTwinFocus(false)} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
