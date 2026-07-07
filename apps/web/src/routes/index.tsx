import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { HomePage, type HomeSearch } from "../pages/home";

// techspec-home-discovery.md §1~2 — 정렬/장르/크리에이터/해시태그/검색어를 모두 홈 라우트의 URL search
// param으로 관리해 새로고침·공유 시에도 유지되게 한다(§1.2 헤더 검색 인라인 익스팬드도 q를 이 스키마로 갱신).
const homeSearchSchema = z.object({
  q: z.string().optional(),
  sort: z.enum(["latest", "popular", "genre"]).optional(),
  genre: z.string().optional(),
  creator: z.string().optional(),
  hashtag: z.string().optional(),
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
