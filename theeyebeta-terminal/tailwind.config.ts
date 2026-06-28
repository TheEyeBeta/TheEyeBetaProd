import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#0A0A0F",
          panel: "#0D0D15",
          panel2: "#11111A",
          border: "#1A1A2E",
          primary: "#00FFD1",
          secondary: "#FF6B35",
          danger: "#FF2D55",
          positive: "#00E676",
          text: "#E8E8F0",
          muted: "#6B7280"
        }
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"]
      },
      boxShadow: {
        neon: "0 0 18px rgba(0, 255, 209, 0.38)"
      }
    }
  },
  plugins: []
} satisfies Config;
