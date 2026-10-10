import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { BuilderPage, NEW_DRAFT_SEGMENT } from "@/pages/builder";

// 초안 만들기(`/builder/$type/new`)와 이어쓰기(`/builder/$type/{id}`)를
// 한 라우트가 받는다. `new`를 별도 정적 라우트로 두지 않는 이유는 `NEW_DRAFT_SEGMENT`의 주석에 있다
// (라우트가 갈리면 첫 자동저장의 URL 교체가 빌더를 리마운트한다).
//
// $type은 URL 가독성을 위한 세그먼트일 뿐 조회에는 쓰이지 않는다(content.$type.$id.tsx와 동일 원칙)
// — GET /contents/{id}/draft 응답 자체의 type 판별값으로 캐릭터/스토리 빌더를 나눈다. 아직 초안이
// 없을 때의 로컬 초기값을 고를 때만 이 값을 쓴다.
//
// 보던 탭은 `?tab=` 이라 새로고침해도 그 탭으로 돌아온다. 두 빌더가 이 라우트를 함께 쓰므로 스키마는 아무 문자열이나
// 받고, 그 빌더에 없는 탭 id 는 빌더가 기본 탭으로 접는다. 기본 탭(프로필)은 파라미터의 부재다. 탭 전환은 기록을 쌓지
// 않고 주소를 바꾼다 — 뒤로 가기는 탭이 아니라 빌더 밖으로 간다. 창 스크롤은 건드리지 않는다(라우터는 서치만 바뀐
// 이동에도 창을 맨 위로 올린다).
const builderSearchSchema = z.object({
  tab: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/builder/$type/$draftId")({
  validateSearch: builderSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { type, draftId } = Route.useParams();
  const { tab } = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <BuilderPage
      type={type === "story" ? "story" : "character"}
      draftId={draftId === NEW_DRAFT_SEGMENT ? undefined : draftId}
      tab={tab}
      onTabChange={(nextTab) =>
        void navigate({ search: (prev) => ({ ...prev, tab: nextTab }), replace: true, resetScroll: false })
      }
    />
  );
}
