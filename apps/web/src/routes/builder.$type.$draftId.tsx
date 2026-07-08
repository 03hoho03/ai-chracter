import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { BuilderPage } from "../pages/builder";

// techspec-builder-common.md §2 — 마이페이지 초안 카드가 이동하는 목적지. $type은 URL 가독성을 위한
// 세그먼트일 뿐 조회에는 쓰이지 않는다(content.$type.$id.tsx와 동일 원칙) — GET /contents/{id}/draft
// 응답 자체의 type 판별값으로 캐릭터/스토리 빌더를 나눈다.
export const Route = createFileRoute("/builder/$type/$draftId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { draftId } = Route.useParams();
  return <BuilderPage draftId={draftId} />;
}
