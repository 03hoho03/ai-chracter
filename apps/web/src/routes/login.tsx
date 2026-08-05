import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { LoginPage } from "../pages/login";

const loginSearchSchema = z.object({
  redirect: z.string().optional(),
  /** 구글 콜백이 실패했을 때 BE가 붙여 보내는 코드(예: state 만료). */
  error: z.string().optional(),
});

export const Route = createFileRoute("/login")({
  validateSearch: loginSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { redirect, error } = Route.useSearch();
  return <LoginPage redirectTo={redirect} errorCode={error} />;
}
