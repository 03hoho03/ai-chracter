import { serveAppShell } from "./appShell";
import { handleContentMeta, parseContentPath } from "./contentMeta";
import { isCrawler } from "./crawler";
import { handleHomeMeta, HOME_PATH } from "./homeMeta";
import { applyIndexingPolicy } from "./indexing";
import { buildLegacyRedirect } from "./legacyRedirect";
import { handleOgImage, OG_IMAGE_PATH_PREFIX } from "./ogImage";
import { handleProfileMeta, parseProfilePath } from "./profileMeta";
import { handleRobots } from "./robots";
import { isKnownRoute } from "./routes";
import { handleSitemap } from "./sitemap";
import type { WorkerDeps, WorkerEnv } from "./workerRuntime";

/**
 * 확장자가 있는 경로와 `/assets/*`는 정적 자산이다. 다른 어떤 검사보다 먼저 통과시킨다 —
 * JS·CSS·폰트·이미지 전부가 이 경로로 나가므로 여기서 한 번이라도 헛돌면 사이트가 죽는다.
 */
function isStaticAssetPath(pathname: string): boolean {
  if (pathname.startsWith("/assets/")) return true;
  return pathname.slice(pathname.lastIndexOf("/") + 1).includes(".");
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
  // 옛 도메인은 경로를 가리지 않고 통째로 넘긴다 — 정적 자산 검사보다 **앞**이라야
  // `/assets/*`·`/sitemap.xml`까지 새 도메인으로 간다. `handleRequest`가 아니라 여기 두는 건
  // "모든 응답은 applyIndexingPolicy를 통과한다"는 불변식을 깨지 않기 위해서다.
  const legacyRedirect = buildLegacyRedirect(request, env);
  if (legacyRedirect !== undefined) return legacyRedirect;

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

  // 앱에 없는 경로는 셸 본문 그대로 404다 — 사용자는 앱의 NotFound 화면을 보고 봇만
  // 404를 받는다. `env.ASSETS.fetch()`가 없는 경로에도 index.html을 200으로 주므로
  // (Pages 자산 서버의 SPA 처리) 이 검사를 Worker가 직접 해야 soft 404가 사라진다.
  if (!isKnownRoute(url.pathname)) {
    return serveAppShell(request, env, 404);
  }

  // 봇에게만 <head>를 채워 준다 — 일반 사용자는 지금과 같은 응답(추가 API 왕복 0회)을 받는다.
  const isBot = isCrawler(request.headers.get("user-agent"));

  // 홈 메타는 조회에 기대지 않으므로 API_BASE_URL 가드보다 위에 둔다 — 환경변수가 빠져도
  // 최소한 홈의 canonical은 나간다.
  if (isBot && url.pathname === HOME_PATH) {
    return handleHomeMeta(request, env);
  }

  // API_BASE_URL은 Pages 런타임 환경변수라 대시보드에서 빠뜨릴 수 있다. 없으면 API를
  // 두드리는 SEO 경로를 통째로 건너뛴다 — 환경변수 하나가 사이트 전체를 죽이면 안 된다.
  if (!env.API_BASE_URL) {
    return serveAppShell(request, env);
  }

  if (isBot) {
    const contentId = parseContentPath(url.pathname);
    if (contentId !== undefined) {
      return handleContentMeta(request, env, contentId);
    }

    const userId = parseProfilePath(url.pathname);
    if (userId !== undefined) return handleProfileMeta(request, env, userId);
  }

  return serveAppShell(request, env);
}
