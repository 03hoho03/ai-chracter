import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { validatePasswordResetToken } from "../features/reset-password";
import { ResetPasswordPage } from "../pages/reset-password";

const resetPasswordSearchSchema = z.object({
  token: z.string(),
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
