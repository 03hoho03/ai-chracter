import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { WebnovelEpisodePage } from "@/pages/webnovel-episode";

// 노벨 화 읽기 화면. 내 소설 화 읽기와 같은 몰입 뷰어라 전역 헤더·사이트 푸터를 숨기는 판정
// (`isGlobalHeaderHidden`·`isSiteFooterHidden`)이 이 경로도 본다.
export const Route = createFileRoute("/webnovels/$novelId/episodes/$chapterId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId, chapterId } = Route.useParams();
  return <WebnovelEpisodePage novelId={novelId} chapterId={chapterId} />;
}
