import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { SentryProvider } from "@/components/SentryProvider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Auxin Automata — Agentic Infrastructure Node",
  description:
    "Hardware wallets · M2M micropayments · Immutable compliance on Solana",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={cn("dark", inter.variable)} suppressHydrationWarning>
      <body
        className="min-h-screen mecha-grid bg-gradient-to-br from-[#0a0e1a] via-[#131826] to-[#0a0e1a] font-sans text-text-primary antialiased"
        style={{
          backgroundImage: "url('/path-to-floral-pattern.svg')",
          backgroundSize: "cover",
          backgroundBlendMode: "overlay",
        }}
      >
        <SentryProvider />
        {children}
      </body>
    </html>
  );
}
