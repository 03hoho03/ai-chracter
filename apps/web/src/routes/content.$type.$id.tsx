import { createFileRoute } from "@tanstack/react-router";

import { isContentType } from "@/entities/content";
import { ContentDetailPage } from "@/pages/content-detail";

// techspec-content-detail.md §1 — 직접 진입(딥링크) 시에만 실제 라우터 매치, 풀페이지로 렌더링한다.
// $type은 URL 가독성을 위한 세그먼트일 뿐 조회에는 쓰이지 않는다(GET /contents/{id}가 type을 포함해 응답).
export const Route = createFileRoute("/content/$type/$id")({
  component: RouteComponent,
});

function RouteComponent() {
  const { id, type } = Route.useParams();
  // image-crop-goal-prompt.md IC-11 — $type은 위 주석대로 조회에 쓰지 않는다. hero 스켈레톤 비율
  // 힌트로만 쓰고, 어긋난 URL(예: /content/story/<캐릭터id>)이어도 스켈레톤만 잠깐 틀렸다가 실제
  // 콘텐츠 도착 시 맞는 비율로 뛴다.
  return <ContentDetailPage id={id} type={isContentType(type) ? type : "character"} />;
}
