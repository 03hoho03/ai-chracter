import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { PromptRoutingPage } from "../pages/prompt-routing";

export const Route = createFileRoute("/prompt-routing")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: PromptRoutingPage,
});
