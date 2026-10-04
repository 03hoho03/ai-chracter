/**
 * 모든 응답에 거는 기본 보안 헤더(CSP 제외). HTML 만이 아니라 전부에 건다 — nosniff 는
 * JS·CSS 에서 의미가 있고 나머지는 비 HTML 응답에서 무해하다.
 *
 * HSTS 는 `includeSubDomains`·`preload` 없이 둔다. 한 번 내보내면 max-age 동안 되돌리기
 * 어렵고, 서브도메인까지 묶으면 HTTPS 가 아닌 서브도메인이 하나만 생겨도 막힌다.
 */
const SECURITY_HEADERS: ReadonlyArray<readonly [string, string]> = [
  ["strict-transport-security", "max-age=31536000"],
  ["x-content-type-options", "nosniff"],
  ["x-frame-options", "DENY"],
  ["referrer-policy", "strict-origin-when-cross-origin"],
];

/**
 * 응답이 밖으로 나가기 직전에 보안 헤더를 붙인다(`handleRequest`의 마지막 줄).
 *
 * **없을 때만 넣는다.** `/_ingest/*` 로 나가는 Bugsink 응답은 이미 더 엄격한
 * `Referrer-Policy: same-origin` 을 주므로 덮어쓰면 오히려 약해진다. API 앞단 Caddy 도
 * 같은 의미(`header ?Name`)로 맞춰 두었다.
 *
 * ASSETS·업스트림 fetch·`Response.redirect` 가 돌려준 응답의 헤더는 불변이라 새 Response 로
 * 감싼 뒤 고친다.
 */
export function applySecurityHeaders(response: Response): Response {
  const secured = new Response(response.body, response);
  for (const [name, value] of SECURITY_HEADERS) {
    if (!secured.headers.has(name)) secured.headers.set(name, value);
  }
  return secured;
}
