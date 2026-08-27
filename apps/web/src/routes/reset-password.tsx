import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { validatePasswordResetToken } from "../features/reset-password";
import { ResetPasswordPage } from "../pages/reset-password";

// 토큰에는 기본값이 없어 부재(`undefined`)가 아니라 빈 문자열로 떨어뜨린다 — 삼키는 게 아니라
// "토큰 없음"으로 정규화해 실패를 그대로 드러내는 쪽이다. 아래 loader의
// `validatePasswordResetToken("")`이 400을 받아 `isTokenValid: false`가 되고, 페이지가 폼 대신
// "링크가 만료되었어요" + 재요청 버튼을 그린다. `validateSearch` 8곳 공통 처방.
const resetPasswordSearchSchema = z.object({
  token: z.string().catch(""),
});

export const Route = createFileRoute("/reset-password")({
  validateSearch: resetPasswordSearchSchema,
  loaderDeps: ({ search }) => ({ token: search.token }),
  loader: async ({ deps }) => ({ isTokenValid: await validatePasswordResetToken(deps.token) }),
  component: RouteComponent,
});

function RouteComponent() {
  const { token } = Route.useSearch();
  const { isTokenValid } = Route.useLoaderData();
  return <ResetPasswordPage token={token} isTokenValid={isTokenValid} />;
}
