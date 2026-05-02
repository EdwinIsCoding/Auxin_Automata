import {
  useAuxinStore,
  type JointData,
  type TelemetryFrame,
  type PaymentEvent,
  type ComplianceLog,
  type RiskReport,
  type TreasuryAnalysis,
} from "./store";

const JOINT_NAMES = ["J1", "J2", "J3", "J4", "J5", "J6", "J7"];

const PROVIDER_PUBKEYS = [
  "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
  "3FoUAsGDbvTD6YZ73HCPkj5RCyTuGCPVhERhE3dPbsfn",
  "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  "So11111111111111111111111111111111111111112",
];

const REASON_CODES = [
  "TORQUE_LIMIT_EXCEEDED",
  "VELOCITY_BOUND_BREACH",
  "WORKSPACE_VIOLATION",
  "EMERGENCY_STOP_TRIGGERED",
  "CHECKSUM_MISMATCH",
  "HEARTBEAT_TIMEOUT",
];

function randomBetween(min: number, max: number) {
  return Math.random() * (max - min) + min;
}

function randomChoice<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function randomHex(length: number): string {
  return Array.from({ length }, () =>
    Math.floor(Math.random() * 16).toString(16)
  ).join("");
}

function randomBase58(length: number): string {
  const chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  return Array.from({ length }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

let jointHistories: { angle: number; torque: number }[][] = JOINT_NAMES.map(
  () =>
    Array.from({ length: 20 }, () => ({
      angle: randomBetween(-90, 90),
      torque: randomBetween(-30, 30),
    }))
);

function nextAngle(prev: number): number {
  return Math.max(-180, Math.min(180, prev + randomBetween(-3, 3)));
}

function nextTorque(prev: number): number {
  return Math.max(-50, Math.min(50, prev + randomBetween(-2, 2)));
}

export function generateTelemetryFrame(): TelemetryFrame {
  const now = Date.now();
  const anomalyJointIdx = Math.random() < 0.05 ? Math.floor(Math.random() * 7) : -1;

  const joints: JointData[] = JOINT_NAMES.map((name, i) => {
    const prev = jointHistories[i][jointHistories[i].length - 1];
    const angle = nextAngle(prev.angle);
    const torque = nextTorque(prev.torque);

    jointHistories[i] = [...jointHistories[i].slice(-19), { angle, torque }];

    return {
      name,
      angle: parseFloat(angle.toFixed(2)),
      torque: parseFloat(torque.toFixed(2)),
      history: jointHistories[i].map((h, idx) => ({
        t: idx,
        angle: parseFloat(h.angle.toFixed(2)),
        torque: parseFloat(h.torque.toFixed(2)),
      })),
    };
  });

  return {
    timestamp: now,
    joints,
    hasAnomaly: anomalyJointIdx >= 0,
    anomalyJoint: anomalyJointIdx >= 0 ? JOINT_NAMES[anomalyJointIdx] : undefined,
  };
}

export function generatePaymentEvent(): PaymentEvent {
  const isPrivate = Math.random() < 0.3;
  return {
    id: randomHex(16),
    timestamp: Date.now(),
    lamports: Math.floor(randomBetween(1_000, 50_000_000)),
    providerPubkey: randomChoice(PROVIDER_PUBKEYS),
    txSignature: randomBase58(88),
    isPrivate,
    privacyProvider: isPrivate ? "cloak" : "direct",
  };
}

export function generateComplianceLog(): ComplianceLog {
  const severity = randomChoice([0, 0, 0, 1, 1, 2, 3] as const);
  return {
    id: randomHex(16),
    timestamp: Date.now(),
    severity,
    reasonCode: randomChoice(REASON_CODES),
    hash: randomHex(64),
    txSignature: randomBase58(88),
  };
}

// ── Mock financial intelligence data ──────────────────────────────────────────

function isoAgo(daysAgo: number): string {
  const d = new Date(Date.now() - daysAgo * 86_400_000);
  return d.toISOString().slice(0, 10);
}

function generateMockRiskReport(): RiskReport {
  const score = 78 + Math.random() * 10; // ~78–88, grade A/B
  return {
    overall_score: parseFloat(score.toFixed(1)),
    grade: score >= 80 ? "A" : "B",
    breakdown: [
      { category: "Financial Health",      score: 82, weight: 0.30, factors: ["Runway 96h at current burn", "Burn rate CV=0.18 (stable)"] },
      { category: "Operational Stability", score: 79, weight: 0.25, factors: ["Payment interval CV=0.31 (regular)", "Uptime 89% (7d)"] },
      { category: "Compliance Record",     score: 91, weight: 0.25, factors: ["0.5 events per 100 tx", "No sev≥2 in 7 days"] },
      { category: "Provider Diversity",    score: 74, weight: 0.20, factors: ["3 unique providers", "HHI 0.41 (moderate)"] },
    ],
    trend: "improving",
    trend_data: Array.from({ length: 7 }, (_, i) => ({
      date: isoAgo(6 - i),
      score: parseFloat((60 + i * 3.5 + Math.random() * 4).toFixed(1)),
    })),
    computed_at: new Date().toISOString(),
  };
}

function generateMockTreasuryAnalysis(): TreasuryAnalysis {
  return {
    burn_rate_lamports_per_hour: 42_000,
    runway_hours: 85.2,
    runway_status: "healthy",
    budget_allocation: { inference: 70, reserve: 20, buffer: 10 },
    recommended_actions: [
      {
        action: "monitor_burn_rate",
        priority: "low",
        reasoning: "Burn rate stable at 42k lam/hr. No action required.",
        auto_executable: false,
      },
      {
        action: "diversify_providers",
        priority: "medium",
        reasoning: "ProviderA handles 58% of payments — consider adding a 4th provider.",
        auto_executable: false,
      },
    ],
    anomaly_flags: [],
    summary:
      "Wallet is operating normally with 85h runway. Burn rate is stable and compliance record is clean. Provider diversification could be improved.",
    risk_score_context: 83.2,
    analyzed_at: new Date().toISOString(),
    used_fallback: true,
  };
}

export function startMockDataFeed() {
  const store = useAuxinStore.getState();

  // Seed initial data
  for (let i = 0; i < 10; i++) {
    store.addPayment(generatePaymentEvent());
  }
  for (let i = 0; i < 8; i++) {
    store.addComplianceLog(generateComplianceLog());
  }
  store.setTelemetry(generateTelemetryFrame());

  // Seed financial intelligence (so dashboard shows data immediately in mock mode)
  store.setRiskReport(generateMockRiskReport());
  store.setTreasuryAnalysis(generateMockTreasuryAnalysis());

  store.setLoading(false);

  // Telemetry at ~10 Hz (100ms)
  const telemetryInterval = setInterval(() => {
    useAuxinStore.getState().setTelemetry(generateTelemetryFrame());
  }, 100);

  // Payments every 2–4 s
  const paymentInterval = setInterval(() => {
    useAuxinStore.getState().addPayment(generatePaymentEvent());
  }, randomBetween(2000, 4000));

  // Compliance logs every 5–10 s
  const complianceInterval = setInterval(() => {
    useAuxinStore.getState().addComplianceLog(generateComplianceLog());
  }, randomBetween(5000, 10000));

  // Risk report every 60 s (mirrors bridge AUXIN_RISK_INTERVAL_S default)
  const riskInterval = setInterval(() => {
    useAuxinStore.getState().setRiskReport(generateMockRiskReport());
  }, 60_000);

  // Treasury analysis every 120 s (mirrors bridge AUXIN_TREASURY_INTERVAL_S default)
  const treasuryInterval = setInterval(() => {
    useAuxinStore.getState().setTreasuryAnalysis(generateMockTreasuryAnalysis());
  }, 120_000);

  return () => {
    clearInterval(telemetryInterval);
    clearInterval(paymentInterval);
    clearInterval(complianceInterval);
    clearInterval(riskInterval);
    clearInterval(treasuryInterval);
  };
}
