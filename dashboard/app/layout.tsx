import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
