import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { UserDetailPage } from "../pages/user-detail";

export const Route = createFileRoute("/users/$userId/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { userId } = Route.useParams();
  return <UserDetailPage userId={userId} />;
}
