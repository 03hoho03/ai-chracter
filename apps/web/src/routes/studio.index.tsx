import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { StudioPage, studioSearchSchema, type StudioSearch } from "@/pages/studio";

// 파일 이름이 `studio.tsx` 가 아니라 `studio.index.tsx` 인 이유: `studio.tsx` 는 `/studio/images` 의 부모 레이아웃이
// 돼 이미지 스튜디오가 그 안에 그려진다. 인덱스 라우트는 이미지 스튜디오의 형제라 그쪽 경로·크롬 판정이 그대로다.
export const Route = createFileRoute("/studio/")({
  validateSearch: studioSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  // `requireSession` 이 실어 준 세션이라 마운트 때 이미 확정돼 있다. 계정 id 만 여기서 쓴다 — 소설 영역 표시 판정은
  // 다시 받은 세션을 따라가야 해서 페이지가 세션 조회에서 직접 읽는다.
  const { session } = Route.useRouteContext();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <StudioPage
      userId={session.id}
      search={search}
      // 객체 리터럴로 넘기면 patch 에 없는 필드가 주소에서 사라진다 — 항상 함수형 업데이터를 쓴다.
      onSearchChange={(patch: Partial<StudioSearch>) => void navigate({ search: (prev) => ({ ...prev, ...patch }) })}
    />
  );
}
