/**
 * 앱이 실제로 그리는 경로 목록. TanStack Router의 파일 라우트(`src/routes/*.tsx`)와
 * 1:1로 대응하고, 세그먼트 표기(`$type` 같은 파라미터)도 파일명 표기를 그대로 따른다.
 *
 * 여기에 없는 경로는 404가 나가므로 **라우트를 새로 만들면 반드시 여기도 더해야 한다** —
 * 그 동기화를 지키는 유일한 방어선이 `routes.test.ts`의 파일 목록 대조 테스트다.
 */
export const KNOWN_ROUTES = [
  "/",
  "/builder",
  "/builder/$type/$draftId",
  "/builder/$type/new",
  "/chat/$roomId",
  "/chats",
  "/content/$type/$id",
  "/favorites",
  "/forgot-password",
  "/login",
  "/mypage",
  "/onboarding/google",
  "/profile/$userId",
  "/reset-password",
  "/signup",
  "/studio/images",
  "/ui-demo",
];

function matchesRoute(route: string, segments: string[]): boolean {
  const routeSegments = route.split("/");
  if (routeSegments.length !== segments.length) return false;

  return routeSegments.every((routeSegment, index) => {
    const segment = segments[index];
    // 파라미터는 아무 값이나 받되 빈 세그먼트(`/content//abc`)는 라우트가 아니다.
    return routeSegment.startsWith("$")
      ? segment !== "" && segment !== undefined
      : routeSegment === segment;
  });
}

/**
 * 앱이 그릴 수 있는 경로인지 판정한다. 순수 함수다.
 *
 * 끝 슬래시(`/mypage/`)는 다른 경로로 본다 — 같은 화면에 URL이 두 벌 생기지 않게 한다.
 */
export function isKnownRoute(pathname: string): boolean {
  const segments = pathname.split("/");
  return KNOWN_ROUTES.some((route) => matchesRoute(route, segments));
}
