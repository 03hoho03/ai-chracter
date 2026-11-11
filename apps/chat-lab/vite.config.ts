import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

/** 앱 폴더 — 빌드 상수를 읽을 `.env` 자리. 아래 별칭과 같은 까닭으로 DOM 전역 URL 로 푼다. */
const APP_DIR = new URL(".", import.meta.url).pathname;

export default defineConfig(({ mode }) => {
  // 빌드 종류는 이 상수 하나로 갈린다. 없음(로컬)과 `hosted` 밖의 값은 빌드에서 막는다 — `hostd` 같은 오타가 조용히 로컬 빌드가
  // 되면 서비스에 넣은 화면이 런을 하나도 열지 못한다(루프백 밖 출처에서 연 로컬 빌드는 측정 서버 요청을 막고 "이 화면은 로컬
  // 빌드다" 안내만 띄운다). 두 빌드의 갈림은 README 「호스팅 모드」.
  const labModeValue = loadEnv(mode, APP_DIR, "VITE_CHAT_LAB_").VITE_CHAT_LAB_MODE;
  if (labModeValue !== undefined && labModeValue !== "hosted") {
    throw new Error(`VITE_CHAT_LAB_MODE 는 없거나 "hosted" 여야 한다(받은 값 ${JSON.stringify(labModeValue)})`);
  }

  return {
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
  };
});
