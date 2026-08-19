import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./types";

/**
 * 크롤링을 막을 경로. 로그인·개인 화면·작성 도구는 색인돼도 검색 결과에서 쓸모가 없고
 * 크롤 예산만 먹는다. 접두사 매칭이므로 하위 경로 전체를 막으려면 `/`로 끝낸다.
 */
const DISALLOWED_PATHS = [
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/onboarding/",
  "/mypage",
  "/favorites",
  "/chats",
  "/chat/",
  "/builder/",
  "/studio/",
  "/ui-demo",
];

/**
 * robots.txt 본문. 순수 함수다.
 *
 * `Sitemap:`은 절대 URL이어야 하고, 그 기준은 요청 host가 아니라 정식 오리진이다 —
 * 프리뷰에서 긁힌 robots.txt가 프리뷰 sitemap을 가리키면 프리뷰 URL이 색인 대상이 된다.
 */
export function buildRobotsTxt(origin: string): string {
  return [
    "User-agent: *",
    ...DISALLOWED_PATHS.map((path) => `Disallow: ${path}`),
    "",
    `Sitemap: ${origin}/sitemap.xml`,
    "",
  ].join("\n");
}

/** `GET /robots.txt`. 조회할 데이터가 없어 매 요청 즉시 만든다(캐시 불필요). */
export function handleRobots(request: Request, env: WorkerEnv): Response {
  return new Response(buildRobotsTxt(resolvePublicOrigin(env, request)), {
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
