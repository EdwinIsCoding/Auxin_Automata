#!/usr/bin/env node
/**
 * keygen.mjs — Generate a Cloak UTXO keypair and derive the viewing key.
 *
 * Used by scripts/setup_cloak_provider.py for one-time provider registration
 * and by operators who want to derive their viewing key for auditor disclosure.
 *
 * stdin  (JSON):
 *   {
 *     "action": "generate" | "derive_viewing_key",
 *     "utxo_private_key_hex": "<hex, required for derive_viewing_key>"
 *   }
 *
 * stdout (JSON):
 *   For "generate":
 *   {
 *     "utxo_private_key_hex": "<hex>",
 *     "utxo_public_key":      "<bigint as string>",
 *     "viewing_key":          "<hex viewing key>",
 *     "nullifier_key":        "<hex nk>"
 *   }
 *
 *   For "derive_viewing_key":
 *   {
 *     "viewing_key": "<hex viewing key>",
 *     "nullifier_key": "<hex nk>"
 *   }
 */

import { readFileSync } from "fs";
import {
  generateUtxoKeypair,
  getNkFromUtxoPrivateKey,
  deriveViewingKeyFromNk,
} from "@cloak.dev/sdk";

async function main() {
  const raw = readFileSync("/dev/stdin", "utf-8");
  const input = JSON.parse(raw);
  const { action } = input;

  if (action === "generate") {
    const keypair = generateUtxoKeypair();
    const nk = getNkFromUtxoPrivateKey(keypair.privateKey);
    const viewingKey = deriveViewingKeyFromNk(nk);

    process.stdout.write(
      JSON.stringify({
        utxo_private_key_hex: keypair.privateKey.toString(16),
        utxo_public_key: keypair.publicKey.toString(),
        viewing_key: Buffer.from(viewingKey.viewingKey ?? viewingKey).toString("hex"),
        nullifier_key: Buffer.from(nk).toString("hex"),
      }) + "\n",
    );
  } else if (action === "derive_viewing_key") {
    const { utxo_private_key_hex } = input;
    if (!utxo_private_key_hex) {
      throw new Error("utxo_private_key_hex is required for derive_viewing_key");
    }

    const privateKey = BigInt("0x" + utxo_private_key_hex);
    const nk = getNkFromUtxoPrivateKey(privateKey);
    const viewingKey = deriveViewingKeyFromNk(nk);

    process.stdout.write(
      JSON.stringify({
        viewing_key: Buffer.from(viewingKey.viewingKey ?? viewingKey).toString("hex"),
        nullifier_key: Buffer.from(nk).toString("hex"),
      }) + "\n",
    );
  } else {
    throw new Error(`Unknown action: ${action}. Expected "generate" or "derive_viewing_key".`);
  }
}

main().catch((err) => {
  process.stderr.write(JSON.stringify({ error: err?.message ?? String(err) }) + "\n");
  process.exit(1);
});
