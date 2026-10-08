import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { NovelPage } from "@/pages/novel";

// 소설 편집 화면. 화 하나씩 보이며 어느 화인지는 `?chapter=<화 번호>`(없으면 마지막 화)다 — 페이지가 같은 키를
// 자기 모델 스키마로 다시 읽는다(뒤로 가기 확인). 스키마를 여기 두는 이유: 페이지 barrel 에서 가져오면 그 barrel 이
// 다시 내보내는 편집 화면 전체가 첫 화면 번들로 끌려간다. 어긋난 값은 부재(마지막 화)로 접는다.
const novelBoardSearchSchema = z.object({
  chapter: z.number().int().positive().optional().catch(undefined),
});

export const Route = createFileRoute("/novels/$novelId/board")({
  validateSearch: novelBoardSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId } = Route.useParams();
  const { chapter } = Route.useSearch();
  return <NovelPage novelId={novelId} chapter={chapter} />;
}
