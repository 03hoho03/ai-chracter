import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // vitest.config 가 있으면 vite.config 는 읽히지 않는다 — alias 를 여기에도 같게 적는다. 설정을 나누는 이유는
    // vitest 가 안에 자기 vite(7)를 따로 써서, vite 8 용 플러그인을 이쪽에 끌어오지 않으려는 것이다(apps/web 과 같다).
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  test: {
    // 브라우저 흉내(jsdom 등)를 들이지 않고 순수 함수만 검사한다.
    environment: "node",
  },
});
