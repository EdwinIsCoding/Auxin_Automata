/**
 * lib/anchor.ts
 * -------------
 * Event parsing utilities for the agentic_hardware_bridge Anchor program.
 *
 * Uses a minimal inline Borsh reader instead of importing the full
 * @coral-xyz/anchor package — avoids Node.js-only module issues in Next.js
 * browser bundles while still doing proper binary event decoding.
 *
 * IDL is loaded from lib/idl/agentic_hardware_bridge.json (copied from
 * /programs/target/idl/ after `anchor build`).
 *
 * Event discriminators come from the IDL's `events[].discriminator` arrays.
 * They are sha256("event:<EventName>")[0..8] truncated, pre-computed by Anchor.
 */

import { PublicKey } from "@solana/web3.js";
import type { PaymentEvent, ComplianceLog } from "./store";

// ── Event discriminators (from IDL events[].discriminator) ────────────────────
// ComplianceEvent      — [91, 66, 46, 200, 143, 43, 176, 16]
// ComputePaymentEvent  — [223, 238, 225, 41, 255, 173, 246, 1]

const COMPLIANCE_DISC = new Uint8Array([91, 66, 46, 200, 143, 43, 176, 16]);
const PAYMENT_DISC    = new Uint8Array([223, 238, 225, 41, 255, 173, 246, 1]);

// ── Borsh reader ──────────────────────────────────────────────────────────────

class BorshReader {
  private readonly dv: DataView;
  private pos = 0;

  constructor(buf: ArrayBuffer) {
    this.dv = new DataView(buf);
  }

  u8(): number {
    return this.dv.getUint8(this.pos++);
  }

  u16(): number {
    const v = this.dv.getUint16(this.pos, true);
    this.pos += 2;
    return v;
  }

  /** Returns a safe JS number (loses precision above 2^53, fine for lamports). */
  u64(): number {
    const v = this.dv.getBigUint64(this.pos, true);
    this.pos += 8;
    return Number(v);
  }

  /** Returns seconds as a JS number. */
  i64(): number {
    const v = this.dv.getBigInt64(this.pos, true);
    this.pos += 8;
    return Number(v);
  }

  pubkey(): string {
    const bytes = new Uint8Array(
      this.dv.buffer,
      this.dv.byteOffset + this.pos,
      32,
    );
    this.pos += 32;
    return new PublicKey(bytes).toBase58();
  }

  string(): string {
    const len = this.dv.getUint32(this.pos, true);
    this.pos += 4;
    const bytes = new Uint8Array(
      this.dv.buffer,
      this.dv.byteOffset + this.pos,
      len,
    );
    this.pos += len;
    return new TextDecoder().decode(bytes);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function discMatch(buf: Uint8Array, disc: Uint8Array): boolean {
  for (let i = 0; i < 8; i++) {
    if (buf[i] !== disc[i]) return false;
  }
  return true;
}

const REASON_LABELS: Record<number, string> = {
  0x0001: "ANOMALY_DETECTED",
  0x0002: "ORACLE_DENIED",
};

// ── Public API ────────────────────────────────────────────────────────────────

type DecodedEvent =
  | { type: "payment"; event: PaymentEvent }
  | { type: "compliance"; event: ComplianceLog };

/**
 * Attempts to decode one Anchor event from a single log line.
 *
 * Anchor emits events as "Program data: <base64>" lines.
 * The encoded bytes are: 8-byte discriminator || borsh-serialised fields.
 *
 * Returns null if:
 *  - the line is not a "Program data:" entry
 *  - the discriminator doesn't match a known event
 *  - the payload is malformed (caught and swallowed)
 */
export function tryDecodeEvent(
  logLine: string,
  signature: string,
): DecodedEvent | null {
  const match = logLine.match(/^Program data:\s+(.+)$/);
  if (!match) return null;

  let buf: ArrayBuffer;
  try {
    const b64 = match[1].trim();
    // atob is available in all modern browsers and in Next.js edge/browser context
    const binary = atob(b64);
    buf = new ArrayBuffer(binary.length);
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  } catch {
    return null;
  }

  if (buf.byteLength < 8) return null;

  const prefix = new Uint8Array(buf, 0, 8);
  const payload = buf.slice(8);

  try {
    // ── ComputePaymentEvent ─────────────────────────────────────────────────
    // fields: agent (pubkey), provider (pubkey), lamports (u64), timestamp (i64)
    if (discMatch(prefix, PAYMENT_DISC)) {
      const r = new BorshReader(payload);
      r.pubkey(); // agent — consumed, not used in UI
      const provider  = r.pubkey();
      const lamports  = r.u64();
      const tsSeconds = r.i64();
      const event: PaymentEvent = {
        id:             signature.slice(0, 16),
        timestamp:      tsSeconds * 1_000,
        lamports,
        providerPubkey: provider,
        txSignature:    signature,
      };
      return { type: "payment", event };
    }

    // ── ComplianceEvent ─────────────────────────────────────────────────────
    // fields: agent (pubkey), hash (string), severity (u8), reason_code (u16), timestamp (i64)
    if (discMatch(prefix, COMPLIANCE_DISC)) {
      const r = new BorshReader(payload);
      r.pubkey(); // agent — consumed, not used in UI
      const hash       = r.string();
      const severity   = Math.min(r.u8(), 3) as 0 | 1 | 2 | 3;
      const reasonCode = r.u16();
      const tsSeconds  = r.i64();
      const event: ComplianceLog = {
        id:          signature.slice(0, 16),
        timestamp:   tsSeconds * 1_000,
        severity,
        reasonCode:  REASON_LABELS[reasonCode] ?? `0x${reasonCode.toString(16).toUpperCase().padStart(4, "0")}`,
        hash,
        txSignature: signature,
      };
      return { type: "compliance", event };
    }
  } catch {
    // Malformed payload — silently ignore
  }

  return null;
}
