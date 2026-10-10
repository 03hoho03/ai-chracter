import { createFileRoute } from "@tanstack/react-router";

import { CreatorPayoutDetailPage } from "../pages/creator-payout-detail";
import { requireSession } from "../entities/session";

export const Route = createFileRoute("/creator-payouts/$payoutId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { payoutId } = Route.useParams();
  return <CreatorPayoutDetailPage payoutId={payoutId} />;
}
