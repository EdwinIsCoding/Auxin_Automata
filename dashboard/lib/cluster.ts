/**
 * lib/cluster.ts
 * --------------
 * Cluster detection and Explorer link utilities for the Auxin Automata
 * dual-cluster architecture (Devnet / Mainnet).
 *
 * Usage
 * -----
 *   import { detectCluster, explorerUrl, clusterLabel, clusterColor } from "@/lib/cluster";
 *
 *   const cluster = detectCluster(process.env.NEXT_PUBLIC_SOLANA_RPC_URL ?? "");
 *   // "mainnet" | "devnet"
 */

/** Detect the active cluster from an RPC URL string. */
export function detectCluster(rpcUrl: string): "mainnet" | "devnet" {
  if (!rpcUrl) return "devnet";
  const lower = rpcUrl.toLowerCase();
  if (lower.includes("mainnet") || lower.includes("mainnet-beta")) return "mainnet";
  return "devnet";
}

/**
 * Return a Solana Explorer link for the given transaction signature.
 * Appends ?cluster=devnet for Devnet; no suffix for Mainnet (Explorer default).
 */
export function explorerUrl(signature: string, cluster: "mainnet" | "devnet"): string {
  const base = `https://explorer.solana.com/tx/${signature}`;
  return cluster === "devnet" ? `${base}?cluster=devnet` : base;
}

/** Human-readable cluster label. */
export function clusterLabel(cluster: "mainnet" | "devnet"): string {
  return cluster === "mainnet" ? "MAINNET" : "DEVNET";
}

/**
 * Tailwind CSS color class for the cluster indicator.
 * Mainnet → green (#14F195 family); Devnet → amber (#eab308 family).
 */
export function clusterColor(cluster: "mainnet" | "devnet"): string {
  return cluster === "mainnet" ? "#14F195" : "#eab308";
}

/** The active cluster, derived from NEXT_PUBLIC_SOLANA_RPC_URL at build time. */
export const ACTIVE_CLUSTER: "mainnet" | "devnet" = detectCluster(
  process.env.NEXT_PUBLIC_SOLANA_RPC_URL ?? process.env.NEXT_PUBLIC_HELIUS_RPC_URL ?? ""
);
