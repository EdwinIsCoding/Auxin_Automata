"use client";

import { useRef, Suspense, useEffect, useState, useCallback } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Grid, Environment } from "@react-three/drei";
import { useAuxinStore } from "@/lib/store";
import { Cpu, Wifi, WifiOff } from "lucide-react";
import type * as THREE from "three";

// ── PyBullet JPEG stream config ───────────────────────────────────────────────

const TWIN_WS_URL = (
  process.env.NEXT_PUBLIC_TWIN_WS_URL ?? "ws://localhost:8765"
).replace(/\/$/, "");

const RECONNECT_BASE_MS = 3_000;
const RECONNECT_MAX_MS  = 30_000;

type TwinStreamStatus = "connecting" | "live" | "disconnected";

/**
 * Connects to the PyBullet websocket frame server at NEXT_PUBLIC_TWIN_WS_URL.
 * The server sends base64-encoded JPEG frames as plain text messages.
 *
 * Returns the latest frame as a data-URL (or null before the first frame),
 * and the current connection status.
 */
function useTwinStream(): { frameUrl: string | null; status: TwinStreamStatus } {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<TwinStreamStatus>("connecting");
  const wsRef       = useRef<WebSocket | null>(null);
  const delayRef    = useRef(RECONNECT_BASE_MS);
  const timerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountRef  = useRef(false);

  const connect = useCallback(() => {
    if (unmountRef.current) return;

    let ws: WebSocket;
    try {
      ws = new WebSocket(TWIN_WS_URL);
    } catch {
      timerRef.current = setTimeout(connect, delayRef.current);
      return;
    }

    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      delayRef.current = RECONNECT_BASE_MS;
      setStatus("live");
    };

    ws.onmessage = (ev: MessageEvent<string>) => {
      // The PyBullet render.py server sends base64-encoded JPEG frames.
      // Each message is the raw base64 string (no JSON wrapper).
      const data = ev.data.trim();
      if (!data) return;
      setFrameUrl(`data:image/jpeg;base64,${data}`);
    };

    ws.onerror = () => {
      // Let onclose handle reconnect
    };

    ws.onclose = () => {
      if (unmountRef.current) return;
      wsRef.current = null;
      setStatus("disconnected");
      const delay = delayRef.current;
      delayRef.current = Math.min(delay * 2, RECONNECT_MAX_MS);
      timerRef.current = setTimeout(connect, delay);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    unmountRef.current = false;
    connect();
    return () => {
      unmountRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { frameUrl, status };
}

// ── 3D arm placeholder (fallback when twin ws is unavailable) ─────────────────

function ArmPlaceholder() {
  const groupRef = useRef<THREE.Group>(null);
  const telemetry = useAuxinStore((s) => s.telemetry);

  useFrame((_, delta) => {
    if (!groupRef.current) return;
    const speed = telemetry?.hasAnomaly ? 3 : 0.4;
    groupRef.current.rotation.y += delta * speed;
  });

  const joints     = telemetry?.joints ?? [];
  const hasAnomaly = telemetry?.hasAnomaly ?? false;
  const tealColor    = "#14b8a6";
  const solanaColor  = "#14F195";
  const redColor     = "#ef4444";
  const surfaceColor = "#1f2937";

  return (
    <group ref={groupRef}>
      {/* Base plate */}
      <mesh position={[0, -0.05, 0]} receiveShadow>
        <cylinderGeometry args={[0.7, 0.8, 0.1, 32]} />
        <meshStandardMaterial color={surfaceColor} metalness={0.8} roughness={0.3} />
      </mesh>

      {/* Arm segments — 7 joints */}
      {joints.slice(0, 7).map((joint, i) => {
        const isAnomalyJoint = hasAnomaly && telemetry?.anomalyJoint === joint.name;
        const normalizedAngle = (joint.angle / 180) * Math.PI * 0.2;
        const yOffset = 0.15 + i * 0.32;
        const color = isAnomalyJoint ? redColor : i % 2 === 0 ? tealColor : solanaColor;

        return (
          <group key={joint.name} position={[0, yOffset, 0]} rotation={[0, normalizedAngle, 0]}>
            <mesh castShadow>
              <sphereGeometry args={[0.08, 16, 16]} />
              <meshStandardMaterial
                color={color}
                emissive={color}
                emissiveIntensity={isAnomalyJoint ? 0.8 : 0.2}
                metalness={0.6}
                roughness={0.2}
              />
            </mesh>
            <mesh position={[0, 0.13, 0]} castShadow>
              <cylinderGeometry args={[0.025, 0.025, 0.26, 12]} />
              <meshStandardMaterial color={surfaceColor} metalness={0.9} roughness={0.2} />
            </mesh>
          </group>
        );
      })}

      {/* End effector */}
      <mesh position={[0, 0.15 + 7 * 0.32, 0]} castShadow>
        <octahedronGeometry args={[0.1]} />
        <meshStandardMaterial
          color={hasAnomaly ? redColor : solanaColor}
          emissive={hasAnomaly ? redColor : solanaColor}
          emissiveIntensity={0.5}
          metalness={0.5}
          roughness={0.1}
        />
      </mesh>
    </group>
  );
}

function SceneContent() {
  return (
    <>
      <ambientLight intensity={0.3} />
      <directionalLight position={[5, 8, 5]} intensity={1.2} castShadow />
      <pointLight position={[-3, 3, -3]} intensity={0.6} color="#14b8a6" />
      <pointLight position={[3, 1, 3]} intensity={0.4} color="#14F195" />
      <Grid
        position={[0, -0.1, 0]}
        args={[10, 10]}
        cellSize={0.5}
        cellThickness={0.5}
        cellColor="#1f2937"
        sectionSize={2}
        sectionThickness={1}
        sectionColor="#14b8a6"
        fadeDistance={8}
        fadeStrength={1}
        followCamera={false}
        infiniteGrid
      />
      <ArmPlaceholder />
      <Environment preset="night" />
      <OrbitControls
        enablePan={false}
        minDistance={2}
        maxDistance={8}
        minPolarAngle={Math.PI * 0.15}
        maxPolarAngle={Math.PI * 0.75}
      />
    </>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function TwinViewport() {
  const telemetry  = useAuxinStore((s) => s.telemetry);
  const isLoading  = useAuxinStore((s) => s.isLoading);
  const hasAnomaly = telemetry?.hasAnomaly ?? false;

  const { frameUrl, status: twinStatus } = useTwinStream();

  // Show JPEG overlay only when the twin WS is live and delivering frames
  const showJpeg = twinStatus === "live" && frameUrl !== null;

  return (
    <div
      className={`card-surface flex flex-col h-full overflow-hidden transition-all duration-500 ${
        hasAnomaly ? "glow-red-card" : ""
      }`}
    >
      {/* Header */}
      <div className="card-header-teal flex items-center justify-between px-4 py-3 shrink-0">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4" style={{ color: "#14b8a6" }} />
          <span className="text-xs font-bold tracking-[0.22em] uppercase text-gradient-purple-green">
            Digital Twin — Franka Panda
          </span>
        </div>
        <div className="flex items-center gap-3">
          {/* PyBullet stream status badge */}
          <span
            className="flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded-full font-mono tracking-wider uppercase"
            style={{
              backgroundColor:
                twinStatus === "live"
                  ? "rgba(20,241,149,0.10)"
                  : twinStatus === "connecting"
                  ? "rgba(234,179,8,0.08)"
                  : "rgba(239,68,68,0.08)",
              color:
                twinStatus === "live"
                  ? "#14F195"
                  : twinStatus === "connecting"
                  ? "#eab308"
                  : "#ef4444",
              border:
                twinStatus === "live"
                  ? "1px solid rgba(20,241,149,0.25)"
                  : twinStatus === "connecting"
                  ? "1px solid rgba(234,179,8,0.25)"
                  : "1px solid rgba(239,68,68,0.25)",
            }}
          >
            {twinStatus === "live" ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {twinStatus === "live" ? "PyBullet Live" : twinStatus === "connecting" ? "PyBullet…" : "3D Mode"}
          </span>

          {isLoading && (
            <span className="text-[10px] tracking-wider" style={{ color: "#3d4663" }}>
              connecting…
            </span>
          )}
        </div>
      </div>

      {/* Viewport */}
      <div className="relative flex-1 min-h-[280px]">
        {/* ── PyBullet JPEG stream overlay ── */}
        {showJpeg ? (
          <div className="absolute inset-0 flex items-center justify-center bg-[#070b14]">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={frameUrl}
              alt="PyBullet digital twin live frame"
              className="w-full h-full object-contain"
              style={{ imageRendering: "pixelated" }}
            />
            {/* Anomaly overlay */}
            {hasAnomaly && (
              <div
                className="absolute inset-0 pointer-events-none"
                style={{
                  border: "2px solid rgba(239,68,68,0.7)",
                  boxShadow: "inset 0 0 30px rgba(239,68,68,0.25)",
                  borderRadius: "inherit",
                }}
              />
            )}
          </div>
        ) : (
          /* ── 3D canvas fallback ── */
          <Canvas
            shadows
            camera={{ position: [3, 3, 4], fov: 45 }}
            style={{ backgroundColor: "#0a0e1a" }}
          >
            <Suspense fallback={null}>
              <SceneContent />
            </Suspense>
          </Canvas>
        )}

        {/* Loading overlay */}
        {isLoading && !showJpeg && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40">
            <div className="flex flex-col items-center gap-3">
              <Cpu className="h-8 w-8 animate-pulse" style={{ color: "#14b8a6" }} />
              <p className="text-sm" style={{ color: "#94a3b8" }}>
                Loading 3D viewport…
              </p>
            </div>
          </div>
        )}

        {/* Bottom overlay label */}
        <div className="absolute bottom-3 left-3 pointer-events-none">
          <span
            className="text-[10px] font-mono px-2 py-1 rounded"
            style={{ backgroundColor: "rgba(10,14,26,0.7)", color: "#94a3b8" }}
          >
            {showJpeg
              ? "PyBullet live feed · ws:8765"
              : "drag to orbit · joint angles from bridge ws"}
          </span>
        </div>
      </div>
    </div>
  );
}
