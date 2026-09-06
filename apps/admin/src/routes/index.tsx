import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { DashboardPage } from "../pages/dashboard";

export const Route = createFileRoute("/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: DashboardPage,
});
