"use client";

/**
 * useProgramEvents  (2C.6)
 * ------------------------
 * Subscribes to on-chain Anchor program logs via connection.onLogs().
 * Decodes ComputePaymentEvent and ComplianceEvent using the IDL's event
 * discriminators + a minimal inline Borsh reader (lib/anchor.ts), and
 * falls back to text-based log scanning when the binary decode fails
 * (e.g. log-only RPC endpoints that redact "Program data:" lines).
 *
 * Required env vars (both must be set for live mode; omitting either is safe
 * — the hook becomes a no-op and the dashboard runs on mock data):
 *   NEXT_PUBLIC_HELIUS_RPC_URL  – WebSocket-capable RPC (Helius wss://)
 *   NEXT_PUBLIC_PROGRAM_ID      – Deployed agentic_hardware_bridge address
 *
 * Reconnect: connection.onLogs uses the underlying WebSocket maintained by
 * @solana/web3.js which reconnects automatically on drop.
 *
 * Dedup: signatures are tracked in a bounded set (MAX_SEEN = 2 000) so
 * re-delivered logs don't produce duplicate UI rows.
 */

import { useEffect, useRef } from "react";
import type { Logs } from "@solana/web3.js";
import { useAuxinStore } from "./store";
import type { PaymentEvent, ComplianceLog } from "./store";
import { makeConnection, getProgramId, RPC_URL } from "./solana";
import { tryDecodeEvent } from "./anchor";

// ── Dedup set (bounded) ───────────────────────────────────────────────────────

const MAX_SEEN = 2_000;
const seen = new Set<string>();

function markSeen(sig: string): boolean {
  if (seen.has(sig)) return false;
  seen.add(sig);
  if (seen.size > MAX_SEEN) {
    const first = seen.values().next().value;
    if (first !== undefined) seen.delete(first);
  }
  return true;
}

// ── Text-based fallback parser ────────────────────────────────────────────────
// Used when binary decode doesn't recognise the event (e.g. filtered RPC).

function textFallback(
  logs: string[],
  signature: string,
): void {
  const store = useAuxinStore.getState();
  const now   = Date.now();
  const joined = logs.join("\n");

  if (joined.includes("ComputePaymentEvent") || joined.includes("stream_compute_payment")) {
    const lamportsMatch = joined.match(/lamports[:\s]+(\d+)/);
    const lamports      = lamportsMatch ? parseInt(lamportsMatch[1], 10) : 0;
    const pubkeyMatch   = joined.match(/provider[:\s]+([1-9A-HJ-NP-Za-km-z]{32,44})/);
    const provider      = pubkeyMatch?.[1] ?? "";
    const event: PaymentEvent = {
      id:             signature.slice(0, 16),
      timestamp:      now,
      lamports,
      providerPubkey: provider,
      txSignature:    signature,
      isPrivate:      false,
      privacyProvider: "direct",
    };
    store.addPayment(event);
  }

  if (joined.includes("ComplianceEvent") || joined.includes("log_compliance_event")) {
    const sevMatch  = joined.match(/severity[:\s]+(\d)/);
    const severity  = Math.min(parseInt(sevMatch?.[1] ?? "1", 10), 3) as 0 | 1 | 2 | 3;
    const hashMatch = joined.match(/hash[:\s]+([0-9a-f]{64})/i);
    const hash      = hashMatch?.[1] ?? signature.slice(0, 64);
    const log: ComplianceLog = {
      id:          signature.slice(0, 16),
      timestamp:   now,
      severity,
      reasonCode:  "ON_CHAIN_COMPLIANCE_EVENT",
      hash,
      txSignature: signature,
    };
    store.addComplianceLog(log);
  }
}

// ── Log handler ───────────────────────────────────────────────────────────────

function handleLogs(logsResult: Logs): void {
  if (logsResult.err) return; // skip failed txs
  const { signature, logs } = logsResult;
  if (!markSeen(signature)) return;

  const store = useAuxinStore.getState();
  let decoded = false;

  // Primary path: binary decode from "Program data:" lines
  for (const line of logs) {
    const result = tryDecodeEvent(line, signature);
    if (!result) continue;
    decoded = true;
    if (result.type === "payment")    store.addPayment(result.event);
    if (result.type === "compliance") store.addComplianceLog(result.event);
  }

  // Fallback: text-scan for human-readable event names
  if (!decoded) textFallback(logs, signature);
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useProgramEvents(): void {
  const subIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!RPC_URL) return; // mock mode — no RPC configured

    const programId  = getProgramId();
    const connection = makeConnection();
    if (!programId || !connection) return;

    subIdRef.current = connection.onLogs(programId, handleLogs, "confirmed");

    return () => {
      if (subIdRef.current !== null) {
        connection.removeOnLogsListener(subIdRef.current).catch(() => {});
        subIdRef.current = null;
      }
    };
  }, []);
}
