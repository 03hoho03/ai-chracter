import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { InquiriesPage } from "../pages/inquiries";

// techspec.md §5-2 — 목록은 `.index.tsx`로 둔다. `inquiries.tsx` 옆에 `inquiries.$inquiryId.tsx`를
// 두면 상세가 자식으로 중첩돼 URL만 바뀌고 화면은 부모가 그대로 보인다(조용한 실패,
// `apps/web/CLAUDE.md` §아키텍처/라우팅).
export const Route = createFileRoute("/inquiries/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: InquiriesPage,
});
