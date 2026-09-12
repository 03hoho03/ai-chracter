import { createFileRoute } from "@tanstack/react-router";

import { NoticeDetailPage } from "@/pages/notice-detail";

/** 공개 라우트 — `routes/terms.tsx`처럼 `beforeLoad: requireSession`이 없다(D-5). */
export const Route = createFileRoute("/notices/$noticeId")({
  component: RouteComponent,
});

function RouteComponent() {
  const { noticeId } = Route.useParams();
  return <NoticeDetailPage noticeId={noticeId} />;
}
