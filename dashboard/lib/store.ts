import { create } from "zustand";

export interface JointData {
  name: string;
  angle: number;
  torque: number;
  history: { t: number; angle: number; torque: number }[];
}

export interface TelemetryFrame {
  timestamp: number;
  joints: JointData[];
  hasAnomaly: boolean;
  anomalyJoint?: string;
}

export interface PaymentEvent {
  id: string;
  timestamp: number;
  lamports: number;
  providerPubkey: string;
  txSignature: string;
  /** True when payment was routed through a privacy provider (e.g. Cloak). */
  isPrivate: boolean;
  /** Name of the privacy provider: "direct", "cloak", etc. */
  privacyProvider: string;
}

export interface ComplianceLog {
  id: string;
  timestamp: number;
  severity: 0 | 1 | 2 | 3;
  reasonCode: string;
  hash: string;
  txSignature: string;
}

export type WsStatus = "connecting" | "live" | "disconnected";

interface AuxinStore {
  telemetry: TelemetryFrame | null;
  payments: PaymentEvent[];
  complianceLogs: ComplianceLog[];
  isLoading: boolean;
  error: string | null;
  /** Reflects the current bridge WebSocket connection state. */
  wsStatus: WsStatus;

  setTelemetry: (frame: TelemetryFrame) => void;
  addPayment: (payment: PaymentEvent) => void;
  addComplianceLog: (log: ComplianceLog) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setWsStatus: (status: WsStatus) => void;
}

export const useAuxinStore = create<AuxinStore>((set) => ({
  telemetry: null,
  payments: [],
  complianceLogs: [],
  isLoading: true,
  error: null,
  wsStatus: "connecting",

  setTelemetry: (frame) => set({ telemetry: frame }),

  addPayment: (payment) =>
    set((state) => ({
      payments: [payment, ...state.payments].slice(0, 50),
    })),

  addComplianceLog: (log) =>
    set((state) => ({
      complianceLogs: [log, ...state.complianceLogs].slice(0, 100),
    })),

  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
  setWsStatus: (wsStatus) => set({ wsStatus }),
}));
