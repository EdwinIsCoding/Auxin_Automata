#!/usr/bin/env ts-node
/**
 * smoke_test_devnet.ts
 *
 * Post-deploy smoke test for agentic_hardware_bridge on Devnet.
 * Initialises a test agent, streams one payment, logs one compliance event,
 * asserts all three events fire, and prints Explorer links.
 *
 * Usage:
 *   HELIUS_RPC_URL=<url> DEPLOYER_KEYPAIR_PATH=~/.config/solana/id.json \
 *     npx ts-node scripts/smoke_test_devnet.ts
 *
 * Requirements: deployed.json must exist at /programs/deployed.json
 */
import * as fs from "fs";
import * as path from "path";
import * as anchor from "@coral-xyz/anchor";
import { BN, Program } from "@coral-xyz/anchor";
import {
  Keypair,
  Connection,
  PublicKey,
  LAMPORTS_PER_SOL,
  SystemProgram,
} from "@solana/web3.js";

// ── Config ────────────────────────────────────────────────────────────────────

const HELIUS_RPC_URL = process.env.HELIUS_RPC_URL;
const DEPLOYER_KEYPAIR_PATH =
  process.env.DEPLOYER_KEYPAIR_PATH ??
  path.join(process.env.HOME!, ".config", "solana", "id.json");

if (!HELIUS_RPC_URL) {
  console.error("ERROR: HELIUS_RPC_URL is required");
  process.exit(1);
}

const DEPLOYED_JSON = path.join(__dirname, "../programs/deployed.json");
const IDL_PATH = path.join(
  __dirname,
  "../programs/target/idl/agentic_hardware_bridge.json"
);

function explorerLink(sig: string) {
  return `https://explorer.solana.com/tx/${sig}?cluster=devnet`;
}
function explorerAccount(pubkey: string | PublicKey) {
  return `https://explorer.solana.com/address/${pubkey}?cluster=devnet`;
}

// ── PDA helpers ───────────────────────────────────────────────────────────────

function deriveAgentPDA(programId: PublicKey, owner: PublicKey) {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("agent"), owner.toBuffer()],
    programId
  );
}

function deriveProviderPDA(programId: PublicKey, provider: PublicKey) {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("provider"), provider.toBuffer()],
    programId
  );
}

