/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        fs: {
          bg: "#f4f6f9",
          surface: "#ffffff",
          sidebar: "#f8fafc",
          border: "#e2e8f0",
          text: "#0f172a",
          muted: "#64748b",
          subtle: "#94a3b8",
          accent: "#0f4c81",
          accentHover: "#0c3d68",
          accentSoft: "#e8f1f8",
          success: "#059669",
          successSoft: "#ecfdf5",
          userBubble: "#0f4c81",
          botBubble: "#f1f5f9",
          danger: "#dc2626",
          dangerSoft: "#fef2f2"
        }
      },
      boxShadow: {
        card: "0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04)",
        panel: "0 4px 24px rgba(15, 23, 42, 0.08)"
      }
    }
  },
  plugins: []
};
