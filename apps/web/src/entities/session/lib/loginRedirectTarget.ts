/** 로그인·가입·온보딩·비밀번호 찾기·재설정 화면. 여기서 로그인 링크가 현재 주소를 `redirect` 로 넘기면 로그인 뒤 다시
 * 그 화면으로 돌아온다 — 재설정 화면은 주소에 재설정 토큰을 들고 있어, 넘기면 토큰이 로그인 화면 주소와 방문 기록으로
 * 옮겨 간다. */
const AUTH_FLOW_PATH = /^\/(?:login|signup|forgot-password|reset-password|onboarding\/[^/]+)$/;

type LoginRedirectLocation = {
  pathname: string;
  href: string;
  search: Record<string, unknown>;
};

/** 로그인 링크에 실을 `redirect` 값. 보통은 지금 주소로 돌아오게 하고, 인증 흐름 화면에서는 그 화면이 이미 들고 있는
 * `redirect` 를 그대로 잇는다(없으면 넘기지 않아 로그인 뒤 기본 도착지로 간다). */
export function loginRedirectTarget({ pathname, href, search }: LoginRedirectLocation): string | undefined {
  if (!AUTH_FLOW_PATH.test(pathname)) return href;
  return typeof search.redirect === "string" ? search.redirect : undefined;
}
