import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { NovelPage, novelSearchSchema } from "@/pages/novel";

// 채팅 경로(`/chat/$roomId/...`) 밑에 두지 않는다 — 소설은 방을 지워도 남고, 채팅 경로는 사이트 푸터를 끄지만
// 소설은 문서 스크롤 화면이라 푸터가 있어야 한다.
export const Route = createFileRoute("/novels/$novelId")({
  validateSearch: novelSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId } = Route.useParams();
  const { chapter } = Route.useSearch();
  return <NovelPage novelId={novelId} chapter={chapter} />;
}
