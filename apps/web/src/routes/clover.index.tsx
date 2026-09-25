import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { CloverHubPage } from "@/pages/clover-hub";

// 플랫 명명, `.index`인 이유는 형제 라우트
// `clover.history.tsx`(`/clover/history`)가 있어서다(`inquiries.index.tsx` 선례).
export const Route = createFileRoute("/clover/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: CloverHubPage,
});
