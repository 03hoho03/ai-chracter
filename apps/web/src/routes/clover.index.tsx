import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { resolvePaymentRedirect } from "@/features/purchase-clover";
import { CloverHubPage, cloverHubSearchSchema } from "@/pages/clover-hub";

// 플랫 명명, `.index`인 이유는 형제 라우트
// `clover.history.tsx`(`/clover/history`)가 있어서다(`inquiries.index.tsx` 선례).
// 결제창이 페이지를 떠났다가 돌아오는 곳이 이 화면이라 그 결과 쿼리를 서치 파라미터로 받는다. 주소에 담긴 상품
// 키(`product`)도 서치 파라미터로 받는다.
//
// 로그인 없이 열린다(상품과 구매 조건은 누구나 본다). 단 결제창이 성공으로 닫혀 돌아왔는데 세션이 없으면(결제하는
// 사이 만료) 확정을 요청하기 전에 로그인으로 보낸다 — 로그인 redirect 가 결과 쿼리를 포함한 주소를 싣고 있어 로그인한
// 뒤 같은 결제를 이어서 확정한다. 그대로 두면 확정 요청이 401 로 끝나 결과를 잃는다.
export const Route = createFileRoute("/clover/")({
  validateSearch: cloverHubSearchSchema,
  beforeLoad: async ({ context, location, search }) => {
    if (resolvePaymentRedirect(search).kind === "complete") await requireSession(context.queryClient, location.href);
  },
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <CloverHubPage
      search={search}
      // 처리한 결제 결과 쿼리를 지운다. `replace`라 뒤로가기로 같은 결제를 다시 확정하러 오지 않는다. 이 화면의
      // 서치 파라미터가 결제 결과만이 아니게 됐으므로 두 지우기 모두 자기 파라미터만 빼는 함수형 업데이터다 — 객체
      // 리터럴(`search: {}`)은 다른 쪽 파라미터까지 지운다.
      onSearchClear={() =>
        void navigate({ search: (prev) => ({ ...prev, paymentId: undefined, code: undefined }), replace: true })
      }
      // 구매 확인을 연 뒤 고른 상품 키를 지운다. 새로고침·뒤로가기로 같은 창이 다시 열리지 않게 `replace`다.
      onProductClear={() => void navigate({ search: (prev) => ({ ...prev, product: undefined }), replace: true })}
    />
  );
}