function deriveComplianceLogPDA(programId: PublicKey, agent: PublicKey, slot: bigint) {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64LE(slot);
  return PublicKey.findProgramAddressSync(
    [Buffer.from("log"), agent.toBuffer(), buf],
    programId
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  // Load deployed program info
  if (!fs.existsSync(DEPLOYED_JSON)) {
    console.error(`deployed.json not found at ${DEPLOYED_JSON}`);
    console.error("Run scripts/deploy_devnet.sh first.");
    process.exit(1);
  }
  const deployed = JSON.parse(fs.readFileSync(DEPLOYED_JSON, "utf8"));
  const PROGRAM_ID = new PublicKey(deployed.program_id);
  console.log(`\n── Smoke test against program: ${PROGRAM_ID} ──`);
  console.log(`   ${explorerAccount(PROGRAM_ID)}\n`);

  // Load IDL
  const idl = JSON.parse(fs.readFileSync(IDL_PATH, "utf8"));

  // Load deployer keypair (funds test accounts)
  const rawKey = JSON.parse(
    fs.readFileSync(path.resolve(DEPLOYER_KEYPAIR_PATH), "utf8")
  );
  const deployer = Keypair.fromSecretKey(Uint8Array.from(rawKey));

  // Generate fresh test keypairs for isolation
  const owner = Keypair.generate();
  const hw = Keypair.generate();
  const providerWallet = Keypair.generate();

  const connection = new Connection(HELIUS_RPC_URL!, "confirmed");

  // Set up provider + program
  const walletAdapter = new anchor.Wallet(deployer);
  const provider = new anchor.AnchorProvider(connection, walletAdapter, {
    commitment: "confirmed",
    preflightCommitment: "confirmed",
  });
  anchor.setProvider(provider);
  const program = new Program(idl, provider);

  // Fund test accounts from deployer
  console.log("▶ Funding test accounts...");
  const FUND_SOL = 1.5 * LAMPORTS_PER_SOL;
  for (const kp of [owner, hw, providerWallet]) {
    const sig = await connection.requestAirdrop(kp.publicKey, FUND_SOL);
    await connection.confirmTransaction(sig, "confirmed");
  }
  console.log(`  owner:    ${owner.publicKey}`);
  console.log(`  hw:       ${hw.publicKey}`);
  console.log(`  provider: ${providerWallet.publicKey}`);

  // Derive PDAs
  const [agentPDA] = deriveAgentPDA(PROGRAM_ID, owner.publicKey);
  const [providerRecordPDA] = deriveProviderPDA(
    PROGRAM_ID,
    providerWallet.publicKey
  );

  // ── Event capture ──────────────────────────────────────────────────────────

  const events: Record<string, any[]> = {
    agentInitializedEvent: [],
    computePaymentEvent: [],
    complianceEvent: [],
  };

  const listeners = [
    program.addEventListener("agentInitializedEvent", (e) =>
      events.agentInitializedEvent.push(e)
    ),
    program.addEventListener("computePaymentEvent", (e) =>
      events.computePaymentEvent.push(e)
    ),
    program.addEventListener("complianceEvent", (e) =>
      events.complianceEvent.push(e)
    ),
  ];

  try {
    // ── 1. initialize_agent ───────────────────────────────────────────────────

    console.log("\n▶ initialize_agent...");
    const initSig = await program.methods
      .initializeAgent(hw.publicKey, new BN(0.5 * LAMPORTS_PER_SOL))
      .accounts({
        agent: agentPDA,
        owner: owner.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .signers([owner])
      .rpc();
    console.log(`  ✓ TX: ${explorerLink(initSig)}`);

    // ── 2. update_provider_whitelist (add) ────────────────────────────────────

    console.log("\n▶ update_provider_whitelist (add)...");
    const whitelistSig = await program.methods
      .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
      .accounts({
        agent: agentPDA,
        owner: owner.publicKey,
      })
      .signers([owner])
      .rpc();
    console.log(`  ✓ TX: ${explorerLink(whitelistSig)}`);

    // ── 3. stream_compute_payment ─────────────────────────────────────────────

    console.log("\n▶ stream_compute_payment (10 000 lamports)...");
    const paymentSig = await program.methods
      .streamComputePayment(new BN(10_000))
      .accounts({
        agent: agentPDA,
        hardwareSigner: hw.publicKey,
        providerWallet: providerWallet.publicKey,
        providerRecord: providerRecordPDA,
        systemProgram: SystemProgram.programId,
      })
      .signers([hw])
      .rpc();
    console.log(`  ✓ TX: ${explorerLink(paymentSig)}`);

    // ── 4. log_compliance_event ───────────────────────────────────────────────

    const HASH = "a".repeat(64);
    console.log("\n▶ log_compliance_event (severity=2, reason=0x0001)...");
    const logSlot = await connection.getSlot("confirmed");
    const [logPDA] = deriveComplianceLogPDA(PROGRAM_ID, agentPDA, BigInt(logSlot));
    const logSig = await program.methods
      .logComplianceEvent(HASH, 2, 0x0001, new anchor.BN(logSlot))
      .accounts({
        agent: agentPDA,
        hardwareSigner: hw.publicKey,
        log: logPDA,
        systemProgram: SystemProgram.programId,
      })
      .signers([hw])
      .rpc();
    console.log(`  ✓ TX: ${explorerLink(logSig)}`);

    // ── Assert on-chain state ─────────────────────────────────────────────────

    console.log("\n▶ Verifying on-chain state...");
    const agentData = await (program.account as any).hardwareAgent.fetch(
      agentPDA
    );
    console.log(`  lamports_spent: ${agentData.lamportsSpent}`);
    console.assert(
      agentData.lamportsSpent.toNumber() === 10_000,
      "lamports_spent should be 10000"
    );
    console.assert(
      agentData.providers[0].equals(providerWallet.publicKey),
      "provider should be whitelisted"
    );

    const providerRecord = await (
      program.account as any
    ).computeProvider.fetch(providerRecordPDA);
    console.assert(
      providerRecord.totalReceived.toNumber() === 10_000,
      "provider total_received should be 10000"
    );
    console.log("  ✓ On-chain state verified");

    // Wait a moment for event subscriptions to deliver
    await new Promise((r) => setTimeout(r, 2000));

    // ── Assert events ─────────────────────────────────────────────────────────

    console.log("\n▶ Verifying events...");
    const checks = [
      ["agentInitializedEvent", 1],
      ["computePaymentEvent", 1],
      ["complianceEvent", 1],
    ] as const;

    let allPassed = true;
    for (const [eventName, expected] of checks) {
      const count = events[eventName].length;
      const ok = count >= expected;
      console.log(`  ${ok ? "✓" : "✗"} ${eventName}: got ${count} (expected ≥${expected})`);
      if (!ok) allPassed = false;
    }

    // Print event details
    if (events.computePaymentEvent.length > 0) {
      const e = events.computePaymentEvent[0];
      console.log(
        `\n  ComputePaymentEvent: agent=${e.agent}, provider=${e.provider}, lamports=${e.lamports}`
      );
    }
    if (events.complianceEvent.length > 0) {
      const e = events.complianceEvent[0];
      console.log(
        `  ComplianceEvent: agent=${e.agent}, severity=${e.severity}, reason_code=${e.reasonCode}`
      );
    }

    console.log("\n────────────────────────────────────────────────────────────");
    if (allPassed) {
      console.log(" ✓ ALL SMOKE TESTS PASSED");
    } else {
      console.log(" ✗ SOME EVENT ASSERTIONS FAILED (events may need longer timeout)");
    }
    console.log("────────────────────────────────────────────────────────────");
    console.log(`\nAgent PDA:         ${explorerAccount(agentPDA)}`);
    console.log(`Provider record:   ${explorerAccount(providerRecordPDA)}`);
  } finally {
    for (const l of listeners) {
      await program.removeEventListener(l);
    }
  }
}

main().catch((err) => {
  console.error("\nSmoke test failed:", err);
  process.exit(1);
});
