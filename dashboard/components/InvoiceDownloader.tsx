"use client";

/**
 * InvoiceDownloader
 * -----------------
 * Small card that shows the latest generated invoice metadata and
 * offers a download button that fetches the PDF from the bridge's
 * GET /invoice/latest endpoint.
 */

import { useAuxinStore } from "@/lib/store";
import { Download, FileText } from "lucide-react";
import { useState } from "react";

const BRIDGE_HTTP_URL = (
  process.env.NEXT_PUBLIC_BRIDGE_HTTP_URL ?? "http://localhost:8767"
).replace(/\/$/, "");

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "2-digit",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

export function InvoiceDownloader() {
  const meta = useAuxinStore((s) => s.latestInvoiceMeta);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      const res = await fetch(`${BRIDGE_HTTP_URL}/invoice/latest`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = meta ? `invoice_${meta.invoice_id.slice(0, 8)}.pdf` : "invoice.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 rounded-xl shrink-0"
      style={{
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(20,184,166,0.15)",
      }}
    >
      <FileText className="h-3.5 w-3.5 shrink-0" style={{ color: "#14b8a6" }} />

      <div className="flex flex-col min-w-0">
        <span className="text-[10px] tracking-widest uppercase" style={{ color: "#6b7280" }}>
          Latest Invoice
        </span>
        {meta ? (
          <span className="text-[11px] font-medium truncate" style={{ color: "#9ca3af" }}>
            {formatDate(meta.period_start)} – {formatDate(meta.period_end)}
            {" · "}
            <span style={{ color: "#14b8a6" }}>{meta.total_sol.toFixed(6)} SOL</span>
          </span>
        ) : (
          <span className="text-[11px]" style={{ color: "#4b5563" }}>
            No invoice yet
          </span>
        )}
        {error && <span className="text-[10px]" style={{ color: "#ef4444" }}>{error}</span>}
      </div>

      <button
        onClick={handleDownload}
        disabled={downloading}
        aria-label="Download latest invoice"
        className="shrink-0 rounded-lg p-1.5 transition-colors hover:bg-teal-500/10 disabled:opacity-40 disabled:cursor-not-allowed"
        style={{ color: "#14b8a6" }}
      >
        <Download className={`h-4 w-4 ${downloading ? "animate-bounce" : ""}`} />
      </button>
    </div>
  );
}
