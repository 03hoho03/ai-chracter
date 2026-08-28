import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { LoginPage } from "../pages/login";

// 인증 흐름이지만 두 축 모두 삼켜도 되는 값이다 — `redirect`가 날아가면 로그인 후 기본 도착지(`/`)로
// 가고(`LoginForm`의 `redirectTo || "/"`), `error`가 날아가면 배너 한 줄이 안 뜰 뿐이다. 어느 쪽도
// 로그인 화면이 통째로 죽는 것보다 낫다. `validateSearch` 8곳 공통 처방.
const loginSearchSchema = z.object({
  redirect: z.string().optional().catch(undefined),
  /** 구글 콜백이 실패했을 때 BE가 붙여 보내는 코드(예: state 만료). */
  error: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/login")({
  validateSearch: loginSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { redirect, error } = Route.useSearch();
  return <LoginPage redirectTo={redirect} errorCode={error} />;
}
