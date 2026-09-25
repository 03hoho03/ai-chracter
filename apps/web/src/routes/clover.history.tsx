import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { CloverHistoryPage, cloverHistorySearchSchema, type CloverHistorySearch } from "@/pages/clover-history";

// 플랫 명명, `inquiries.index.tsx`/`clover.index.tsx` 선례.
// 탭 상태는 URL 검색 파라미터(`?tab=`)로 둔다.
export const Route = createFileRoute("/clover/history")({
  validateSearch: cloverHistorySearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <CloverHistoryPage
      search={search}
      // 객체 리터럴로 넘기면 patch에 없는 필드가 URL에서 사라진다 — 항상 함수형 업데이터
      // (`apps/web/CLAUDE.md` "navigate search", `/my` 선례).
      onSearchChange={(patch: Partial<CloverHistorySearch>) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }) })
      }
    />
  );
}
