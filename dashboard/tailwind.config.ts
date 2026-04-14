import type { Config } from "tailwindcss";

// Design tokens defined here are expanded fully in Phase 2C.
const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Mechafloral palette — finalised in Phase 2C
        background: "#0a0e1a",
        surface: "#131826",
        border: "#1f2937",
        "accent-teal": "#14b8a6",
        "accent-solana": "#14F195",
        "text-primary": "#f1f5f9",
        "text-muted": "#94a3b8",
      },
    },
  },
  plugins: [],
};

export default config;
