import { readAppShellHtml } from "./appShell";
import { injectHead } from "./html";
import { buildMetaTags, SITE_NAME } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/** `/legal/{kind}` API와 값이 같은 법적 문서 종류. 값이 곧 웹 경로라(`/operation-policy` 등) 경로 해석과
 * canonical 이 따로 표를 두지 않는다. */
export type LegalKind = "terms" | "privacy" | "operation-policy" | "youth-policy";

const LEGAL_LABEL: Record<LegalKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
  "operation-policy": "운영정책",
  "youth-policy": "청소년 보호정책",
};

function isLegalKind(value: string): value is LegalKind {
  // own key만 본다 — `in`이면 `/toString` 같은 경로가 프로토타입 키로 통과한다.
  return Object.hasOwn(LEGAL_LABEL, value);
}

/** 경로 → 법적 문서 종류. 한 세그먼트 정적 경로뿐이라 앞 `/`만 떼어 종류 표에 대 본다. */
export function parseLegalPath(pathname: string): LegalKind | undefined {
  const kind = pathname.slice(1);
  return pathname.startsWith("/") && isLegalKind(kind) ? kind : undefined;
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

/** 봇 UA + 법적 문서 경로 — index.html에 title·description·canonical을 주입해 응답한다. */
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
