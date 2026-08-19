import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/**
 * `X-Robots-Tag`가 의미를 갖는 응답 타입. 검색엔진은 HTML과 XML(sitemap)만 색인 대상으로
 * 읽으므로 JS·CSS·이미지에는 붙이지 않는다.
 */
const INDEXABLE_CONTENT_TYPES = ["text/html", "application/xml", "text/xml"];

function isIndexableResponse(response: Response): boolean {
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  return INDEXABLE_CONTENT_TYPES.some((type) => contentType.startsWith(type));
}

/**
 * 요청이 정식 오리진이 아닌 host로 들어왔는가 — 프리뷰 배포(`*.pages.dev`의 랜덤
 * 서브도메인)와 로컬 `wrangler pages dev`가 여기에 걸린다.
 *
 * `PUBLIC_ORIGIN`이 없거나 URL로 파싱되지 않으면 **판단을 포기하고 false**를 준다.
 * 환경변수 실수로 프로덕션 전체가 noindex가 되는 쪽이 프리뷰 하나가 색인되는 것보다
 * 훨씬 위험하다.
 */
export function isPreviewHost(env: WorkerEnv, request: Request): boolean {
  if (env.PUBLIC_ORIGIN === undefined) return false;

  let publicHost: string;
  try {
    publicHost = new URL(resolvePublicOrigin(env, request)).host;
  } catch {
    return false;
  }

  return new URL(request.url).host !== publicHost;
}

/**
 * 모든 응답이 밖으로 나가기 직전에 통과하는 지점(`handleRequest`의 마지막 줄).
 * 프리뷰 host의 HTML·XML에만 `X-Robots-Tag: noindex`를 붙인다 — 프리뷰가 색인되면
 * 프로덕션과 중복 콘텐츠가 되고, 어느 쪽을 남길지는 검색엔진이 정한다.
 *
 * 여기 한 곳에 두었으므로 sitemap·봇 메타 주입 등 이후 추가되는 응답에도 자동으로 적용된다.
 */
export function applyIndexingPolicy(
  response: Response,
  env: WorkerEnv,
  request: Request,
): Response {
  if (!isIndexableResponse(response)) return response;
  if (!isPreviewHost(env, request)) return response;

  // ASSETS가 돌려준 응답의 헤더는 불변이라 새 Response로 감싼다.
  const tagged = new Response(response.body, response);
  tagged.headers.set("x-robots-tag", "noindex");
  return tagged;
}
