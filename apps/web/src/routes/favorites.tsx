import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { FavoritesPage, type FavoritesSearch } from "../pages/favorites";

// card-grid-goal-prompt.md D-6 — 그리드가 항상 단일 타입이어야 해서(D-5) 타입 필터 상태를 URL에 싣는다.
// `routes/profile.$userId.tsx`의 `profileSearchSchema`와 같은 패턴이다. 모르는 값은 그 축만 기본값
// (= 파라미터의 부재)으로 흘려보낸다 — `validateSearch` 8곳 공통 처방.
const favoritesSearchSchema = z.object({
  type: z.enum(["character", "story"]).optional().catch(undefined),
});

export const Route = createFileRoute("/favorites")({
  validateSearch: favoritesSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <FavoritesPage
      search={search}
      onSearchChange={(patch: Partial<FavoritesSearch>) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }) })
      }
    />
  );
}
