import { createFileRoute } from "@tanstack/react-router";

import { toHomeTypeSwitchSearch } from "@/entities/content";
import { HomePage, homeSearchSchema, type HomeSearch } from "@/pages/home";

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
      // 유형 전환은 병합이 아니라 교체다 — 정렬만 들고 가고 나머지 축은 버린다(`toHomeTypeSwitchSearch`).
      onTypeChange={(type) => void navigate({ search: (prev) => toHomeTypeSwitchSearch(type, prev.sort) })}
    />
  );
}
