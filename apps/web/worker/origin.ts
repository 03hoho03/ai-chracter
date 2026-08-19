import type { WorkerEnv } from "./workerRuntime";

/**
 * canonical·sitemap·og:url에 쓰는 **사이트 기준 오리진**. 요청 host를 쓰지 않는다 —
 * 프리뷰 배포(`*.pages.dev`의 랜덤 서브도메인)가 색인되더라도 URL은 프로덕션을 가리켜야
 * 중복 콘텐츠가 되지 않는다.
 *
 * 환경변수가 없을 때만 요청 오리진으로 폴백한다(로컬 `wrangler pages dev`).
 * 끝의 `/`는 잘라낸다 — 대시보드에 `https://example.com/`처럼 넣어도 `//content/...`가 되지 않게.
 */
export function resolvePublicOrigin(env: WorkerEnv, request: Request): string {
  const origin = env.PUBLIC_ORIGIN ?? new URL(request.url).origin;
  return origin.replace(/\/+$/, "");
}
