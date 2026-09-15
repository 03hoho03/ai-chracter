import { sentryVitePlugin } from "@sentry/vite-plugin";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * `vite.config.ts`는 Node에서 도는 빌드 스크립트라 실제로 `process`가 있지만, 이 저장소는
 * `@types/node`를 두지 않는다(브라우저 코드에 `process`가 새는 걸 컴파일 타임에 막으려는
 * 선택 — `src/main.tsx` 주석 참고). `worker/cache.ts`의 `declare const caches`와 같은
 * 이유로, 이 파일 안에서만 좁혀 선언한다(모듈 스코프라 다른 파일로 안 샌다).
 */
declare const process: { env: Record<string, string | undefined> };

/**
 * 소스맵 업로드(monitoring-techspec.md MT-8)에 쓰는 Bugsink 인증 토큰. Cloudflare Pages
 * **빌드** 환경변수로만 넣는다 — `VITE_` 접두어를 쓰면 브라우저 번들에 그대로 실려 공개된다.
 *
 * 로컬·CI에는 이 값이 없다. **플러그인에게 "토큰 없을 때 뭘 할지"를 맡기지 않고 여기서
 * 명시적으로 판단한다** — 토큰이 없으면 플러그인 자체를 `plugins` 배열에서 뺀다. 그래야
 * 인증 토큰 없는 환경에서 빌드가 깨지지 않는다는 걸 이 파일만 보고 보장할 수 있다.
 */
const sentryAuthToken = process.env.SENTRY_AUTH_TOKEN;

export default defineConfig({
  resolve: {
    // @types/node 없이 쓰는 절대경로(node:url 대신 DOM 전역 URL) — POSIX(dev macOS·CI Linux) 전제.
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    // tailscale serve(MagicDNS 호스트명)로 원격 접속할 때 Vite의 host 검사를 통과시킨다.
    allowedHosts: [".ts.net"],
  },
  build: {
    // 숨김 생성 — 번들 JS에 `//# sourceMappingURL=` 참조 주석을 남기지 않는다(참조가 있으면
    // 브라우저 devtools가 공개 경로로 `.map`을 바로 찾으러 간다). 업로드 후 삭제와 한 쌍이라,
    // 업로드할 토큰이 없는 환경(로컬·CI)에서는 애초에 만들지 않는다 — 지울 대상을 안 만들면
    // "삭제를 깜박한다"는 실패 모드 자체가 없어진다.
    sourcemap: sentryAuthToken ? "hidden" : false,
  },
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    // 소스맵 업로드 플러그인은 반드시 배열 **마지막**에 둔다(다른 플러그인이 변환을 끝낸
    // 뒤의 최종 산출물을 봐야 한다 — 공식 문서 권고).
    ...(sentryAuthToken
      ? [
          sentryVitePlugin({
            sourcemaps: {
              // 업로드 후 `.map`을 지운다 — 안 지우면 `worker/handler.ts:isStaticAssetPath`가
              // `/assets/*`를 그대로 서빙하고 `_headers` 파일도 없어(§0-1-17) `.map`이 공개
              // 다운로드된다. org·project·url은 `SENTRY_ORG`/`SENTRY_PROJECT`/`SENTRY_URL`
              // 환경변수로 플러그인이 직접 읽는다(공식 지원, DEPLOY.md에 값을 남긴다).
              filesToDeleteAfterUpload: ["dist/**/*.map"],
            },
          }),
        ]
      : []),
  ],
});
