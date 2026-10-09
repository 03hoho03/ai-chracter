import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { NovelBoardPage } from "@/pages/novel-board";

// 소설 편집 보드. 고른 카드·패널은 `?select=`(배치 저장 키와 같은 말 + `versions`, 없으면 고른 것 없음)이고, 고를
// 때마다 기록에 쌓인다 — 값의 꼴은 페이지가 판정한다(뒤로 가기 확인 때도 같은 판정 함수로 다음 주소를 읽는다).
// 스키마를 여기 두는 이유: 페이지 barrel 에서 가져오면 그 barrel 이 다시 내보내는 보드 화면 전체가 첫 화면 번들로
// 끌려간다. 어긋난 값은 부재(고른 것 없음)로 접는다.
const novelBoardSearchSchema = z.object({
  select: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/novels/$novelId/board")({
  validateSearch: novelBoardSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId } = Route.useParams();
  const { select } = Route.useSearch();
  return <NovelBoardPage novelId={novelId} select={select} />;
}
