import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { WebnovelInfoPage } from "@/pages/webnovel-info";

// 노벨 작품 정보. 화 읽기 화면이 이 경로의 자식이라 이 화면은 인덱스 라우트다(내 소설 작품 정보와 같은 꼴).
export const Route = createFileRoute("/webnovels/$novelId/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId } = Route.useParams();
  return <WebnovelInfoPage novelId={novelId} />;
}
