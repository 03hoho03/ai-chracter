import { readAppShellHtml } from "./app-shell";
import { injectHead } from "./html";
import { buildMetaTags } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./types";

/** 홈. 정렬·장르 쿼리(`?sort=popular` 등)가 붙어도 경로는 언제나 이것 하나다. */
export const HOME_PATH = "/";

/**
 * 홈 <head>에 더할 조각을 만든다. 순수 함수다.
 *
 * title·description·og:*는 조회 없이 정해지므로 index.html에 직접 박혀 있고, 여기서는
 * **오리진을 알아야 만들 수 있는 두 개만** 만든다.
 *
 * canonical은 요청 URL이 아니라 항상 `{origin}/`이다 — `/?sort=latest`, `/?sort=popular`,
 * `/?sort=genre&genre={uuid}`가 전부 같은 홈이라 쿼리를 살려 두면 구글이 중복 콘텐츠로 본다.
 */
export function buildHomeHead(origin: string): string {
  return buildMetaTags({
    canonical: `${origin}/`,
    ogUrl: `${origin}/`,
  });
}

/**
 * 봇 UA + 홈 — index.html에 canonical·og:url을 주입해 응답한다.
 *
 * API를 두드리지 않는다(홈 메타는 데이터에 기대지 않는다) — 그래서 호출부에서
 * `API_BASE_URL` 가드보다 위에 배선한다.
 */
export async function handleHomeMeta(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const html = await readAppShellHtml(request, env);
  const head = buildHomeHead(resolvePublicOrigin(env, request));

  return new Response(injectHead(html, head), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
