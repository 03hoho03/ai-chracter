import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ContentDetailPage } from "../pages/content-detail";

export const Route = createFileRoute("/contents/$contentId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { contentId } = Route.useParams();
  return <ContentDetailPage contentId={contentId} />;
}
