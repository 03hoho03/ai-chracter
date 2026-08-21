import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { BuilderPage, NEW_DRAFT_SEGMENT } from "@/pages/builder";

// techspec-builder-common.md §2 — 초안 만들기(`/builder/$type/new`)와 이어쓰기(`/builder/$type/{id}`)를
// 한 라우트가 받는다. `new`를 별도 정적 라우트로 두지 않는 이유는 `NEW_DRAFT_SEGMENT`의 주석에 있다
// (US-007 — 라우트가 갈리면 첫 자동저장의 URL 교체가 빌더를 리마운트한다).
//
// $type은 URL 가독성을 위한 세그먼트일 뿐 조회에는 쓰이지 않는다(content.$type.$id.tsx와 동일 원칙)
// — GET /contents/{id}/draft 응답 자체의 type 판별값으로 캐릭터/스토리 빌더를 나눈다. 아직 초안이
// 없을 때의 로컬 초기값을 고를 때만 이 값을 쓴다.
export const Route = createFileRoute("/builder/$type/$draftId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { type, draftId } = Route.useParams();
  return (
    <BuilderPage
      type={type === "story" ? "story" : "character"}
      draftId={draftId === NEW_DRAFT_SEGMENT ? null : draftId}
    />
  );
}
