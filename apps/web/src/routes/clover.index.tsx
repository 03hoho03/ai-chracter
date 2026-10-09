import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { CloverHubPage, cloverHubSearchSchema } from "@/pages/clover-hub";

// 플랫 명명, `.index`인 이유는 형제 라우트
// `clover.history.tsx`(`/clover/history`)가 있어서다(`inquiries.index.tsx` 선례).
// 결제창이 페이지를 떠났다가 돌아오는 곳이 이 허브라 그 결과 쿼리를 서치 파라미터로 받는다.
export const Route = createFileRoute("/clover/")({
  validateSearch: cloverHubSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <CloverHubPage
      search={search}
      // 처리한 결제 결과 쿼리를 지운다. 이 화면의 서치 파라미터는 그 결과뿐이라 통째로 비운다. `replace`라 뒤로가기로
      // 같은 결제를 다시 확정하러 오지 않는다.
      onSearchClear={() => void navigate({ search: {}, replace: true })}
    />
  );
}
