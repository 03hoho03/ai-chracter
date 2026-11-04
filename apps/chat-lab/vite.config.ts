import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  resolve: {
    // @types/node 없이 쓰는 절대경로(node:url 대신 DOM 전역 URL) — POSIX(dev macOS·CI Linux) 전제.
    // apps/web·apps/admin 과 같은 형태로 맞춘다.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    // 측정 서버의 CORS 가 이 오리진(127.0.0.1·localhost 의 5291)만 받는다. 포트가 비어 있지 않을 때 Vite 가
    // 다음 포트로 옮겨 가면 화면은 뜨는데 요청만 전부 막히므로, 옮기지 말고 바로 실패하게 한다.
    host: "127.0.0.1",
    port: 5291,
    strictPort: true,
  },
  // 라우터 플러그인을 쓰지 않는다 — 라우트는 코드로 적고 동적 import 를 두지 않아, 런 하나를 단일 HTML 로
  // 굳힐 때 따로 떨어지는 청크가 생기지 않는다.
  plugins: [react(), tailwindcss()],
});
