import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    // Only needed for local `npm run dev` behind a public hostname
    allowedHosts: ["dashboard.fmfurnisteel.com", "localhost"],
    hmr: {
      protocol: "wss",
      host: "dashboard.fmfurnisteel.com",
      clientPort: 443,
    },
  },
});
