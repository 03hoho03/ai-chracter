import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { NovelEpisodePage } from "@/pages/novel-episode";

// 화 읽기 화면. 전역 헤더·사이트 푸터를 숨기는 판정은 `isGlobalHeaderHidden`·`isSiteFooterHidden` 이 이 경로를 보고
// 한다.
export const Route = createFileRoute("/novels/$novelId/episodes/$chapterId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId, chapterId } = Route.useParams();
  return <NovelEpisodePage novelId={novelId} chapterId={chapterId} />;
}
