"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Copy, Check, Cpu, Wifi, WifiOff, Loader2 } from "lucide-react";
import { useAuxinStore } from "@/lib/store";
import type { WsStatus } from "@/lib/store";

// Falls back to the deployed agent PDA placeholder if the env var isn't set.
const AGENT_PUBKEY =
  process.env.NEXT_PUBLIC_AGENT_PUBKEY ??
  "AuxiNdemo1111111111111111111111111111111111";

const STATUS_CONFIG: Record<
  WsStatus,
  { label: string; color: string; icon: React.ReactNode; glow: string }
> = {
  live: {
    label: "Live",
    color: "#14F195",
    icon: <Activity className="h-3.5 w-3.5" />,
    glow: "0 0 18px rgba(20,241,149,0.35), 0 0 8px rgba(168,85,247,0.15)",
  },
  connecting: {
    label: "Connecting",
    color: "#eab308",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    glow: "0 0 14px rgba(234,179,8,0.30)",
  },
  disconnected: {
    label: "Offline",
    color: "#ef4444",
    icon: <WifiOff className="h-3.5 w-3.5" />,
    glow: "0 0 14px rgba(239,68,68,0.30)",
  },
};

export function Header() {
  const [copied, setCopied] = useState(false);
  const wsStatus = useAuxinStore((s) => s.wsStatus);
  const cfg = STATUS_CONFIG[wsStatus];

  function handleCopy() {
    navigator.clipboard.writeText(AGENT_PUBKEY).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const truncated = `${AGENT_PUBKEY.slice(0, 6)}…${AGENT_PUBKEY.slice(-6)}`;

  return (
    <header
      className="header-underline w-full px-6 py-3 flex items-center justify-between shrink-0"
      style={{
        backgroundColor: "rgba(7, 11, 20, 0.85)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        boxShadow: "0 -1px 0 rgba(168,85,247,0.10) inset, 0 4px 32px rgba(0,0,0,0.6), 0 0 60px -20px rgba(168,85,247,0.18)",
      }}
    >
      {/* Left: brand */}
      <div className="flex items-center gap-3">
        <motion.div
          animate={{ color: ["#A855F7", "#14F195", "#A855F7"] }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        >
          <Cpu className="h-5 w-5 shrink-0" />
        </motion.div>
        <div>
          <h1 className="text-sm font-bold tracking-[0.35em] uppercase text-gradient-brand">
            Auxin Automata
          </h1>
          <p
            className="text-[11px] tracking-[0.18em] uppercase font-medium"
            style={{ color: "#A855F7", opacity: 0.7 }}
          >
            Agentic Infrastructure Node
          </p>
        </div>
      </div>

      {/* Centre: agent pubkey */}
      <div className="hidden md:flex items-center gap-2">
        <span
          className="text-[10px] font-mono tracking-[0.15em] uppercase"
          style={{ color: "#4b5563" }}
        >
          Agent
        </span>
        <span
          className="text-xs font-mono px-3 py-1 rounded-full"
          style={{
            color: "#C084FC",
            backgroundColor: "rgba(168,85,247,0.08)",
            border: "1px solid rgba(168,85,247,0.25)",
          }}
        >
          {truncated}
        </span>
        <button
          onClick={handleCopy}
          className="rounded-full p-1.5 transition-all hover:bg-purple-500/10"
          aria-label="Copy pubkey"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5" style={{ color: "#14F195" }} />
          ) : (
            <Copy className="h-3.5 w-3.5" style={{ color: "#6b21a8" }} />
          )}
        </button>
      </div>

      {/* Right: dynamic connection status */}
      <AnimatePresence mode="wait">
        <motion.div
          key={wsStatus}
          className="flex items-center gap-2 px-3 py-1.5 rounded-full"
          style={{
            backgroundColor: `${cfg.color}0f`,
            border: `1px solid ${cfg.color}33`,
          }}
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{
            opacity: 1,
            scale: 1,
            boxShadow:
              wsStatus === "live"
                ? [
                    "0 0 0px rgba(20,241,149,0)",
                    cfg.glow,
                    "0 0 0px rgba(20,241,149,0)",
                  ]
                : cfg.glow,
          }}
          exit={{ opacity: 0, scale: 0.92 }}
          transition={
            wsStatus === "live"
              ? { duration: 3, repeat: Infinity, ease: "easeInOut" }
              : { duration: 0.25 }
          }
        >
          {wsStatus === "live" && (
            <span className="relative flex h-2 w-2">
              {/* Outer ring — slower */}
              <span
                className="absolute inline-flex h-full w-full rounded-full"
                style={{
                  backgroundColor: cfg.color,
                  animation: "ripple-ring 2s ease-out infinite",
                  animationDelay: "0s",
                }}
              />
              {/* Inner ring — faster offset */}
              <span
                className="absolute inline-flex h-full w-full rounded-full"
                style={{
                  backgroundColor: cfg.color,
                  animation: "ripple-ring 2s ease-out infinite",
                  animationDelay: "0.7s",
                }}
              />
              <span
                className="relative inline-flex rounded-full h-2 w-2"
                style={{ backgroundColor: cfg.color }}
              />
            </span>
          )}
          <span style={{ color: cfg.color }}>{cfg.icon}</span>
          <span
            className="text-xs font-bold tracking-[0.18em] uppercase"
            style={{ color: cfg.color }}
          >
            {cfg.label}
          </span>
        </motion.div>
      </AnimatePresence>
    </header>
  );
}
