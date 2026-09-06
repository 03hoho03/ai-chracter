import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { LegalPage } from "../pages/legal";

export const Route = createFileRoute("/legal")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: LegalPage,
});
