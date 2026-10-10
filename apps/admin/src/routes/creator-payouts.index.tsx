import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { CreatorPayoutsListPage } from "../pages/creator-payouts";
import { requireSession } from "../entities/session";
import { useRememberListSearch } from "../shared/lib/list-search-memory/listSearchMemory";

// 처리 중(서버 기본값)은 search 에 싣지 않는다 — 내비 링크와 필터 초기화가 같은 URL 이 된다.
const creatorPayoutsSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  status: z.enum(["held", "paid", "returned"]).optional().catch(undefined),
});

export const Route = createFileRoute("/creator-payouts/")({
  validateSearch: creatorPayoutsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const { page = 1, status } = search;
  const navigate = Route.useNavigate();
  useRememberListSearch("/creator-payouts/", search);

  return (
    <CreatorPayoutsListPage
      page={page}
      status={status}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onStatusChange={(nextStatus) =>
        void navigate({ search: (prev) => ({ ...prev, status: nextStatus, page: 1 }) })
      }
    />
  );
}
