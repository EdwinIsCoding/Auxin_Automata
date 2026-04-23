/**
 * Umbra Bridge — Express sidecar for the Auxin SDK bridge.
 *
 * Wraps @umbra-privacy/sdk calls behind two REST endpoints so the Python
 * bridge can drive Umbra operations via HTTP on localhost.
 *
 * Endpoints
 * ---------
 *   POST /deposit   — Create a self-claimable UTXO in Umbra's mixer pool.
 *   POST /withdraw  — Claim a UTXO from the pool to a public ATA.
 *   GET  /health    — Liveness probe.
 *
 * Environment
 * -----------
 *   UMBRA_NETWORK    devnet | mainnet  (default: devnet)
 *   SOLANA_RPC_URL   HTTP RPC endpoint
 *   SOLANA_WS_URL    WebSocket RPC endpoint (derived from HTTP if absent)
 *   PORT             Sidecar listen port (default: 3002)
 */

import express from "express";
import {
  createSignerFromPrivateKeyBytes,
  getUmbraClient,
  getPublicBalanceToSelfClaimableUtxoCreatorFunction,
} from "@umbra-privacy/sdk";
import {
  getPublicBalanceToSelfClaimableUtxoCreatorProver,
  getSelfClaimableToPublicBalanceUtxoClaimerProver,
} from "@umbra-privacy/web-zk-prover";

const PORT = parseInt(process.env.PORT ?? "3002", 10);
const NETWORK = process.env.UMBRA_NETWORK ?? "devnet";
const RPC_URL = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const WS_URL =
  process.env.SOLANA_WS_URL ?? RPC_URL.replace("https://", "wss://");

const app = express();
app.use(express.json());

// ── Health ──────────────────────────────────────────────────────────────────

app.get("/health", (_req, res) => {
  res.json({ status: "ok", network: NETWORK });
});

// ── POST /deposit ───────────────────────────────────────────────────────────
// Body: { keypair_bytes: number[], mint: string, amount: number,
//         destination_address: string }
// Returns: { signature: string, utxo_commitment?: string }

app.post("/deposit", async (req, res) => {
  try {
    const { keypair_bytes, mint, amount, destination_address } = req.body;
    if (!keypair_bytes || !mint || !amount || !destination_address) {
      return res
        .status(400)
        .json({ error: "Missing required fields: keypair_bytes, mint, amount, destination_address" });
    }

    const signer = await createSignerFromPrivateKeyBytes(
      new Uint8Array(keypair_bytes),
    );

    const client = await getUmbraClient({
      signer,
      network: NETWORK,
      rpcUrl: RPC_URL,
      rpcSubscriptionsUrl: WS_URL,
    });

    const zkProver = getPublicBalanceToSelfClaimableUtxoCreatorProver();
    const createUtxo = getPublicBalanceToSelfClaimableUtxoCreatorFunction(
      { client },
      { zkProver },
    );

    const result = await createUtxo({
      destinationAddress: destination_address,
      mint,
      amount: BigInt(amount),
    });

    res.json({
      signature: result.queueSignature ?? result.callbackSignature ?? null,
      utxo_commitment: result.utxoCommitment ?? null,
    });
  } catch (err) {
    console.error("[umbra-bridge] deposit error:", err);
    res.status(500).json({ error: String(err.message ?? err) });
  }
});

// ── POST /withdraw ──────────────────────────────────────────────────────────
// Body: { keypair_bytes: number[], mint: string,
//         utxo_commitment: string, tree_index: number,
//         insertion_index: number }
// Returns: { signature: string }

app.post("/withdraw", async (req, res) => {
  try {
    const { keypair_bytes, mint, utxo_commitment, tree_index, insertion_index } =
      req.body;
    if (!keypair_bytes || !mint) {
      return res
        .status(400)
        .json({ error: "Missing required fields: keypair_bytes, mint" });
    }

    const signer = await createSignerFromPrivateKeyBytes(
      new Uint8Array(keypair_bytes),
    );

    const client = await getUmbraClient({
      signer,
      network: NETWORK,
      rpcUrl: RPC_URL,
      rpcSubscriptionsUrl: WS_URL,
    });

    // Dynamic import — the claim function names follow the same factory pattern
    const { getSelfClaimableToPublicBalanceUtxoClaimerFunction } =
      await import("@umbra-privacy/sdk");

    const zkProver = getSelfClaimableToPublicBalanceUtxoClaimerProver();
    const claimUtxo = getSelfClaimableToPublicBalanceUtxoClaimerFunction(
      { client },
      { zkProver },
    );

    const result = await claimUtxo({
      mint,
      treeIndex: tree_index ?? 0,
      insertionIndex: insertion_index ?? 0,
    });

    res.json({
      signature: result.signature ?? result.callbackSignature ?? null,
    });
  } catch (err) {
    console.error("[umbra-bridge] withdraw error:", err);
    res.status(500).json({ error: String(err.message ?? err) });
  }
});

// ── POST /viewing-key ───────────────────────────────────────────────────────
// Body: { keypair_bytes: number[], scope: "master" | "yearly" | "monthly" | "daily",
//         mint?: string, year?: number, month?: number, day?: number }
// Returns: { viewing_key: string, scope: string }

app.post("/viewing-key", async (req, res) => {
  try {
    const { keypair_bytes, scope, mint, year, month, day } = req.body;
    if (!keypair_bytes) {
      return res.status(400).json({ error: "Missing required field: keypair_bytes" });
    }

    const signer = await createSignerFromPrivateKeyBytes(
      new Uint8Array(keypair_bytes),
    );

    const client = await getUmbraClient({
      signer,
      network: NETWORK,
      rpcUrl: RPC_URL,
      rpcSubscriptionsUrl: WS_URL,
    });

    // The SDK derives viewing keys hierarchically from the master seed.
    // We export the scoped key as a hex string for the Python side.
    const { getViewingKeyDeriverFunction } = await import("@umbra-privacy/sdk");
    const deriveViewingKey = getViewingKeyDeriverFunction({ client });

    const result = await deriveViewingKey({
      scope: scope ?? "master",
      mint: mint ?? undefined,
      year: year ?? undefined,
      month: month ?? undefined,
      day: day ?? undefined,
    });

    res.json({
      viewing_key: result.viewingKeyHex ?? result.viewingKey ?? null,
      scope: scope ?? "master",
    });
  } catch (err) {
    console.error("[umbra-bridge] viewing-key error:", err);
    res.status(500).json({ error: String(err.message ?? err) });
  }
});

// ── Start ───────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(
    `[umbra-bridge] listening on :${PORT}  network=${NETWORK}  rpc=${RPC_URL}`,
  );
});
