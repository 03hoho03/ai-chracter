import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { MyWorksPage } from "@/pages/my-works";

export const Route = createFileRoute("/my")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  // `requireSession`이 세션을 라우트 컨텍스트에 실어 준다 — 컴포넌트가 마운트될 땐 이미 확정된 값이라
  // 로딩·미로그인 분기가 필요 없다.
  const { session } = Route.useRouteContext();

  return <MyWorksPage userId={session.id} />;
}
