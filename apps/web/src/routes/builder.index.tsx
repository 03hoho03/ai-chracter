import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { BuilderTypeSelectPage } from "@/pages/builder";

export const Route = createFileRoute("/builder/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: BuilderTypeSelectPage,
});
