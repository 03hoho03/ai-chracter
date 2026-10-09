// Cloudflare Pages Advanced Mode 진입점. 빌드 없이 `public/`에서 `dist/_worker.js`로 그대로 복사된다.
//
// 하는 일은 하나다 — 없는 자산 파일 요청에 SPA 셸이 200으로 나가지 않게 한다. Pages 자산 서버는
// 없는 파일에도 index.html을 200으로 주고, 그 응답에 요청 경로의 확장자를 따라 자산과 같은
// `max-age=14400`을 붙인다. 그러면 배포 직후 옛 번들 이름을 요청한 브라우저가 JS·CSS 자리에 HTML을
// 받아 4시간 동안 스타일 없는 화면·라우트 코드 로드 실패를 겪는다. `_redirects`는 404 재작성을
// 지원하지 않고 `_headers`는 있는 파일과 없는 파일을 경로로 구별하지 못해서 Worker가 맡는다.
//
// 나머지 요청은 전부 ASSETS로 넘긴다. ASSETS는 `_headers`·`_redirects`를 그대로 적용하므로
// 보안 헤더와 SPA 폴백은 지금과 같다.

// `_headers`가 붙여 주는 보안 헤더. Worker가 새로 만든 404에는 `_headers`가 걸리지 않아서
// ASSETS 응답에 붙어 온 값을 옮겨 단다.
const SECURITY_HEADER_NAMES = [
  "strict-transport-security",
  "x-content-type-options",
  "referrer-policy",
  "x-frame-options",
];

// 확장자가 있는 경로와 `/assets/*`는 정적 자산이다(web Worker의 `isStaticAssetPath`와 같은 기준).
function isStaticAssetPath(pathname) {
  if (pathname.startsWith("/assets/")) return true;
  return pathname.slice(pathname.lastIndexOf("/") + 1).includes(".");
}

export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request);
    if (!isStaticAssetPath(new URL(request.url).pathname)) return response;

    // 자산 경로에 HTML이 200으로 왔다는 것 자체가 파일이 없다는 신호다 — 진짜 `.html` 파일은
    // Pages가 확장자를 떼는 308로 준다.
    const isHtml = (response.headers.get("content-type") ?? "").startsWith("text/html");
    if (response.status !== 200 || !isHtml) return response;

    // no-store: 다음 요청에서 파일이 생겼으면 바로 받아야 하므로 브라우저·엣지 어디에도 남기지 않는다.
    const headers = new Headers({
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    });
    for (const name of SECURITY_HEADER_NAMES) {
      const value = response.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    return new Response("Not Found", { status: 404, headers });
  },
};
