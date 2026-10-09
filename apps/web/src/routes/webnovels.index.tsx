import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { WebnovelsPage } from "@/pages/webnovels";

// 노벨 목록. 목록·작품 정보·화 API 가 전부 로그인 회원만 받아, 비로그인은 로그인으로 보낸 뒤 이 주소로 돌아오게 한다.
// 정렬은 최신이 기본이라 파라미터의 부재로 적고 인기순만 싣는다. 스키마를 페이지 barrel 이 아니라 여기 두는 이유는
// 라우트 옵션이 쓰는 값을 페이지 barrel 에서 가져오면 페이지 전체가 첫 화면 번들로 끌려가서다.
const webnovelsSearchSchema = z.object({
  sort: z.enum(["popular"]).optional().catch(undefined),
});

export const Route = createFileRoute("/webnovels/")({
  validateSearch: webnovelsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { sort } = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <WebnovelsPage
      sort={sort ?? "latest"}
      onSortChange={(next) =>
        void navigate({ search: (prev) => ({ ...prev, sort: next === "latest" ? undefined : next }) })
      }
    />
  );
}
