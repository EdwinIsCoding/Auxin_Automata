"use client";

/**
 * useBridgeSocket
 * ---------------
 * Connects to the Python bridge WebSocket broadcaster at NEXT_PUBLIC_BRIDGE_WS_URL/ws
 * (default ws://localhost:8766/ws) and feeds incoming messages into the Zustand store.
 *
 * Message types emitted by bridge.py:
 *   { type: "telemetry",        data: PythonTelemetryFrame }
 *   { type: "compliance_event", data: BridgeComplianceEvent }
 *   { type: "payment_event",    data: BridgePaymentEvent }
 *
 * Schema adapter: converts the Python TelemetryFrame (radians, separate arrays)
 * into the TypeScript TelemetryFrame (degrees, joint objects with rolling history).
 *
 * Reconnect: exponential backoff from RECONNECT_BASE_MS up to RECONNECT_MAX_MS.
 */

import { useEffect, useRef } from "react";
import { useAuxinStore } from "./store";
import type { TelemetryFrame, JointData, PaymentEvent, ComplianceLog } from "./store";

// ── Config ────────────────────────────────────────────────────────────────────

const BASE_URL = (process.env.NEXT_PUBLIC_BRIDGE_WS_URL ?? "ws://localhost:8766").replace(/\/$/, "");
const WS_URL = `${BASE_URL}/ws`;

const RECONNECT_BASE_MS = 2_000;
const RECONNECT_MAX_MS  = 30_000;
const HISTORY_LENGTH    = 20;

const JOINT_NAMES = ["J1", "J2", "J3", "J4", "J5", "J6", "J7"];

const REASON_CODE_LABELS: Record<number, string> = {
  0x0001: "ANOMALY_DETECTED",
  0x0002: "ORACLE_DENIED",
};

// ── Python schema types (what the bridge actually sends) ──────────────────────

interface PythonTelemetryFrame {
  timestamp:       string;          // ISO 8601
  joint_positions: number[];        // radians
  joint_velocities: number[];       // rad/s
  joint_torques:   number[];        // N·m
  end_effector_pose: Record<string, number>;
  anomaly_flags:   string[];        // e.g. ["torque_spike"]
}

interface BridgeComplianceEvent {
  hash:        string;
  severity:    number;              // 0|1|2|3
  reason_code: number;              // 0x0001 | 0x0002
  signature:   string;
  flags:       string[];
  timestamp:   string;
}

interface BridgePaymentEvent {
  signature:      string;
  amount_lamports: number;
  provider:       string;
  timestamp:      string;
  oracle_reason:  string;
}

type BridgeMessage =
  | { type: "telemetry";        data: PythonTelemetryFrame }
  | { type: "compliance_event"; data: BridgeComplianceEvent }
  | { type: "payment_event";    data: BridgePaymentEvent };

// ── Rolling history buffer (persists between frames, cleared on remount) ──────

type HistoryPoint = { t: number; angle: number; torque: number };

function makeEmptyHistories(jointCount: number): HistoryPoint[][] {
  return Array.from({ length: jointCount }, () => []);
}

// ── Schema adapter ────────────────────────────────────────────────────────────

function adaptTelemetry(
  raw: PythonTelemetryFrame,
  histories: HistoryPoint[][],
  frameIndex: number,
): TelemetryFrame {
  const RAD_TO_DEG = 180 / Math.PI;
  const timestamp  = new Date(raw.timestamp).getTime();
  const hasAnomaly = raw.anomaly_flags.length > 0;

  const jointCount = Math.min(
    raw.joint_positions.length,
    raw.joint_torques.length,
    JOINT_NAMES.length,
  );

  const joints: JointData[] = Array.from({ length: jointCount }, (_, i) => {
    const angle  = parseFloat((raw.joint_positions[i] * RAD_TO_DEG).toFixed(2));
    const torque = parseFloat(raw.joint_torques[i].toFixed(2));

    // Append to rolling history, capped at HISTORY_LENGTH
    histories[i] = [
      ...histories[i].slice(-(HISTORY_LENGTH - 1)),
      { t: frameIndex, angle, torque },
    ];

    return {
      name:    JOINT_NAMES[i],
      angle,
      torque,
      history: [...histories[i]],
    };
  });

  // Best-effort: identify the anomalous joint as the one with highest |torque|
  let anomalyJoint: string | undefined;
  if (hasAnomaly) {
    const maxIdx = joints.reduce(
      (best, j, idx) => (Math.abs(j.torque) > Math.abs(joints[best].torque) ? idx : best),
      0,
    );
    anomalyJoint = joints[maxIdx].name;
  }

  return { timestamp, joints, hasAnomaly, anomalyJoint };
}

function adaptCompliance(raw: BridgeComplianceEvent): ComplianceLog {
  return {
    id:          raw.signature.slice(0, 16),
    timestamp:   new Date(raw.timestamp).getTime(),
    severity:    Math.min(raw.severity, 3) as 0 | 1 | 2 | 3,
    reasonCode:  REASON_CODE_LABELS[raw.reason_code] ?? raw.flags[0] ?? "COMPLIANCE_EVENT",
    hash:        raw.hash,
    txSignature: raw.signature,
  };
}

function adaptPayment(raw: BridgePaymentEvent): PaymentEvent {
  return {
    id:            raw.signature.slice(0, 16),
    timestamp:     new Date(raw.timestamp).getTime(),
    lamports:      raw.amount_lamports,
    providerPubkey: raw.provider,
    txSignature:   raw.signature,
  };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useBridgeSocket(): void {
  const wsRef          = useRef<WebSocket | null>(null);
  const delayRef       = useRef(RECONNECT_BASE_MS);
  const timerRef       = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef   = useRef(false);
  const frameIndexRef  = useRef(0);
  const historiesRef   = useRef<HistoryPoint[][]>(makeEmptyHistories(JOINT_NAMES.length));

  useEffect(() => {
    unmountedRef.current = false;

    function connect() {
      if (unmountedRef.current) return;

      let ws: WebSocket;
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        // Constructor threw (invalid URL or non-browser env) — retry
        timerRef.current = setTimeout(connect, delayRef.current);
        return;
      }

      wsRef.current = ws;

      ws.onopen = () => {
        delayRef.current = RECONNECT_BASE_MS;
        const s = useAuxinStore.getState();
        s.setError(null);
        s.setWsStatus("live");
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        let msg: BridgeMessage;
        try {
          msg = JSON.parse(ev.data) as BridgeMessage;
        } catch {
          return; // malformed JSON
        }

        const s = useAuxinStore.getState();

        if (msg.type === "telemetry") {
          const frame = adaptTelemetry(
            msg.data,
            historiesRef.current,
            frameIndexRef.current++,
          );
          s.setTelemetry(frame);
        } else if (msg.type === "compliance_event") {
          s.addComplianceLog(adaptCompliance(msg.data));
        } else if (msg.type === "payment_event") {
          s.addPayment(adaptPayment(msg.data));
        }
      };

      ws.onerror = () => {
        // Let onclose handle reconnect
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        wsRef.current = null;
        useAuxinStore.getState().setWsStatus("disconnected");
        const delay = delayRef.current;
        delayRef.current = Math.min(delay * 2, RECONNECT_MAX_MS);
        timerRef.current = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect loop
        wsRef.current.close();
      }
    };
  }, []);
}
