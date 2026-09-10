import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { PromptSetsPage } from "../pages/prompt-sets";

export const Route = createFileRoute("/prompt-sets")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: PromptSetsPage,
});
