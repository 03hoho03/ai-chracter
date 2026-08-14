import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // vitest.config가 있으면 vite.config는 무시된다 — alias를 여기에도 동일하게 정의.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  test: {
    environment: "node",
  },
});
