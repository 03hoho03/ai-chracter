import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { MyPagePage, mypageSearchSchema } from "@/pages/mypage";

// 본인인증창이 페이지를 떠났다가 돌아오는 곳이 여기라 그 결과 쿼리를 서치 파라미터로 받는다.
export const Route = createFileRoute("/mypage")({
  validateSearch: mypageSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <MyPagePage
      search={search}
      // 처리한 인증 결과 쿼리를 지운다. 이 화면의 서치 파라미터는 그 결과뿐이라 통째로 비운다. `replace`라 뒤로가기로
      // 같은 인증을 다시 저장하러 오지 않는다.
      onSearchClear={() => void navigate({ search: {}, replace: true })}
    />
  );
}
