import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { HomePage } from "../pages/home";

export const Route = createFileRoute("/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: HomePage,
});
