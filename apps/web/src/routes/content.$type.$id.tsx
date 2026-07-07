import { createFileRoute } from "@tanstack/react-router";

import { ContentDetailPage } from "../pages/content-detail";

// techspec-content-detail.md §1 — 직접 진입(딥링크) 시에만 실제 라우터 매치, 풀페이지로 렌더링한다.
// $type은 URL 가독성을 위한 세그먼트일 뿐 조회에는 쓰이지 않는다(GET /contents/{id}가 type을 포함해 응답).
export const Route = createFileRoute("/content/$type/$id")({
  component: RouteComponent,
});

function RouteComponent() {
  const { id } = Route.useParams();
  return <ContentDetailPage id={id} />;
}
