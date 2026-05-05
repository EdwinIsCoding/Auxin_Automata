/**
 * lib/solana.ts
 * -------------
 * Solana connection factory consumed by useProgramEvents and any future
 * read-only anchor usage in the dashboard.
 *
 * Falls back to the public Devnet endpoint when NEXT_PUBLIC_HELIUS_RPC_URL
 * is unset so the mock build never requires env vars.
 *
 * Explorer links: use explorerUrl() from lib/cluster.ts rather than
 * constructing https://explorer.solana.com URLs directly in components.
 */

import { Connection, PublicKey } from "@solana/web3.js";
import { detectCluster, explorerUrl as _explorerUrl, ACTIVE_CLUSTER } from "@/lib/cluster";

// Deployed program ID — can be overridden via env for localnet testing.
export const PROGRAM_ID_STR =
  process.env.NEXT_PUBLIC_PROGRAM_ID ??
  "7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm";

export const RPC_URL =
  process.env.NEXT_PUBLIC_HELIUS_RPC_URL ??
  process.env.NEXT_PUBLIC_SOLANA_RPC_URL ??
  "";

/** The cluster inferred from the RPC URL at build time. */
export const cluster = ACTIVE_CLUSTER;

// Lazy singleton — created at most once per browser session.
let _programId: PublicKey | null = null;

/**
 * Returns the PROGRAM_ID as a PublicKey, or null if the string is invalid.
 * Cached after the first successful parse.
 */
export function getProgramId(): PublicKey | null {
  if (_programId) return _programId;
  try {
    _programId = new PublicKey(PROGRAM_ID_STR);
    return _programId;
  } catch {
    return null;
  }
}

/**
 * Creates a new Solana Connection pointed at the configured RPC URL.
 * Automatically derives the wss:// WebSocket endpoint from the http(s):// URL.
 *
 * Returns null when no RPC URL is configured (mock-only mode).
 */
export function makeConnection(): Connection | null {
  if (!RPC_URL) return null;
  const wsEndpoint = RPC_URL.replace(/^https?/, (p) =>
    p === "https" ? "wss" : "ws"
  );
  return new Connection(RPC_URL, {
    commitment: "confirmed",
    wsEndpoint,
  });
}

/**
 * Returns a Solana Explorer link for the given transaction signature,
 * using the cluster inferred from NEXT_PUBLIC_SOLANA_RPC_URL.
 */
export function getExplorerUrl(signature: string): string {
  return _explorerUrl(signature, cluster);
}
