import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Proxy /api → FastAPI backend so the frontend can call it same-origin in dev.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["apple-touch-icon.png", "store-bg.png"],
      manifest: {
        name: "C-Bot — Costco Assistant",
        short_name: "C-Bot",
        description: "Ask about and compare Costco products by text or voice.",
        theme_color: "#e32b2b",
        background_color: "#f4f6fb",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "pwa-512-maskable.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Don't cache API calls; network-first for everything dynamic.
        navigateFallbackDenylist: [/^\/(chat|products|index|tts|settings|knowledge|health)/],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024, // store-bg.png is ~3MB
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
