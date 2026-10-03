import { readAppShellHtml } from "./appShell";
import { injectHead } from "./html";
import { buildMetaTags, SITE_NAME } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/** 서비스 소개. 정적 경로 하나뿐이라 세그먼트 파싱이 필요 없다. */
export const ABOUT_PATH = "/about";

/**
 * 봇 <head>에 더할 조각을 만든다. 순수 함수다.
 *
 * 본문이 클라이언트 번들에 박힌 정적 문장이라 title·description·canonical 전부 조회 없이 정해진다 —
 * 홈·약관 메타와 같은 이유로 `API_BASE_URL` 가드보다 위에 둔다.
 */
export function buildAboutHead(origin: string): string {
  return buildMetaTags({
    title: `서비스 소개 — ${SITE_NAME}`,
    description: `${SITE_NAME}는 AI 캐릭터와 대화하고, 직접 만든 캐릭터와 스토리를 다른 사람과 나누는 서비스입니다.`,
    canonical: `${origin}${ABOUT_PATH}`,
  });
}

/** 봇 UA + `/about` — index.html에 title·description·canonical을 주입해 응답한다. */
export async function handleAboutMeta(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const html = await readAppShellHtml(request, env);
  const head = buildAboutHead(resolvePublicOrigin(env, request));

  return new Response(injectHead(html, head), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
