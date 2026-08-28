import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  resolve: {
    // @types/node 없이 쓰는 절대경로(node:url 대신 DOM 전역 URL) — POSIX(dev macOS·CI Linux) 전제.
    // apps/web과 같은 형태로 맞춘다.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    port: 5174,
  },
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
});
