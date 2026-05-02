"use client";

import { useState, useMemo, useRef } from "react";
import { motion } from "framer-motion";
import { useAuxinStore, type ComplianceLog } from "@/lib/store";
import {
  Copy,
  Check,
  ExternalLink,
  Loader2,
  ShieldCheck,
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
} from "lucide-react";

type SortKey = "timestamp" | "severity";
type SortDir = "asc" | "desc";

const SEVERITY_STYLES: Record<
  0 | 1 | 2 | 3,
  { label: string; bg: string; text: string; border: string }
> = {
  0: {
    label: "INFO",
    bg: "rgba(168,85,247,0.12)",
    text: "#C084FC",
    border: "rgba(168,85,247,0.35)",
  },
  1: {
    label: "LOW",
    bg: "rgba(234,179,8,0.10)",
    text: "#eab308",
    border: "rgba(234,179,8,0.35)",
  },
  2: {
    label: "HIGH",
    bg: "rgba(249,115,22,0.12)",
    text: "#f97316",
    border: "rgba(249,115,22,0.35)",
  },
  3: {
    label: "CRIT",
    bg: "rgba(239,68,68,0.14)",
    text: "#ef4444",
    border: "rgba(239,68,68,0.40)",
  },
};

function SeverityBadge({ severity }: { severity: 0 | 1 | 2 | 3 }) {
  const s = SEVERITY_STYLES[severity];
  return (
    <span
      className="inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-bold tracking-[0.12em]"
      style={{ backgroundColor: s.bg, color: s.text, borderColor: s.border }}
    >
      {s.label}
    </span>
  );
}

function HashCell({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);
  const truncated = `${hash.slice(0, 8)}…${hash.slice(-6)}`;

  function handleCopy() {
    navigator.clipboard.writeText(hash).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 font-mono text-[11px] hover:opacity-80 transition-opacity"
      title={hash}
    >
      <span style={{ color: "#C084FC" }}>{truncated}</span>
      {copied ? (
        <Check className="h-3 w-3 shrink-0" style={{ color: "#14F195" }} />
      ) : (
        <Copy className="h-3 w-3 shrink-0" style={{ color: "#3d4663" }} />
      )}
    </button>
  );
}

