import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  resolve: {
    // @types/node 없이 쓰는 절대경로(node:url 대신 DOM 전역 URL) — POSIX(dev macOS·CI Linux) 전제.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    // tailscale serve(MagicDNS 호스트명)로 원격 접속할 때 Vite의 host 검사를 통과시킨다.
    allowedHosts: [".ts.net"],
  },
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
});
