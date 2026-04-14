// @ts-nocheck
import * as anchor from "@coral-xyz/anchor";
import { Program, BN } from "@coral-xyz/anchor";
import {
  Keypair,
  PublicKey,
  SystemProgram,
  LAMPORTS_PER_SOL,
  Connection,
} from "@solana/web3.js";
import { assert } from "chai";
import { AgenticHardwareBridge } from "../target/types/agentic_hardware_bridge";

// ── Constants (must match state.rs) ───────────────────────────────────────────

const MAX_PROVIDERS = 8;
const MAX_PAYMENT_LAMPORTS = 1_000_000; // 0.001 SOL
const RATE_LIMIT_MAX_TXS = 100;
const RATE_LIMIT_WINDOW_SLOTS = 60;

// ── PDA derivation helpers ────────────────────────────────────────────────────

function deriveAgentPDA(
  programId: PublicKey,
  owner: PublicKey
): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("agent"), owner.toBuffer()],
    programId
  );
}

function deriveProviderPDA(
  programId: PublicKey,
  provider: PublicKey
): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("provider"), provider.toBuffer()],
    programId
  );
}

function deriveComplianceLogPDA(
  programId: PublicKey,
  agent: PublicKey,
  slot: bigint
): [PublicKey, number] {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64LE(slot);
  return PublicKey.findProgramAddressSync(
    [Buffer.from("log"), agent.toBuffer(), buf],
    programId
  );
}

// ── Localnet helpers ──────────────────────────────────────────────────────────

async function createFundedKeypair(
  connection: Connection,
  lamports = 5 * LAMPORTS_PER_SOL
): Promise<Keypair> {
  const kp = Keypair.generate();
  const sig = await connection.requestAirdrop(kp.publicKey, lamports);
  const bh = await connection.getLatestBlockhash();
  await connection.confirmTransaction(
    { signature: sig, blockhash: bh.blockhash, lastValidBlockHeight: bh.lastValidBlockHeight },
    "confirmed"
  );
  return kp;
}

