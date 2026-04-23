import {
  useAuxinStore,
  type JointData,
  type TelemetryFrame,
  type PaymentEvent,
  type ComplianceLog,
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

  return () => {
    clearInterval(telemetryInterval);
    clearInterval(paymentInterval);
    clearInterval(complianceInterval);
  };
}
