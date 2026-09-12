import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { InquiryDetailPage } from "@/pages/inquiry-detail";

export const Route = createFileRoute("/inquiries/$inquiryId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { inquiryId } = Route.useParams();
  return <InquiryDetailPage inquiryId={inquiryId} />;
}
