import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ReportDetailPage } from "../pages/report-detail";

export const Route = createFileRoute("/reports/$reportId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { reportId } = Route.useParams();
  return <ReportDetailPage reportId={reportId} />;
}
