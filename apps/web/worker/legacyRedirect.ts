import type { WorkerEnv } from "./workerRuntime";

/**
 * 옛 프로덕션 도메인. **정확히 이 host일 때만** 넘긴다.
 *
 * `endsWith("pages.dev")`나 `includes("ai-character-chat-web")`으로 판별하면
 * 프리뷰 배포(`<hash>.ai-character-chat-web.pages.dev`)와 브랜치 별칭까지 함께 날아간다 —
 * 접미사가 같기 때문이다. 프리뷰가 프로덕션으로 리다이렉트되면 PR에서 변경분을 볼 방법이 없어진다.
 */
const LEGACY_PRODUCTION_HOST = "ai-character-chat-web.pages.dev";

/**
 * 커스텀 도메인 전환 후에도 옛 주소를 살려 두기 위한 리다이렉트.
 * 커스텀 도메인을 붙여도 `*.pages.dev`는 계속 살아 있으므로, 이력서에 제출된 링크가
 * 새 도메인으로 이어지려면 여기서 직접 넘겨야 한다.
 *
 * **`resolvePublicOrigin()`을 쓰지 않는다.** 그 함수는 `PUBLIC_ORIGIN`이 없을 때 요청 오리진으로
 * 폴백하므로 여기서 쓰면 **자기 자신으로 리다이렉트하는 무한 루프**가 된다. 그래서 환경변수를
 * 직접 읽고, 목적지가 다시 옛 host가 되는 두 경우(미설정 · 교체 전 값)에는 리다이렉트하지 않는다.
 *
 * **301이다.** 처음엔 302 + `Cache-Control: no-store`로 배포해 host 매칭을 프로덕션에서 실측한 뒤
 * (프로덕션 host만 302, 살아 있는 프리뷰 배포는 200) 2026-09-02에 승격했다. 서치콘솔의 주소 변경
 * 도구가 301을 요구하는 것이 승격의 직접 이유다.
 *
 * ⚠️ **이제 되돌리기 어렵다.** 브라우저는 301을 오래 캐시하므로 분기를 지워도 이미 방문한
 * 브라우저는 한동안 새 도메인으로 간다. 되돌려야 한다면 코드를 지우는 것만으로는 부족하고,
 * 새 도메인을 계속 살려 두는 것이 유일한 실질적 복구 경로다.
 */
export function buildLegacyRedirect(request: Request, env: WorkerEnv): Response | undefined {
  const url = new URL(request.url);
  if (url.host !== LEGACY_PRODUCTION_HOST) return undefined;

  if (env.PUBLIC_ORIGIN === undefined) return undefined;

  let target: URL;
  try {
    // 문자열 결합이 아니라 `new URL(path, base)`이라 `PUBLIC_ORIGIN`의 끝 슬래시가
    // `//content/...` 같은 이중 슬래시를 만들지 않는다.
    target = new URL(url.pathname + url.search, env.PUBLIC_ORIGIN);
  } catch {
    return undefined;
  }
  if (target.host === LEGACY_PRODUCTION_HOST) return undefined;

  return new Response(null, { status: 301, headers: { location: target.href } });
}
