import { createFileRoute } from "@tanstack/react-router";

import { OnboardingPage } from "@/pages/onboarding";

// 서치 파라미터가 없다 — 가입 대기 토큰은 백엔드 콜백이 HttpOnly 쿠키로 심고 온보딩 요청에 자동으로 실린다.
// 쿠키가 없거나 만료됐으면(직접 주소로 들어왔거나 다른 브라우저) 화면은 정상으로 그리고, 첫 제출에서 백엔드가
// 400을 돌려주면 위저드가 "인증이 만료되었어요. 처음부터 다시 시도해주세요."와 로그인 링크를 띄운다.
export const Route = createFileRoute("/onboarding/google")({
  component: RouteComponent,
});

function RouteComponent() {
  return <OnboardingPage provider="google" />;
}
