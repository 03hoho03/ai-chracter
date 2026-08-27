import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { OnboardingGooglePage } from "../pages/onboarding-google";

// 토큰에는 기본값이 없어 부재(`undefined`)가 아니라 빈 문자열로 떨어뜨린다 — 삼키는 게 아니라
// "토큰 없음"으로 정규화해 실패를 그대로 드러내는 쪽이다. 첫 스텝 제출에서 BE가 400을 돌려주고
// 위저드가 "인증이 만료되었어요. 처음부터 다시 시도해주세요."를 띄운다(`OnboardingGoogleWizard`) —
// 페이지가 통째로 죽는 것과 달리 사용자가 무엇을 해야 하는지 알 수 있다. `validateSearch` 8곳 공통 처방.
const onboardingGoogleSearchSchema = z.object({
  token: z.string().catch(""),
});

export const Route = createFileRoute("/onboarding/google")({
  validateSearch: onboardingGoogleSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { token } = Route.useSearch();
  return <OnboardingGooglePage token={token} />;
}
