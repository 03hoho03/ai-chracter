import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { NoticeDetailPage } from "../pages/notice-detail";

export const Route = createFileRoute("/notices/$noticeId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { noticeId } = Route.useParams();
  return <NoticeDetailPage noticeId={noticeId} />;
}
