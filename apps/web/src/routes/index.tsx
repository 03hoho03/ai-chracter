import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { HomePage, type HomeSearch } from "../pages/home";

// techspec-home-discovery.md §1~2 — 정렬/장르/크리에이터/해시태그/검색어를 모두 홈 라우트의 URL search
// param으로 관리해 새로고침·공유 시에도 유지되게 한다(§1.2 헤더 검색 인라인 익스팬드도 q를 이 스키마로 갱신).
// 모든 필드는 `.catch(undefined)`로 끝난다 — 모르는 값(오래된 링크·손으로 고친 URL)이 와도 그 축만
// 기본값(= 파라미터의 부재)으로 떨어지고 페이지는 렌더된다. `validateSearch` 스키마 8곳이 전부 같은
// 처방을 쓴다(`apps/web/CLAUDE.md`).
const homeSearchSchema = z.object({
  q: z.string().optional().catch(undefined),
  sort: z.enum(["latest", "popular", "genre"]).optional().catch(undefined),
  genre: z.string().optional().catch(undefined),
  creator: z.string().optional().catch(undefined),
  hashtag: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/")({
  validateSearch: homeSearchSchema,
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <HomePage
      search={search}
      onSearchChange={(patch: Partial<HomeSearch>) => void navigate({ search: (prev) => ({ ...prev, ...patch }) })}
    />
  );
}
