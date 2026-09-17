import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ImageGenerationViewPage } from "../pages/image-generation-view";

export const Route = createFileRoute("/users/$userId/image-generations")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { userId } = Route.useParams();
  return <ImageGenerationViewPage userId={userId} />;
}
