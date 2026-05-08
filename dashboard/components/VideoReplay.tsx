"use client";

/**
 * VideoReplay
 * ----------
 * Shows the recorded robot camera feed alongside real-time telemetry sync.
 *
 * The video is served by the bridge at GET /video/{camera_key}.
 * Frame synchronisation uses video.currentTime driven by the telemetry timestamp
 * (wall-clock at playback, not original recording timestamp).
 *
 * Features:
 *  - Multi-camera tab bar (ee_zed_m_left, ee_zed_m_right, third_person_d405)
 *  - Episode progress bar + frame index overlay
 *  - Oracle pulse: green flash on payment approval, red flash on anomaly
 *  - Graceful degradation if bridge or video endpoint is unreachable
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Video, Wifi, WifiOff, Camera, AlertTriangle } from "lucide-react";
import { useAuxinStore } from "@/lib/store";

// Bridge HTTP base URL (video endpoint lives on port 8767, same as /healthz)
const BRIDGE_HTTP =
  (process.env.NEXT_PUBLIC_BRIDGE_HTTP_URL ?? "http://localhost:8767").replace(/\/$/, "");

const CAMERA_LABELS: Record<string, string> = {
  ee_zed_m_left: "EE ZED Left",
  ee_zed_m_right: "EE ZED Right",
  third_person_d405: "3rd Person",
};

const AVAILABLE_CAMERAS = ["ee_zed_m_left", "ee_zed_m_right", "third_person_d405"];

type OraclePulse = "approved" | "anomaly" | null;

export function VideoReplay() {
  const frameSync = useAuxinStore((s) => s.frameSync);
  const telemetry = useAuxinStore((s) => s.telemetry);

  const [activeCamera, setActiveCamera] = useState("ee_zed_m_left");
  const [videoError, setVideoError] = useState(false);
  const [videoLoaded, setVideoLoaded] = useState(false);
  const [oraclePulse, setOraclePulse] = useState<OraclePulse>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const prevPaymentCount = useRef(0);
  const prevComplianceCount = useRef(0);
  const geminiCallCount = useAuxinStore((s) => s.geminiCallCount);
  const complianceEventCount = useAuxinStore((s) => s.complianceEventCount);

  // Sync video time to episode progress.
  // Only seek if divergence exceeds 3 s — the video plays at its own natural
  // pace under autoPlay; we only correct large drift caused by the bridge
  // pausing/skipping (e.g. the 148 s idle gap that gets capped to 2 s).
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !videoLoaded || !frameSync || !video.duration) return;

    const targetTime = frameSync.episode_progress * video.duration;
    if (Math.abs(video.currentTime - targetTime) > 3.0) {
      video.currentTime = targetTime;
    }
  }, [frameSync, videoLoaded]);

  // Oracle approved pulse (new payment)
  useEffect(() => {
    if (geminiCallCount > prevPaymentCount.current) {
      prevPaymentCount.current = geminiCallCount;
      setOraclePulse("approved");
      const t = setTimeout(() => setOraclePulse(null), 800);
      return () => clearTimeout(t);
    }
  }, [geminiCallCount]);

  // Anomaly detected pulse (new compliance event)
  useEffect(() => {
    if (complianceEventCount > prevComplianceCount.current) {
      prevComplianceCount.current = complianceEventCount;
      // Don't pulse on session start/end markers (they show up as compliance events too)
      if (telemetry?.hasAnomaly) {
        setOraclePulse("anomaly");
        const t = setTimeout(() => setOraclePulse(null), 800);
        return () => clearTimeout(t);
      }
    }
  }, [complianceEventCount, telemetry]);

  const videoSrc = `${BRIDGE_HTTP}/video/${activeCamera}`;

  const pulseColor =
    oraclePulse === "approved"
      ? "rgba(20,241,149,0.7)"
      : oraclePulse === "anomaly"
      ? "rgba(239,68,68,0.7)"
      : "transparent";

  return (
    <div
      className="relative flex flex-col rounded-2xl overflow-hidden"
      style={{
        backgroundColor: "rgba(7,11,20,0.95)",
        border: "1px solid rgba(168,85,247,0.18)",
        boxShadow: "0 4px 32px rgba(0,0,0,0.5)",
        minHeight: "320px",
      }}
    >
      {/* Camera tab bar */}
      <div
        className="flex items-center gap-1 px-3 py-2 shrink-0"
        style={{ borderBottom: "1px solid rgba(168,85,247,0.12)" }}
      >
        <Camera className="h-3.5 w-3.5 mr-1" style={{ color: "#A855F7" }} />
        {AVAILABLE_CAMERAS.map((key) => (
          <button
            key={key}
            onClick={() => {
              setActiveCamera(key);
              setVideoError(false);
              setVideoLoaded(false);
            }}
            className="px-2 py-0.5 rounded-full text-[10px] font-bold tracking-widest uppercase transition-all"
            style={{
              backgroundColor:
                activeCamera === key ? "rgba(168,85,247,0.22)" : "transparent",
              color: activeCamera === key ? "#C084FC" : "#4b5563",
              border:
                activeCamera === key
                  ? "1px solid rgba(168,85,247,0.40)"
                  : "1px solid transparent",
            }}
          >
            {CAMERA_LABELS[key] ?? key}
          </button>
        ))}

        {/* Live indicator */}
        <div className="ml-auto flex items-center gap-1.5">
          {frameSync && (
            <span
              className="text-[10px] font-mono"
              style={{ color: "#6b7280" }}
            >
              {frameSync.frame_index.toLocaleString()} /&nbsp;
              {frameSync.total_frames.toLocaleString()}
            </span>
          )}
          {videoLoaded ? (
            <Wifi className="h-3 w-3" style={{ color: "#14F195" }} />
          ) : (
            <WifiOff className="h-3 w-3" style={{ color: "#6b7280" }} />
          )}
        </div>
      </div>

      {/* Video area */}
      <div className="relative flex-1">
        {/* Oracle pulse border */}
        <AnimatePresence>
          {oraclePulse && (
            <motion.div
              key={oraclePulse}
              className="absolute inset-0 rounded-none pointer-events-none z-20"
              style={{ border: `2px solid ${pulseColor}` }}
              initial={{ opacity: 0 }}
              animate={{ opacity: [0, 1, 0] }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.8, ease: "easeOut" }}
            />
          )}
        </AnimatePresence>

        {/* Video element is always mounted so the browser starts loading immediately.
            We fade it in once data is ready rather than using display:none, which
            can prevent onLoadedData from firing in some browsers. */}
        <video
          ref={videoRef}
          key={videoSrc}
          src={videoSrc}
          className="w-full h-full object-cover"
          style={{
            minHeight: "240px",
            opacity: videoLoaded && !videoError ? 1 : 0,
            transition: "opacity 0.4s ease",
            position: videoLoaded && !videoError ? "relative" : "absolute",
            inset: 0,
          }}
          autoPlay
          muted
          loop
          playsInline
          onLoadedData={() => { setVideoLoaded(true); setVideoError(false); }}
          onError={() => setVideoError(true)}
        />

        {/* Loading / error placeholder */}
        {(!videoLoaded || videoError) && (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-3"
            style={{ minHeight: "240px" }}
          >
            {videoError ? (
              <>
                <AlertTriangle className="h-8 w-8" style={{ color: "#6b7280" }} />
                <p className="text-xs" style={{ color: "#6b7280" }}>
                  Waiting for video feed&hellip;
                </p>
                <p className="text-[10px] font-mono" style={{ color: "#374151" }}>
                  {videoSrc}
                </p>
              </>
            ) : (
              <>
                <Video className="h-8 w-8 animate-pulse" style={{ color: "#A855F7" }} />
                <p className="text-xs" style={{ color: "#6b7280" }}>
                  Loading camera feed&hellip;
                </p>
              </>
            )}
          </div>
        )}

        {/* Episode progress bar */}
        {frameSync && videoLoaded && (
          <div
            className="absolute bottom-0 left-0 right-0"
            style={{ backgroundColor: "rgba(7,11,20,0.75)", padding: "6px 10px" }}
          >
            <div className="flex items-center gap-2">
              <div
                className="flex-1 h-1 rounded-full overflow-hidden"
                style={{ backgroundColor: "rgba(168,85,247,0.15)" }}
              >
                <motion.div
                  className="h-full rounded-full"
                  style={{ backgroundColor: "#A855F7" }}
                  animate={{ width: `${frameSync.episode_progress * 100}%` }}
                  transition={{ duration: 0.3, ease: "linear" }}
                />
              </div>
              <span
                className="text-[9px] font-mono shrink-0"
                style={{ color: "#6b7280" }}
              >
                {Math.round(frameSync.episode_progress * 100)}%
              </span>
              {frameSync.loop_count > 0 && (
                <span
                  className="text-[9px] font-bold tracking-widest uppercase shrink-0"
                  style={{ color: "#A855F7" }}
                >
                  Loop&nbsp;{frameSync.loop_count + 1}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Oracle pulse label */}
        <AnimatePresence>
          {oraclePulse && (
            <motion.div
              key={`label-${oraclePulse}`}
              className="absolute top-3 right-3 px-2 py-0.5 rounded-full text-[10px] font-bold tracking-widest uppercase"
              style={{
                backgroundColor:
                  oraclePulse === "approved"
                    ? "rgba(20,241,149,0.15)"
                    : "rgba(239,68,68,0.15)",
                color:
                  oraclePulse === "approved" ? "#14F195" : "#ef4444",
                border: `1px solid ${oraclePulse === "approved" ? "rgba(20,241,149,0.4)" : "rgba(239,68,68,0.4)"}`,
              }}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
            >
              {oraclePulse === "approved" ? "AI Inference ✓" : "Anomaly Detected"}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
