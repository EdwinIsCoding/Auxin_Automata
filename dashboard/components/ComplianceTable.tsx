"use client";

import { useState, useMemo } from "react";
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
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold tracking-widest border"
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
      className="flex items-center gap-1 font-mono text-xs hover:opacity-80 transition-opacity"
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
      className="border-b transition-colors hover:bg-purple-500/[0.04]"
      style={{
        borderColor: "rgba(168,85,247,0.08)",
        backgroundColor:
          log.severity === 3
            ? "rgba(239,68,68,0.05)"
            : isEven
            ? "rgba(168,85,247,0.02)"
            : undefined,
      }}
    >
      <td className="px-3 py-2 font-mono text-[11px]" style={{ color: "#3d4663" }}>
        {ts}
      </td>
      <td className="px-3 py-2">
        <SeverityBadge severity={log.severity} />
      </td>
      <td className="px-3 py-2 font-mono text-[11px]" style={{ color: "#e2e8f0" }}>
        {log.reasonCode}
      </td>
      <td className="px-3 py-2">
        <HashCell hash={log.hash} />
      </td>
      <td className="px-3 py-2">
        <a
          href={`https://explorer.solana.com/tx/${log.txSignature}?cluster=devnet`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 font-mono text-[11px] hover:opacity-80 transition-opacity"
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
  if (col !== sortKey) return <ChevronsUpDown className="h-3 w-3 opacity-40" />;
  return sortDir === "asc"
    ? <ChevronUp className="h-3 w-3" style={{ color: "#A855F7" }} />
    : <ChevronDown className="h-3 w-3" style={{ color: "#A855F7" }} />;
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

      {/* Table */}
      <div className="scroll-tech flex-1 overflow-y-auto">
        <table className="w-full text-left">
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
                className="px-3 py-2 text-[10px] font-bold tracking-[0.18em] uppercase cursor-pointer select-none"
                style={{ color: "#A855F7", opacity: sortKey === "timestamp" ? 1 : 0.7 }}
                onClick={() => handleSort("timestamp")}
              >
                <span className="inline-flex items-center gap-1">
                  Timestamp
                  <SortIcon col="timestamp" sortKey={sortKey} sortDir={sortDir} />
                </span>
              </th>
              {/* Sortable: Severity */}
              <th
                className="px-3 py-2 text-[10px] font-bold tracking-[0.18em] uppercase cursor-pointer select-none"
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
                  className="px-3 py-2 text-[10px] font-bold tracking-[0.18em] uppercase"
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
