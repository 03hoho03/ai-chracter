import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { ReportDetailPage } from "../pages/report-detail";

const reportSearchSchema = z.object({
  target: z.enum(["content", "comment"]).optional().catch(undefined),
});

export const Route = createFileRoute("/reports/$reportId")({
  validateSearch: reportSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { reportId } = Route.useParams();
  const { target = "content" } = Route.useSearch();
  return <ReportDetailPage reportId={reportId} target={target} />;
}
