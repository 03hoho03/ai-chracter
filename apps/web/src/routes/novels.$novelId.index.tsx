import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { NovelInfoPage } from "@/pages/novel-info";

// 작품 정보 화면. 채팅 경로(`/chat/$roomId/...`) 밑에 두지 않는다 — 소설은 방을 지워도 남고, 채팅 경로는 사이트
// 푸터를 끄지만 작품 정보 화면은 문서 스크롤 화면이라 푸터가 있어야 한다. 화 읽기·편집 화면이 이 경로의 자식이라
// 이 화면은 인덱스 라우트다.
//
// 페이지 모듈에서는 페이지 컴포넌트만 가져온다. 라우트 옵션(`validateSearch`·`beforeLoad`)이 쓰는 값을 페이지
// barrel 에서 가져오면 그 barrel 이 다시 내보내는 페이지 전체가 첫 화면 번들로 끌려간다.
export const Route = createFileRoute("/novels/$novelId/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { novelId } = Route.useParams();
  return <NovelInfoPage novelId={novelId} />;
}
