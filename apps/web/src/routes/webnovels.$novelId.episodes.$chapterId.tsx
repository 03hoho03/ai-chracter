import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { WebnovelEpisodePage } from "@/pages/webnovel-episode";

// 노벨 화 읽기 화면. 내 소설 화 읽기와 같은 몰입 뷰어라 전역 헤더·사이트 푸터를 숨기는 판정
// (`isGlobalHeaderHidden`·`isSiteFooterHidden`)이 이 경로도 본다.
// `edition` 은 소장자가 고른 산 때의 판이다 — 없으면 최신 판. 주소에 두어 새로고침·뒤로 가기가 고른 판을 지킨다.
// 스키마를 페이지 barrel 이 아니라 여기 두는 이유는 노벨 목록 라우트와 같다(페이지 전체가 첫 화면 번들로 끌려간다).
const webnovelEpisodeSearchSchema = z.object({
  edition: z.number().int().positive().optional().catch(undefined),
});

export const Route = createFileRoute("/webnovels/$novelId/episodes/$chapterId")({
  validateSearch: webnovelEpisodeSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId, chapterId } = Route.useParams();
  const { edition } = Route.useSearch();
  return <WebnovelEpisodePage novelId={novelId} chapterId={chapterId} edition={edition} />;
}
