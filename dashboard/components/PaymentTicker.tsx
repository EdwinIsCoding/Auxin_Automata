"use client";

import { useAuxinStore } from "@/lib/store";
import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, Loader2, Lock, Wallet } from "lucide-react";

function lamportsToSol(lamports: number): string {
  return (lamports / 1_000_000_000).toFixed(6);
}

function truncatePubkey(pk: string): string {
  return `${pk.slice(0, 4)}…${pk.slice(-4)}`;
}

function truncateSig(sig: string): string {
  return `${sig.slice(0, 8)}…${sig.slice(-6)}`;
}

function formatTime(ts: number): string {
  return new Date(ts).toISOString().slice(11, 19);
}

export function PaymentTicker() {
  const payments = useAuxinStore((s) => s.payments);
  const isLoading = useAuxinStore((s) => s.isLoading);

  if (isLoading) {
    return (
      <div className="card-surface flex items-center justify-center gap-3 p-6 h-full">
        <Loader2 className="h-5 w-5 animate-spin" style={{ color: "#14F195" }} />
        <span className="text-sm tracking-wider" style={{ color: "#64748b" }}>
          Awaiting payments…
        </span>
      </div>
    );
  }

  if (payments.length === 0) {
    return (
      <div className="card-surface flex flex-col items-center justify-center gap-3 p-6 h-full">
        <Wallet className="h-7 w-7" style={{ color: "#3d4663" }} />
        <p className="text-sm tracking-wider" style={{ color: "#64748b" }}>
          No payments recorded yet
        </p>
      </div>
    );
  }

  return (
    <div className="card-surface flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="card-header-green flex items-center justify-between px-4 py-3 shrink-0">
        <div className="flex items-center gap-2">
          <Wallet className="h-4 w-4" style={{ color: "#14F195" }} />
          <span
            className="text-xs font-bold tracking-[0.22em] uppercase"
            style={{ color: "#14F195" }}
          >
            Payment Stream
          </span>
        </div>
        <span
          className="text-[10px] font-mono tabular-nums px-2 py-0.5 rounded-full"
          style={{
            color: "#3d4663",
            backgroundColor: "rgba(20,241,149,0.05)",
            border: "1px solid rgba(20,241,149,0.12)",
          }}
        >
          {payments.length} events
        </span>
      </div>

      {/* Animated payment rows */}
      <div className="payment-bg scroll-tech flex-1 overflow-y-auto font-mono text-xs">
        <AnimatePresence initial={false}>
          {payments.map((p, i) => (
            <motion.div
              key={p.id}
              initial={{ opacity: 0, y: -20, rotateX: -8 }}
              animate={{ opacity: 1, y: 0, rotateX: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.40, ease: [0.22, 1, 0.36, 1] }}
              className={`row-interactive relative z-10 flex items-center gap-1.5 px-3 py-1.5 border-b hover:bg-white/[0.03] ${i === 0 ? "pay-newest" : ""}`}
              style={{
                borderColor: "rgba(20,241,149,0.07)",
                backgroundColor: i === 0 ? undefined : undefined,
              }}
            >
              {/* Newest-row green dot */}
              {i === 0 && (
                <span
                  className="shrink-0 w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: "#14F195", boxShadow: "0 0 6px #14F195" }}
                />
              )}

              {/* Timestamp */}
              <span className="shrink-0 tabular-nums" style={{ color: "#3d4663" }}>
                {formatTime(p.timestamp)}
              </span>

              {/* SOL amount — hidden behind lock icon when private */}
              {p.isPrivate ? (
                <span
                  className="shrink-0 w-24 flex items-center gap-1 font-bold"
                  style={{ color: "#A855F7" }}
                  title="Private Payment — amount and recipient shielded via Cloak"
                >
                  <Lock className="h-3 w-3" />
                  Private
                </span>
              ) : (
                <span
                  className="value-primary shrink-0 w-24 text-sm font-mono"
                  style={{
                    color: "#14F195",
                    textShadow: i === 0
                      ? "0 0 14px rgba(20,241,149,0.7), 0 0 6px rgba(20,241,149,0.4)"
                      : "0 0 8px rgba(20,241,149,0.3)",
                  }}
                >
                  ◎ {lamportsToSol(p.lamports)}
                </span>
              )}

              {/* Provider — hidden for private payments */}
              {p.isPrivate ? (
                <span className="shrink-0 text-[10px]" style={{ color: "#64748b" }}>
                  shielded recipient
                </span>
              ) : (
                <span className="shrink-0" style={{ color: "#C084FC" }}>
                  {truncatePubkey(p.providerPubkey)}
                </span>
              )}

              {/* Sig + link */}
              <div className="flex items-center gap-1 ml-auto shrink-0">
                <span style={{ color: "#3d4663" }}>{truncateSig(p.txSignature)}</span>
                <a
                  href={`https://explorer.solana.com/tx/${p.txSignature}?cluster=devnet`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:opacity-80 transition-opacity"
                  title="View on Solana Explorer"
                >
                  <ExternalLink className="h-3 w-3" style={{ color: "#A855F7" }} />
                </a>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
