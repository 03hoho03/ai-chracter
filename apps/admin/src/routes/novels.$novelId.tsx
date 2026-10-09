import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { NovelDetailPage } from "../pages/novel-detail";

export const Route = createFileRoute("/novels/$novelId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId } = Route.useParams();
  return <NovelDetailPage novelId={novelId} />;
}
