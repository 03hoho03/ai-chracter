import { createFileRoute } from "@tanstack/react-router";

import { OnboardingPage } from "@/pages/onboarding";

// 서치 파라미터가 없다 — 가입 대기 토큰은 백엔드 콜백이 HttpOnly 쿠키로 심고 온보딩 요청에 자동으로 실린다.
// 쿠키가 없거나 만료됐으면 첫 제출의 400에서 위저드가 만료 안내와 로그인 링크를 띄운다(구글 온보딩과 같다).
// 동적 `$provider` 라우트로 합치지 않은 이유: 그러면 `/onboarding/아무거나`도 알려진 경로가 되어 페이지가
// 제공자 검증과 404를 따로 맡아야 한다. 정적 파일 둘이 더 단순하다.
export const Route = createFileRoute("/onboarding/kakao")({
  component: RouteComponent,
});

function RouteComponent() {
  return <OnboardingPage provider="kakao" />;
}
