import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { CreatorPayoutApplicationsPage } from "../pages/creator-payout-applications";

// 대기(서버 기본값)는 search 에 싣지 않는다 — 내비 링크와 필터 초기화가 같은 URL 이 된다.
const creatorPayoutApplicationsSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  status: z.enum(["approved", "rejected", "revoked"]).optional().catch(undefined),
});

export const Route = createFileRoute("/creator-payout-applications")({
  validateSearch: creatorPayoutApplicationsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, status } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <CreatorPayoutApplicationsPage
      page={page}
      status={status}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onStatusChange={(nextStatus) =>
        void navigate({ search: (prev) => ({ ...prev, status: nextStatus, page: 1 }) })
      }
    />
  );
}
