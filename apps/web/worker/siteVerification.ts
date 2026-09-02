/**
 * 검색엔진 소유확인 **파일**은 Worker가 직접 응답한다 — `public/`에 커밋하면 안 된다.
 *
 * 실측(2026-09-02): `public/`에 둔 `foo.html`은 `dist/`까지는 잘 복사되지만 프로덕션에서
 * 도달할 수 없다. Pages 자산 서버가 클린 URL 정책으로 `/foo.html` → `/foo`를 **308**로 돌려주고
 * (`env.ASSETS.fetch()`가 그 308을 그대로 준다), 확장자가 사라진 `/foo`는 `KNOWN_ROUTES`에 없어
 * 우리 Worker가 soft-404 제거 규칙에 따라 404를 준다. 검증기는 `.html` URL을 치므로 실패한다.
 *
 * 그래서 자산 검사(`isStaticAssetPath`)보다 **앞에서** 가로채 본문을 직접 만든다.
 *
 * **meta 태그가 아니라 파일을 쓰는 이유**: `index.html`에 옛 `pages.dev` 사이트용
 * `naver-site-verification` 태그가 이미 있다. 같은 `name`의 meta를 하나 더 넣으면 크롤러
 * 대부분이 앞의 것만 읽어 새 사이트 확인이 조용히 실패한다. 옛 태그는 주소 이전 기간 동안
 * 살아 있어야 하므로 교체할 수도 없다.
 */
const VERIFICATION_FILES: Record<string, string> = {
  // ddona.site — 네이버 서치어드바이저 (2026-09-02 등록)
  "/naver51990167ef24f88190ab863b33dae806.html":
    "naver-site-verification: naver51990167ef24f88190ab863b33dae806.html",
};

/** 소유확인 파일 경로면 그 본문을, 아니면 `undefined`. */
export function handleSiteVerification(pathname: string): Response | undefined {
  const body = VERIFICATION_FILES[pathname];
  if (body === undefined) return undefined;

  return new Response(body, {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