function LogRow({ log, index }: { log: ComplianceLog; index: number }) {
  const ts = new Date(log.timestamp).toISOString().slice(11, 23);
  const truncatedSig = `${log.txSignature.slice(0, 8)}…`;
  const isEven = index % 2 === 0;

  return (
    <tr
      className={`row-interactive border-b hover:bg-purple-500/[0.04] ${log.severity === 3 ? "crit-row-pulse" : ""}`}
      style={{
        borderColor: "rgba(168,85,247,0.08)",
        backgroundColor:
          log.severity === 3
            ? undefined  /* handled by crit-row-pulse animation */
            : isEven
            ? "rgba(168,85,247,0.02)"
            : undefined,
      }}
    >
      <td className="px-2 py-1 font-mono text-[10px] whitespace-nowrap" style={{ color: "#3d4663" }}>
        {ts}
      </td>
      <td className="px-2 py-1 whitespace-nowrap">
        <SeverityBadge severity={log.severity} />
      </td>
      <td className="px-2 py-1 font-mono text-[10px] max-w-[80px] truncate" style={{ color: "#e2e8f0" }}>
        {log.reasonCode}
      </td>
      <td className="px-2 py-1">
        <HashCell hash={log.hash} />
      </td>
      <td className="px-2 py-1">
        <a
          href={`https://explorer.solana.com/tx/${log.txSignature}?cluster=devnet`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 font-mono text-[10px] hover:opacity-80 transition-opacity"
          style={{ color: "#A855F7" }}
        >
          {truncatedSig}
          <ExternalLink className="h-3 w-3 shrink-0" />
        </a>
      </td>
    </tr>
  );
}

function SortIcon({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  const isActive = col === sortKey;
  const rotation = !isActive ? 0 : sortDir === "asc" ? 0 : 180;
  return (
    <motion.span
      animate={{ rotate: rotation }}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      style={{ display: "inline-flex" }}
    >
      {!isActive
        ? <ChevronsUpDown className="h-3 w-3 opacity-40" />
        : <ChevronUp className="h-3 w-3" style={{ color: "#A855F7" }} />}
    </motion.span>
  );
}

function ComplianceTimeline({ logs }: { logs: ComplianceLog[] }) {
  const recent = logs.slice(0, 20).reverse();

  if (recent.length === 0) return null;

  return (
    <div
      className="mx-3 mb-1 mt-2 rounded-xl border px-2 py-1.5"
      style={{
        borderColor: "rgba(168,85,247,0.20)",
        background:
          "linear-gradient(90deg, rgba(168,85,247,0.08) 0%, rgba(20,241,149,0.05) 100%)",
      }}
    >
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[9px] font-bold uppercase tracking-[0.16em]" style={{ color: "#A855F7" }}>
          Severity Timeline
        </span>
        <span className="text-[9px] font-mono uppercase tracking-[0.12em]" style={{ color: "#64748b" }}>
          last {recent.length} events
        </span>
      </div>
      {/* Stacked vertical bars — animate up from 0 on mount */}
      <div
        className="flex items-end gap-0.5"
        style={{ height: 28 }}
      >
        {recent.map((log, i) => {
          const sev = SEVERITY_STYLES[log.severity];
          /* Height proportional to severity (0→25%, 1→50%, 2→75%, 3→100%) */
          const heightPct = ((log.severity + 1) / 4) * 100;
          return (
            <motion.div
              key={log.id}
              className="flex-1 rounded-sm origin-bottom"
              title={`${new Date(log.timestamp).toISOString()} · ${sev.label} · ${log.reasonCode}`}
              initial={{ scaleY: 0 }}
              animate={{ scaleY: 1 }}
              transition={{ duration: 0.4, delay: i * 0.02, ease: "easeOut" }}
              style={{
                height: `${heightPct}%`,
                backgroundColor: sev.bg,
                border: `1px solid ${sev.border}`,
                boxShadow: log.severity === 3 ? "0 0 8px rgba(239,68,68,0.55)" : "none",
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

export function ComplianceTable() {
  const logs = useAuxinStore((s) => s.complianceLogs);
  const isLoading = useAuxinStore((s) => s.isLoading);

  const [sortKey, setSortKey] = useState<SortKey>("timestamp");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(col: SortKey) {
    if (col === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col);
      setSortDir("desc");
    }
  }

  const sorted = useMemo(() => {
    return [...logs].sort((a, b) => {
      const delta =
        sortKey === "timestamp"
          ? a.timestamp - b.timestamp
          : a.severity - b.severity;
      return sortDir === "asc" ? delta : -delta;
    });
  }, [logs, sortKey, sortDir]);

  if (isLoading) {
    return (
      <div className="card-surface flex items-center justify-center gap-3 p-6 h-full">
        <Loader2 className="h-5 w-5 animate-spin" style={{ color: "#A855F7" }} />
        <span className="text-sm tracking-wider" style={{ color: "#64748b" }}>
          Loading compliance log…
        </span>
      </div>
    );
  }

  if (logs.length === 0) {
    return (
      <div className="card-surface flex flex-col items-center justify-center gap-3 p-6 h-full">
        <ShieldCheck className="h-7 w-7" style={{ color: "#A855F7" }} />
        <p className="text-sm tracking-wider" style={{ color: "#64748b" }}>
          No compliance events recorded
        </p>
      </div>
    );
  }

  const critCount = logs.filter((l) => l.severity === 3).length;

  return (
    <div className="card-surface flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="card-header-purple flex items-center justify-between px-4 py-3 shrink-0">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" style={{ color: "#A855F7" }} />
          <span
            className="text-xs font-bold tracking-[0.22em] uppercase"
            style={{ color: "#C084FC" }}
          >
            Compliance Log
          </span>
        </div>
        <div className="flex items-center gap-3">
          {critCount > 0 && (
            <span
              className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full tracking-widest"
              style={{
                backgroundColor: "rgba(239,68,68,0.12)",
                color: "#ef4444",
                border: "1px solid rgba(239,68,68,0.35)",
              }}
            >
              <AlertTriangle className="h-3 w-3" />
              {critCount} CRIT
            </span>
          )}
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded-full"
            style={{
              color: "#3d4663",
              backgroundColor: "rgba(168,85,247,0.05)",
              border: "1px solid rgba(168,85,247,0.12)",
            }}
          >
            {logs.length} entries
          </span>
        </div>
      </div>

      <ComplianceTimeline logs={logs} />

      {/* Table */}
      <div className="scroll-tech flex-1 overflow-y-auto">
        <table className="w-full border-collapse text-left">
          <thead
            className="sticky top-0"
            style={{
              backgroundColor: "rgba(10,14,28,0.90)",
              backdropFilter: "blur(8px)",
              WebkitBackdropFilter: "blur(8px)",
            }}
          >
            <tr className="border-b" style={{ borderColor: "rgba(168,85,247,0.15)" }}>
              {/* Sortable: Timestamp */}
              <th
                className="cursor-pointer select-none px-2 py-1.5 text-[9px] font-bold uppercase tracking-[0.16em] whitespace-nowrap"
                style={{ color: "#A855F7", opacity: sortKey === "timestamp" ? 1 : 0.7 }}
                onClick={() => handleSort("timestamp")}
              >
                <span className="inline-flex items-center gap-1">
                  Time
                  <SortIcon col="timestamp" sortKey={sortKey} sortDir={sortDir} />
                </span>
              </th>
              {/* Sortable: Severity */}
              <th
                className="cursor-pointer select-none px-2 py-1.5 text-[9px] font-bold uppercase tracking-[0.16em] whitespace-nowrap"
                style={{ color: "#A855F7", opacity: sortKey === "severity" ? 1 : 0.7 }}
                onClick={() => handleSort("severity")}
              >
                <span className="inline-flex items-center gap-1">
                  Sev
                  <SortIcon col="severity" sortKey={sortKey} sortDir={sortDir} />
                </span>
              </th>
              {/* Non-sortable columns */}
              {["Reason", "Hash", "Tx"].map((h) => (
                <th
                  key={h}
                  className="px-2 py-1.5 text-[9px] font-bold uppercase tracking-[0.16em]"
                  style={{ color: "#A855F7", opacity: 0.7 }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((log, i) => (
              <LogRow key={log.id} log={log} index={i} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
