import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { LlmCredentialsPage } from "../pages/llm-credentials";

export const Route = createFileRoute("/llm-credentials")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: LlmCredentialsPage,
});
