import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { ProfilePage } from "../pages/profile";

// techspec-global-nav-profile.md §3.2 — 작품 목록 유형 토글은 헤더의 전역 atom과 별개로 URL search
// param(?type=)으로 관리한다(새로고침/공유 시에도 선택 상태 유지). 생략 시 기본값은 "character".
const profileSearchSchema = z.object({
  type: z.enum(["character", "story"]).optional(),
});

// techspec-global-nav-profile.md §3 — 본인/타인 조회 모두 같은 라우트를 쓰고, 로그인 여부와 무관하게 열람 가능하다.
export const Route = createFileRoute("/profile/$userId")({
  validateSearch: profileSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const { userId } = Route.useParams();
  const { type = "character" } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <ProfilePage
      userId={userId}
      contentType={type}
      onContentTypeChange={(nextType) => void navigate({ search: { type: nextType } })}
    />
  );
}
