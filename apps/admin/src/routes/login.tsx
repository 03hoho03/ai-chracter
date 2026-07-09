import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { LoginPage } from "../pages/login";

const loginSearchSchema = z.object({
  redirect: z.string().optional(),
});

export const Route = createFileRoute("/login")({
  validateSearch: loginSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { redirect } = Route.useSearch();
  return <LoginPage redirectTo={redirect} />;
}
