import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { MyWorksPage, myWorksSearchSchema, type MyWorksSearch } from "@/pages/my-works";

export const Route = createFileRoute("/my")({
  validateSearch: myWorksSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  // `requireSession`이 세션을 라우트 컨텍스트에 실어 준다 — 컴포넌트가 마운트될 땐 이미 확정된 값이라
  // 로딩·미로그인 분기가 필요 없다.
  const { session } = Route.useRouteContext();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <MyWorksPage
      userId={session.id}
      search={search}
      // 객체 리터럴(`search: {...}`)로 넘기면 patch에 없는 필드가 URL에서 사라진다 — 항상 함수형
      // 업데이터를 쓴다(`apps/web/CLAUDE.md` "navigate search").
      onSearchChange={(patch: Partial<MyWorksSearch>) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }) })
      }
    />
  );
}
