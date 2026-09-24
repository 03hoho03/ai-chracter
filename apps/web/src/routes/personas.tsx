import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { PersonasPage } from "@/pages/personas";

export const Route = createFileRoute("/personas")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: PersonasPage,
});
