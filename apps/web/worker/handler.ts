import { applyIndexingPolicy } from "./indexing";
import { handleOgImage, OG_IMAGE_PATH_PREFIX } from "./og-image";
import { handleRobots } from "./robots";
import { handleSitemap } from "./sitemap";
import type { WorkerDeps, WorkerEnv } from "./types";

/**
 * 확장자가 있는 경로와 `/assets/*`는 정적 자산이다. 다른 어떤 검사보다 먼저 통과시킨다 —
 * JS·CSS·폰트·이미지 전부가 이 경로로 나가므로 여기서 한 번이라도 헛돌면 사이트가 죽는다.
 */
function isStaticAssetPath(pathname: string): boolean {
  if (pathname.startsWith("/assets/")) return true;
  return pathname.slice(pathname.lastIndexOf("/") + 1).includes(".");
}

/**
 * SPA 셸(index.html)을 200으로 돌려준다.
 *
 * `_worker.js`가 있으면 Pages는 모든 요청을 Worker로 보내고 `public/_redirects`의
 * `/* → /index.html 200`을 더 이상 적용하지 않는다. 딥링크·새로고침이 index.html을
 * 받게 하는 일은 이제 Worker의 몫이다.
 */
function serveAppShell(request: Request, env: WorkerEnv): Promise<Response> {
  const indexUrl = new URL("/index.html", request.url);
  return env.ASSETS.fetch(new Request(indexUrl, { headers: request.headers }));
}

/**
 * Worker 진입 핸들러. 런타임 전용 자원(Cache API)은 전부 `deps`로 주입받으므로
 * 이 함수는 vitest(`environment: "node"`)에서 그냥 호출해 테스트할 수 있다.
 *
 * 라우팅 결과는 예외 없이 `applyIndexingPolicy`를 통과해서 나간다 — 프리뷰 배포의
 * 색인 차단을 라우트마다 기억해야 하는 규칙으로 만들지 않기 위해서다.
 */
export async function handleRequest(
  request: Request,
  env: WorkerEnv,
  deps: WorkerDeps,
): Promise<Response> {
  const response = await routeRequest(request, env, deps);
  return applyIndexingPolicy(response, env, request);
}

async function routeRequest(
  request: Request,
  env: WorkerEnv,
  deps: WorkerDeps,
): Promise<Response> {
  const url = new URL(request.url);

  // Worker가 만들어 내는 경로는 정적 자산 검사보다 **먼저** 가로챈다.
  // `/sitemap.xml`·`/robots.txt`는 확장자가 있어 `isStaticAssetPath`가 true를 주고,
  // 그대로 ASSETS로 넘기면 (dist에 그런 파일이 없으므로) index.html이 200으로 나간다.
  if (url.pathname === "/sitemap.xml") {
    return handleSitemap(request, env, deps);
  }

  if (url.pathname === "/robots.txt") {
    return handleRobots(request, env);
  }

  // `/og/...`는 접두사로 통째로 가로챈다 — 형식이 틀린 것까지 여기서 404로 끝내지 않으면
  // 확장자가 있는 경로라 ASSETS로 흘러가 og:image 자리에 index.html이 200으로 나간다.
  if (url.pathname.startsWith(OG_IMAGE_PATH_PREFIX)) {
    return handleOgImage(request, env, deps);
  }

  if (isStaticAssetPath(url.pathname)) {
    return env.ASSETS.fetch(request);
  }

  // API_BASE_URL은 Pages 런타임 환경변수라 대시보드에서 빠뜨릴 수 있다. 없으면 API를
  // 두드리는 SEO 경로를 통째로 건너뛴다 — 환경변수 하나가 사이트 전체를 죽이면 안 된다.
  if (!env.API_BASE_URL) {
    return serveAppShell(request, env);
  }

  // 봇 메타 주입·404 판별이 이 자리에 붙는다(US-007~US-011).

  return serveAppShell(request, env);
}
