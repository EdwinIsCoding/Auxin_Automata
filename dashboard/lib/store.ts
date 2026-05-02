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

// ── Financial Intelligence types (mirroring Python SDK) ───────────────────────

export interface RiskBreakdown {
  category: string;
  score: number;
  weight: number;
  factors: string[];
}

export interface RiskReport {
  overall_score: number;
  grade: string;
  breakdown: RiskBreakdown[];
  trend: "improving" | "stable" | "declining";
  trend_data: { date: string; score: number }[];
  computed_at: string;
}

export interface BudgetAllocation {
  inference: number;
  reserve: number;
  buffer: number;
}

export interface RecommendedAction {
  action: string;
  priority: "low" | "medium" | "high" | "critical";
  reasoning: string;
  auto_executable: boolean;
}

export interface TreasuryAnalysis {
  burn_rate_lamports_per_hour: number;
  runway_hours: number;
  runway_status: "healthy" | "warning" | "critical";
  budget_allocation: BudgetAllocation;
  recommended_actions: RecommendedAction[];
  anomaly_flags: string[];
  summary: string;
  risk_score_context: number | null;
  analyzed_at: string;
  used_fallback: boolean;
}

export interface InvoiceMeta {
  invoice_id: string;
  period_start: string;
  period_end: string;
  total_sol: number;
  total_transactions: number;
  pdf_path: string;
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

  // Financial Intelligence
  riskReport: RiskReport | null;
  treasuryAnalysis: TreasuryAnalysis | null;
  latestInvoiceMeta: InvoiceMeta | null;

  setTelemetry: (frame: TelemetryFrame) => void;
  addPayment: (payment: PaymentEvent) => void;
  addComplianceLog: (log: ComplianceLog) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setWsStatus: (status: WsStatus) => void;

  // Financial Intelligence setters
  setRiskReport: (report: RiskReport) => void;
  setTreasuryAnalysis: (analysis: TreasuryAnalysis) => void;
  setLatestInvoiceMeta: (meta: InvoiceMeta) => void;
}

export const useAuxinStore = create<AuxinStore>((set) => ({
  telemetry: null,
  payments: [],
  complianceLogs: [],
  isLoading: true,
  error: null,
  wsStatus: "connecting",

  // Financial Intelligence initial state
  riskReport: null,
  treasuryAnalysis: null,
  latestInvoiceMeta: null,

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

  // Financial Intelligence
  setRiskReport: (riskReport) => set({ riskReport }),
  setTreasuryAnalysis: (treasuryAnalysis) => set({ treasuryAnalysis }),
  setLatestInvoiceMeta: (latestInvoiceMeta) => set({ latestInvoiceMeta }),
}));
