import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const devPort = Number(env.VITE_PORT || 5175);
  const devHost = String(env.VITE_HOST || "0.0.0.0");

  return {
    plugins: [vue()],
    server: {
      host: devHost,
      port: Number.isFinite(devPort) ? devPort : 5175,
      strictPort: true,
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
      // Local dev by default.
      // For cloudflared dev set env: VITE_DEV_TUNNEL_HOST=docs.e-qoldau.asia
      ...(env.VITE_DEV_TUNNEL_HOST
        ? {
            hmr: {
              host: env.VITE_DEV_TUNNEL_HOST,
              protocol: "wss",
              clientPort: 443,
            },
          }
        : {}),
    },
  };
});
