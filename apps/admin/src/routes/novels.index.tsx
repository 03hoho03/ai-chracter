import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { NOVEL_MODERATION_STATUS_VALUES } from "../entities/admin-novel";
import { requireSession } from "../entities/session";
import { useRememberListSearch } from "../shared/lib/list-search-memory/listSearchMemory";
import { NovelsListPage } from "../pages/novels";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`). 상태 값은 entities 가 라벨 Record 키에서
// 도출한 목록이라 서버에 상태가 늘면 함께 늘어난다.
const novelsSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  moderationStatus: z.enum(NOVEL_MODERATION_STATUS_VALUES).optional().catch(undefined),
});

export const Route = createFileRoute("/novels/")({
  validateSearch: novelsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const { page = 1, moderationStatus } = search;
  const navigate = Route.useNavigate();
  useRememberListSearch("/novels/", search);

  return (
    <NovelsListPage
      page={page}
      moderationStatus={moderationStatus}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onModerationStatusChange={(next) => void navigate({ search: (prev) => ({ ...prev, moderationStatus: next, page: 1 }) })}
    />
  );
}
