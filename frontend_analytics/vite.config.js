import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const devPort = Number(process.env.VITE_PORT || 5178);

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: Number.isFinite(devPort) ? devPort : 5178,
    allowedHosts: [
      "localhost",
      "127.0.0.1",
      "docs.e-qoldau.asia",
      "219.e-qoldau.asia",
      "243.e-qoldau.asia",
      "420.e-qoldau.asia",
      "552.e-qoldau.asia",
      "analytics.e-qoldau.asia",
      "api.e-qoldau.asia",
    ],
    ...(process.env.VITE_DEV_TUNNEL_HOST
      ? {
          hmr: {
            host: process.env.VITE_DEV_TUNNEL_HOST,
            protocol: "wss",
            clientPort: 443,
          },
        }
      : {}),
  },
});
