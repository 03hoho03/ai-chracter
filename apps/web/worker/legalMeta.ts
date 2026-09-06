import { readAppShellHtml } from "./appShell";
import { injectHead } from "./html";
import { buildMetaTags, SITE_NAME } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/** `/legal/{kind}` API와 값이 같은, 약관 공개 페이지 종류. */
export type LegalKind = "terms" | "privacy";

const LEGAL_LABEL: Record<LegalKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
};

/** 경로 → 약관 종류. 정적 경로 둘뿐이라 세그먼트 파싱이 필요 없다. */
export function parseLegalPath(pathname: string): LegalKind | undefined {
  if (pathname === "/terms") return "terms";
  if (pathname === "/privacy") return "privacy";
  return undefined;
}

/**
 * 봇 <head>에 더할 조각을 만든다. 순수 함수다.
 *
 * title·description·canonical 전부 조회 없이 정해진다(문서 본문은 클라이언트가 `GET /legal/{kind}`로
 * 받아 그리므로 봇 메타에는 필요 없다) — 홈 메타와 같은 이유로 `API_BASE_URL` 가드보다 위에 둔다.
 */
export function buildLegalHead(kind: LegalKind, origin: string): string {
  const label = LEGAL_LABEL[kind];

  return buildMetaTags({
    title: `${label} — ${SITE_NAME}`,
    description: `${SITE_NAME} ${label}을 확인하세요.`,
    canonical: `${origin}/${kind}`,
  });
}

/** 봇 UA + `/terms`·`/privacy` — index.html에 title·description·canonical을 주입해 응답한다. */
export async function handleLegalMeta(
  request: Request,
  env: WorkerEnv,
  kind: LegalKind,
): Promise<Response> {
  const html = await readAppShellHtml(request, env);
  const head = buildLegalHead(kind, resolvePublicOrigin(env, request));

  return new Response(injectHead(html, head), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
