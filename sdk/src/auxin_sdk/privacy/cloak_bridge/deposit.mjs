#!/usr/bin/env node
/**
 * deposit.mjs — Cloak shield pool deposit via @cloak.dev/sdk
 *
 * Called by CloakProvider (Python) as a subprocess.
 *
 * stdin  (JSON):
 *   {
 *     "rpc_url":            "https://...",
 *     "wallet_secret_b64":  "<base64-encoded 64-byte Solana keypair>",
 *     "provider_pubkey":    "<base58 provider public key>",
 *     "amount_lamports":    5000,
 *     "program_id":         "zh1eLd6rSphLejbFfJEneUwzHRfMKxgzrgkfwA6qRkW",
 *     "relay_url":          null
 *   }
 *
 * stdout (JSON):
 *   {
 *     "signature":              "<solana tx signature>",
 *     "utxo_commitment":        "<hex commitment hash>",
 *     "utxo_private_key_hex":   "<hex UTXO private key for recipient withdrawal>",
 *     "confirmation_slot":      12345678
 *   }
 *
 * stderr (JSON on error):
 *   { "error": "human-readable message" }
 *
 * Exit codes: 0 = success, 1 = error
 */

import { readFileSync } from "fs";
import { Connection, Keypair } from "@solana/web3.js";
import {
  generateUtxoKeypair,
  createUtxo,
  createZeroUtxo,
  transact,
} from "@cloak.dev/sdk";

async function main() {
  // ── Parse stdin ────────────────────────────────────────────────────────────
  const raw = readFileSync("/dev/stdin", "utf-8");
  const input = JSON.parse(raw);
  const {
    rpc_url,
    wallet_secret_b64,
    amount_lamports,
    // provider_pubkey is logged but not used in the deposit tx itself —
    // the shield pool deposit is unlinkable to any recipient identity.
    // The recipient uses their UTXO private key to withdraw later.
  } = input;

  if (!rpc_url || !wallet_secret_b64 || !amount_lamports) {
    throw new Error("Missing required fields: rpc_url, wallet_secret_b64, amount_lamports");
  }

  // ── Reconstruct Solana signer ──────────────────────────────────────────────
  const secretBytes = Buffer.from(wallet_secret_b64, "base64");
  const wallet = Keypair.fromSecretKey(new Uint8Array(secretBytes));

  const connection = new Connection(rpc_url, "confirmed");

  // ── Generate UTXO keypair (the "stealth commitment" for this payment) ──────
  // Each payment gets a unique UTXO keypair.  The private key is returned to
  // the Python caller so it can be stored and later shared with the recipient
  // for withdrawal.  This is the privacy primitive: the on-chain commitment
  // is unlinkable to the recipient's public identity.
  const utxoKeypair = generateUtxoKeypair();

  // ── Create the output UTXO ─────────────────────────────────────────────────
  // Cloak requires exactly 2 inputs and 2 outputs per transaction.
  // For a deposit: 2 zero inputs, 1 funded output + 1 zero padding output.
  const outputUtxo = createUtxo(BigInt(amount_lamports), utxoKeypair);
  const zeroInput1 = createZeroUtxo();
  const zeroInput2 = createZeroUtxo();
  const zeroPad = createZeroUtxo();

  // ── Execute deposit (ZK proof generation + Solana tx submission) ────────────
  // externalAmount > 0 means deposit from the wallet into the shield pool.
  const result = await transact(
    {
      inputUtxos: [zeroInput1, zeroInput2],
      outputUtxos: [outputUtxo, zeroPad],
      externalAmount: BigInt(amount_lamports),
    },
    {
      signer: wallet,
      connection,
    },
  );

  // ── Output result ──────────────────────────────────────────────────────────
  // The SDK may return the signature under different keys depending on version.
  const signature = result.signature ?? result.txid ?? result.txSignature ?? null;

  const output = {
    signature,
    utxo_commitment: outputUtxo.commitment?.toString(16) ?? "",
    utxo_private_key_hex: utxoKeypair.privateKey.toString(16),
    confirmation_slot: result.slot ?? result.confirmationSlot ?? null,
  };

  process.stdout.write(JSON.stringify(output) + "\n");
}

main().catch((err) => {
  const msg = err?.message ?? String(err);
  process.stderr.write(JSON.stringify({ error: msg }) + "\n");
  process.exit(1);
});
