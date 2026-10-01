import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { LOGIN_ERROR_CODES, SIGNUP_METHODS, UNKNOWN_LOGIN_ERROR } from "@/features/login";
import { LoginPage } from "@/pages/login";

// 인증 흐름이지만 세 축 모두 삼켜도 되는 값이다 — `redirect`가 날아가면 로그인 후 기본 도착지(`/`)로
// 가고(`LoginForm`의 `redirectTo || "/"`), `error`·`method`가 날아가면 배너 한 줄이 덜 정확해질 뿐이다.
// 어느 쪽도 로그인 화면이 통째로 죽는 것보다 낫다. `validateSearch` 8곳 공통 처방.
const loginSearchSchema = z.object({
  redirect: z.string().optional().catch(undefined),
  /** 소셜 로그인 콜백이 실패했을 때 백엔드가 붙여 보내는 코드. 목록 밖의 값은 없던 일로 지우지 않고
   * `UNKNOWN_LOGIN_ERROR`로 접는다 — 실패해서 돌아온 사용자에게 아무 말도 안 하는 것보다 일반 오류 문구가 낫다. */
  error: z.enum([...LOGIN_ERROR_CODES, UNKNOWN_LOGIN_ERROR]).optional().catch(UNKNOWN_LOGIN_ERROR),
  /** `*_email_taken`과 함께 오는, 같은 이메일이 이미 가입된 방법. 빠지면 방법을 특정하지 않는 문구가 뜬다. */
  method: z.enum(SIGNUP_METHODS).optional().catch(undefined),
});

export const Route = createFileRoute("/login")({
  validateSearch: loginSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { redirect, error, method } = Route.useSearch();
  return <LoginPage redirectTo={redirect} errorCode={error} errorMethod={method} />;
}
