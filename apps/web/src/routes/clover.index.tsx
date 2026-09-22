import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { CloverHubPage } from "@/pages/clover-hub";

// clover-page-goal-prompt.md CE-24 — 플랫 명명, `.index`인 이유는 S7이 형제 라우트
// `clover.history.tsx`(`/clover/history`)를 추가할 예정이라서다(`inquiries.index.tsx` 선례).
export const Route = createFileRoute("/clover/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: CloverHubPage,
});