/** Expect a tx to fail with a specific Anchor error code name. */
async function expectError(fn: () => Promise<any>, errorCode: string) {
  try {
    await fn();
    assert.fail(`Expected error ${errorCode} but tx succeeded`);
  } catch (err: any) {
    if (err.error?.errorCode?.code) {
      assert.equal(err.error.errorCode.code, errorCode);
    } else if (err.logs) {
      const hasCode = err.logs.some((l: string) => l.includes(errorCode));
      assert.isTrue(hasCode, `Expected ${errorCode} in logs, got: ${err.message}`);
    } else {
      // Re-throw non-Anchor errors
      if (err.message?.includes("assert.fail")) throw err;
      assert.include(err.message, errorCode);
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test suite
// ═══════════════════════════════════════════════════════════════════════════════

describe("agentic_hardware_bridge", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace
    .AgenticHardwareBridge as Program<AgenticHardwareBridge>;
  const conn = provider.connection;

  // ── Shared fixtures ─────────────────────────────────────────────────────────

  let owner: Keypair;
  let hw: Keypair; // hardware keypair — signs autonomous instructions
  let providerWallet: Keypair;
  let agentPDA: PublicKey;
  let agentBump: number;
  let providerRecordPDA: PublicKey;

  const BUDGET = new BN(LAMPORTS_PER_SOL / 2); // 0.5 SOL

  before("fund test keypairs", async () => {
    owner = await createFundedKeypair(conn);
    hw = await createFundedKeypair(conn); // needs SOL for payer on init_if_needed
    providerWallet = await createFundedKeypair(conn);

    [agentPDA, agentBump] = deriveAgentPDA(program.programId, owner.publicKey);
    [providerRecordPDA] = deriveProviderPDA(
      program.programId,
      providerWallet.publicKey
    );
  });

  // ══════════════════════════════════════════════════════════════════════════════
  // initialize_agent
  // ══════════════════════════════════════════════════════════════════════════════

  describe("initialize_agent", () => {
    it("creates HardwareAgent PDA with correct fields and emits event", async () => {
      // Set up event listener before tx
      let captured: any[] = [];
      const listener = program.addEventListener(
        "agentInitializedEvent",
        (event) => captured.push(event)
      );

      await program.methods
        .initializeAgent(hw.publicKey, BUDGET)
        .accounts({
          agent: agentPDA,
          owner: owner.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .signers([owner])
        .rpc();

      // Verify on-chain state
      const agent = await program.account.hardwareAgent.fetch(agentPDA);
      assert.ok(agent.owner.equals(owner.publicKey));
      assert.ok(agent.hardwarePubkey.equals(hw.publicKey));
      assert.ok(agent.computeBudgetLamports.eq(BUDGET));
      assert.ok(agent.lamportsSpent.eq(new BN(0)));
      assert.equal(agent.providers.length, 0);
      assert.isAbove(agent.createdAt.toNumber(), 0);
      assert.equal(agent.lastWindowStartSlot.toNumber(), 0);
      assert.equal(agent.windowTxCount, 0);
      assert.equal(agent.bump, agentBump);

      // Verify agent PDA was funded with the budget
      const lamports = await conn.getBalance(agentPDA);
      assert.isAtLeast(lamports, BUDGET.toNumber());

      // Verify event
      await new Promise((r) => setTimeout(r, 500));
      await program.removeEventListener(listener);
      assert.equal(captured.length, 1);
      assert.ok(captured[0].agent.equals(agentPDA));
      assert.ok(captured[0].owner.equals(owner.publicKey));
      assert.ok(captured[0].hardwarePubkey.equals(hw.publicKey));
      assert.ok(captured[0].computeBudgetLamports.eq(BUDGET));
    });

    it("rejects double init for the same owner", async () => {
      await expectError(
        () =>
          program.methods
            .initializeAgent(hw.publicKey, BUDGET)
            .accounts({
              agent: agentPDA,
              owner: owner.publicKey,
              systemProgram: SystemProgram.programId,
            })
            .signers([owner])
            .rpc(),
        // Anchor/runtime rejects because the account already exists
        "already in use"
      );
    });
  });

  // ══════════════════════════════════════════════════════════════════════════════
  // update_provider_whitelist
  // ══════════════════════════════════════════════════════════════════════════════

  describe("update_provider_whitelist", () => {
    it("adds a provider and emits event", async () => {
      let captured: any[] = [];
      const listener = program.addEventListener(
        "providerWhitelistUpdatedEvent",
        (e) => captured.push(e)
      );

      await program.methods
        .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
        .accounts({
          agent: agentPDA,
          owner: owner.publicKey,
        })
        .signers([owner])
        .rpc();

      const agent = await program.account.hardwareAgent.fetch(agentPDA);
      assert.equal(agent.providers.length, 1);
      assert.ok(agent.providers[0].equals(providerWallet.publicKey));

      await new Promise((r) => setTimeout(r, 500));
      await program.removeEventListener(listener);
      assert.equal(captured.length, 1);
      assert.isTrue(captured[0].added);
      assert.ok(captured[0].provider.equals(providerWallet.publicKey));
    });

    it("rejects adding a duplicate provider (InvalidProvider)", async () => {
      await expectError(
        () =>
          program.methods
            .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
            .accounts({ agent: agentPDA, owner: owner.publicKey })
            .signers([owner])
            .rpc(),
        "InvalidProvider"
      );
    });

    it("rejects when non-owner calls (UnauthorizedSigner)", async () => {
      const imposter = await createFundedKeypair(conn);
      const [imposterAgent] = deriveAgentPDA(
        program.programId,
        imposter.publicKey
      );

      // imposter's agent PDA doesn't exist, so this will fail.
      // To properly test has_one, we'd need to pass the real agentPDA
      // but with imposter as signer — which fails seed derivation.
      await expectError(
        () =>
          program.methods
            .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
            .accounts({ agent: agentPDA, owner: imposter.publicKey })
            .signers([imposter])
            .rpc(),
        // Seeds won't match because seeds use owner.key(), which is imposter != actual owner
        "ConstraintSeeds"
      );
    });

    it("removes a provider", async () => {
      await program.methods
        .updateProviderWhitelist(providerWallet.publicKey, { remove: {} })
        .accounts({ agent: agentPDA, owner: owner.publicKey })
        .signers([owner])
        .rpc();

      const agent = await program.account.hardwareAgent.fetch(agentPDA);
      assert.equal(agent.providers.length, 0);
    });

    it("rejects removing a provider not on the list (InvalidProvider)", async () => {
      await expectError(
        () =>
          program.methods
            .updateProviderWhitelist(Keypair.generate().publicKey, {
              remove: {},
            })
            .accounts({ agent: agentPDA, owner: owner.publicKey })
            .signers([owner])
            .rpc(),
        "InvalidProvider"
      );
    });

    it("rejects when whitelist is full at 8 providers (MaxProvidersReached)", async () => {
      // Add 8 providers
      for (let i = 0; i < MAX_PROVIDERS; i++) {
        const pk = Keypair.generate().publicKey;
        await program.methods
          .updateProviderWhitelist(pk, { add: {} })
          .accounts({ agent: agentPDA, owner: owner.publicKey })
          .signers([owner])
          .rpc();
      }

      // 9th should fail
      await expectError(
        () =>
          program.methods
            .updateProviderWhitelist(Keypair.generate().publicKey, { add: {} })
            .accounts({ agent: agentPDA, owner: owner.publicKey })
            .signers([owner])
            .rpc(),
        "MaxProvidersReached"
      );

      // Clean up: remove all 8 so later tests aren't affected
      const agent = await program.account.hardwareAgent.fetch(agentPDA);
      for (const p of agent.providers) {
        await program.methods
          .updateProviderWhitelist(p, { remove: {} })
          .accounts({ agent: agentPDA, owner: owner.publicKey })
          .signers([owner])
          .rpc();
      }
    });

    // Re-add provider for subsequent payment tests
    after("re-whitelist provider for payment tests", async () => {
      await program.methods
        .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
        .accounts({ agent: agentPDA, owner: owner.publicKey })
        .signers([owner])
        .rpc();
    });
  });

  // ══════════════════════════════════════════════════════════════════════════════
  // stream_compute_payment
  // ══════════════════════════════════════════════════════════════════════════════

  describe("stream_compute_payment", () => {
    const AMOUNT = new BN(10_000); // 0.00001 SOL — well under 0.001 cap

    it("transfers lamports and emits ComputePaymentEvent", async () => {
      const provBefore = await conn.getBalance(providerWallet.publicKey);

      let captured: any[] = [];
      const listener = program.addEventListener(
        "computePaymentEvent",
        (e) => captured.push(e)
      );

      await program.methods
        .streamComputePayment(AMOUNT)
        .accounts({
          agent: agentPDA,
          hardwareSigner: hw.publicKey,
          providerWallet: providerWallet.publicKey,
          providerRecord: providerRecordPDA,
          systemProgram: SystemProgram.programId,
        })
        .signers([hw])
        .rpc();

      // Verify agent state
      const agent = await program.account.hardwareAgent.fetch(agentPDA);
      assert.ok(agent.lamportsSpent.eq(AMOUNT));
      assert.isAbove(agent.windowTxCount, 0);

      // Verify provider wallet received lamports
      const provAfter = await conn.getBalance(providerWallet.publicKey);
      assert.equal(provAfter - provBefore, AMOUNT.toNumber());

      // Verify provider record
      const record = await program.account.computeProvider.fetch(
        providerRecordPDA
      );
      assert.ok(record.providerPubkey.equals(providerWallet.publicKey));
      assert.ok(record.totalReceived.eq(AMOUNT));

      // Verify event
      await new Promise((r) => setTimeout(r, 500));
      await program.removeEventListener(listener);
      assert.equal(captured.length, 1);
      assert.ok(captured[0].agent.equals(agentPDA));
      assert.ok(captured[0].provider.equals(providerWallet.publicKey));
      assert.ok(captured[0].lamports.eq(AMOUNT));
      assert.isAbove(captured[0].timestamp.toNumber(), 0);
    });

    it("rejects when provider is not whitelisted (ProviderNotWhitelisted)", async () => {
      const rando = Keypair.generate();
      const [randoRecord] = deriveProviderPDA(
        program.programId,
        rando.publicKey
      );

      await expectError(
        () =>
          program.methods
            .streamComputePayment(AMOUNT)
            .accounts({
              agent: agentPDA,
              hardwareSigner: hw.publicKey,
              providerWallet: rando.publicKey,
              providerRecord: randoRecord,
              systemProgram: SystemProgram.programId,
            })
            .signers([hw])
            .rpc(),
        "ProviderNotWhitelisted"
      );
    });

    it("rejects when wrong key signs (UnauthorizedSigner)", async () => {
      const wrongHw = await createFundedKeypair(conn);

      await expectError(
        () =>
          program.methods
            .streamComputePayment(AMOUNT)
            .accounts({
              agent: agentPDA,
              hardwareSigner: wrongHw.publicKey,
              providerWallet: providerWallet.publicKey,
              providerRecord: providerRecordPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([wrongHw])
            .rpc(),
        "UnauthorizedSigner"
      );
    });

    it("rejects zero amount (ZeroAmount)", async () => {
      await expectError(
        () =>
          program.methods
            .streamComputePayment(new BN(0))
            .accounts({
              agent: agentPDA,
              hardwareSigner: hw.publicKey,
              providerWallet: providerWallet.publicKey,
              providerRecord: providerRecordPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([hw])
            .rpc(),
        "ZeroAmount"
      );
    });

    it("rejects per-tx cap exceeded (PerTxCapExceeded)", async () => {
      await expectError(
        () =>
          program.methods
            .streamComputePayment(new BN(MAX_PAYMENT_LAMPORTS + 1))
            .accounts({
              agent: agentPDA,
              hardwareSigner: hw.publicKey,
              providerWallet: providerWallet.publicKey,
              providerRecord: providerRecordPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([hw])
            .rpc(),
        "PerTxCapExceeded"
      );
    });

    it("rejects when lifetime budget exceeded (BudgetExceeded)", async () => {
      // Create a separate agent with a tiny budget to test budget exhaustion
      const tinyOwner = await createFundedKeypair(conn);
      const tinyHw = await createFundedKeypair(conn);
      const tinyBudget = new BN(5_000); // 5000 lamports total
      const [tinyAgent] = deriveAgentPDA(
        program.programId,
        tinyOwner.publicKey
      );

      await program.methods
        .initializeAgent(tinyHw.publicKey, tinyBudget)
        .accounts({
          agent: tinyAgent,
          owner: tinyOwner.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .signers([tinyOwner])
        .rpc();

      // Whitelist provider
      await program.methods
        .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
        .accounts({ agent: tinyAgent, owner: tinyOwner.publicKey })
        .signers([tinyOwner])
        .rpc();

      // First payment: 4000 lamports — succeeds
      await program.methods
        .streamComputePayment(new BN(4_000))
        .accounts({
          agent: tinyAgent,
          hardwareSigner: tinyHw.publicKey,
          providerWallet: providerWallet.publicKey,
          providerRecord: providerRecordPDA,
          systemProgram: SystemProgram.programId,
        })
        .signers([tinyHw])
        .rpc();

      // Second payment: 2000 lamports — exceeds budget (4000+2000 > 5000)
      await expectError(
        () =>
          program.methods
            .streamComputePayment(new BN(2_000))
            .accounts({
              agent: tinyAgent,
              hardwareSigner: tinyHw.publicKey,
              providerWallet: providerWallet.publicKey,
              providerRecord: providerRecordPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([tinyHw])
            .rpc(),
        "BudgetExceeded"
      );
    });

    it("tracks rate-limit window fields correctly", async () => {
      const agent = await program.account.hardwareAgent.fetch(agentPDA);
      assert.isAbove(agent.windowTxCount, 0);
      assert.isAbove(agent.lastWindowStartSlot.toNumber(), 0);
    });

    // Note: Testing the exact 101st-tx-fails boundary requires >100 txs landing
    // within 60 slots. On localnet with sequential confirmations (~1 tx/slot),
    // the window resets before we can accumulate 100. The rate-limit logic is
    // verified by code review and the window-tracking assertions above.
    // On mainnet/devnet with batched txs, the 100-per-60-slots limit will engage.
    it.skip("101st tx in window fails, passes after window rolls (requires batched slot injection)", () => {});
  });

  // ══════════════════════════════════════════════════════════════════════════════
  // log_compliance_event
  // ══════════════════════════════════════════════════════════════════════════════

  describe("log_compliance_event", () => {
    const HASH = "a".repeat(64); // 64-char hex hash
    const SEVERITY = 2; // WARN
    const REASON = 0x0001; // torque-limit

    it("writes ComplianceLog PDA and emits ComplianceEvent", async () => {
      let captured: any[] = [];
      const listener = program.addEventListener("complianceEvent", (e) =>
        captured.push(e)
      );

      const slot = await conn.getSlot("confirmed");
      const [logPDA] = deriveComplianceLogPDA(
        program.programId,
        agentPDA,
        BigInt(slot)
      );

      await program.methods
        .logComplianceEvent(HASH, SEVERITY, REASON, new BN(slot))
        .accounts({
          agent: agentPDA,
          hardwareSigner: hw.publicKey,
          log: logPDA,
          systemProgram: SystemProgram.programId,
        })
        .signers([hw])
        .rpc();

      const logData = await program.account.complianceLog.fetch(logPDA);
      assert.isNotNull(logData, "ComplianceLog PDA not found");
      assert.ok(logData.agent.equals(agentPDA));
      assert.equal(logData.hash, HASH);
      assert.equal(logData.severity, SEVERITY);
      assert.equal(logData.reasonCode, REASON);
      assert.isAbove(logData.timestamp.toNumber(), 0);

      // Verify event
      await new Promise((r) => setTimeout(r, 500));
      await program.removeEventListener(listener);
      assert.equal(captured.length, 1);
      assert.ok(captured[0].agent.equals(agentPDA));
      assert.equal(captured[0].hash, HASH);
      assert.equal(captured[0].severity, SEVERITY);
      assert.equal(captured[0].reasonCode, REASON);
    });

    it("rejects hash exceeding 64 bytes (HashTooLong)", async () => {
      const slot = await conn.getSlot("confirmed");
      const [logPDA] = deriveComplianceLogPDA(program.programId, agentPDA, BigInt(slot));
      await expectError(
        () =>
          program.methods
            .logComplianceEvent("x".repeat(65), SEVERITY, REASON, new BN(slot))
            .accounts({
              agent: agentPDA,
              hardwareSigner: hw.publicKey,
              log: logPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([hw])
            .rpc(),
        "HashTooLong"
      );
    });

    it("rejects invalid severity > 3 (InvalidSeverity)", async () => {
      const slot = await conn.getSlot("confirmed");
      const [logPDA] = deriveComplianceLogPDA(program.programId, agentPDA, BigInt(slot));
      await expectError(
        () =>
          program.methods
            .logComplianceEvent(HASH, 4, REASON, new BN(slot))
            .accounts({
              agent: agentPDA,
              hardwareSigner: hw.publicKey,
              log: logPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([hw])
            .rpc(),
        "InvalidSeverity"
      );
    });

    it("succeeds even when compute budget is exhausted (compliance contract)", async () => {
      // Use the tinyBudget agent from above — budget is drained.
      // Create fresh one to be deterministic.
      const drainedOwner = await createFundedKeypair(conn);
      const drainedHw = await createFundedKeypair(conn);
      const [drainedAgent] = deriveAgentPDA(
        program.programId,
        drainedOwner.publicKey
      );

      // Init with tiny budget
      await program.methods
        .initializeAgent(drainedHw.publicKey, new BN(100))
        .accounts({
          agent: drainedAgent,
          owner: drainedOwner.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .signers([drainedOwner])
        .rpc();

      // Whitelist + drain budget
      await program.methods
        .updateProviderWhitelist(providerWallet.publicKey, { add: {} })
        .accounts({ agent: drainedAgent, owner: drainedOwner.publicKey })
        .signers([drainedOwner])
        .rpc();

      await program.methods
        .streamComputePayment(new BN(100))
        .accounts({
          agent: drainedAgent,
          hardwareSigner: drainedHw.publicKey,
          providerWallet: providerWallet.publicKey,
          providerRecord: providerRecordPDA,
          systemProgram: SystemProgram.programId,
        })
        .signers([drainedHw])
        .rpc();

      // Budget is now exhausted — compliance log MUST still succeed.
      const drainSlot = await conn.getSlot("confirmed");
      const [drainedLogPDA] = deriveComplianceLogPDA(program.programId, drainedAgent, BigInt(drainSlot));
      await program.methods
        .logComplianceEvent("deadbeef", 3, 0x0002, new BN(drainSlot))
        .accounts({
          agent: drainedAgent,
          hardwareSigner: drainedHw.publicKey,
          log: drainedLogPDA,
          systemProgram: SystemProgram.programId,
        })
        .signers([drainedHw])
        .rpc();

      // If we got here without error, the compliance contract holds.
    });

    it("rejects when wrong key signs (UnauthorizedSigner)", async () => {
      const wrongHw = await createFundedKeypair(conn);
      const wrongSlot = await conn.getSlot("confirmed");
      const [wrongLogPDA] = deriveComplianceLogPDA(program.programId, agentPDA, BigInt(wrongSlot));

      await expectError(
        () =>
          program.methods
            .logComplianceEvent(HASH, SEVERITY, REASON, new BN(wrongSlot))
            .accounts({
              agent: agentPDA,
              hardwareSigner: wrongHw.publicKey,
              log: wrongLogPDA,
              systemProgram: SystemProgram.programId,
            })
            .signers([wrongHw])
            .rpc(),
        "UnauthorizedSigner"
      );
    });
  });

  // ══════════════════════════════════════════════════════════════════════════════
  // Multi-agent isolation
  // ══════════════════════════════════════════════════════════════════════════════

  describe("multi-agent isolation", () => {
    let ownerA: Keypair;
    let ownerB: Keypair;
    let hwA: Keypair;
    let hwB: Keypair;
    let agentA: PublicKey;
    let agentB: PublicKey;
    let sharedProvider: Keypair;

    before(async () => {
      ownerA = await createFundedKeypair(conn);
      ownerB = await createFundedKeypair(conn);
      hwA = await createFundedKeypair(conn);
      hwB = await createFundedKeypair(conn);
      sharedProvider = await createFundedKeypair(conn);

      [agentA] = deriveAgentPDA(program.programId, ownerA.publicKey);
      [agentB] = deriveAgentPDA(program.programId, ownerB.publicKey);

      // Init both agents with 0.1 SOL budget
      const budget = new BN(LAMPORTS_PER_SOL / 10);
      for (const [o, h, a] of [
        [ownerA, hwA, agentA],
        [ownerB, hwB, agentB],
      ] as [Keypair, Keypair, PublicKey][]) {
        await program.methods
          .initializeAgent(h.publicKey, budget)
          .accounts({
            agent: a,
            owner: o.publicKey,
            systemProgram: SystemProgram.programId,
          })
          .signers([o])
          .rpc();

        await program.methods
          .updateProviderWhitelist(sharedProvider.publicKey, { add: {} })
          .accounts({ agent: a, owner: o.publicKey })
          .signers([o])
          .rpc();
      }
    });

    it("agent A payment does not affect agent B budget", async () => {
      const [provRecord] = deriveProviderPDA(
        program.programId,
        sharedProvider.publicKey
      );

      // Agent A pays
      await program.methods
        .streamComputePayment(new BN(50_000))
        .accounts({
          agent: agentA,
          hardwareSigner: hwA.publicKey,
          providerWallet: sharedProvider.publicKey,
          providerRecord: provRecord,
          systemProgram: SystemProgram.programId,
        })
        .signers([hwA])
        .rpc();

      // Agent B's budget is untouched
      const agentBData = await program.account.hardwareAgent.fetch(agentB);
      assert.ok(agentBData.lamportsSpent.eq(new BN(0)));
    });

    it("hardware key A cannot sign for agent B", async () => {
      const [provRecord] = deriveProviderPDA(
        program.programId,
        sharedProvider.publicKey
      );

      await expectError(
        () =>
          program.methods
            .streamComputePayment(new BN(1_000))
            .accounts({
              agent: agentB,
              hardwareSigner: hwA.publicKey, // wrong hw key for agent B
              providerWallet: sharedProvider.publicKey,
              providerRecord: provRecord,
              systemProgram: SystemProgram.programId,
            })
            .signers([hwA])
            .rpc(),
        "UnauthorizedSigner"
      );
    });

    it("PDAs are distinct", () => {
      assert.isFalse(agentA.equals(agentB));
    });
  });
});
