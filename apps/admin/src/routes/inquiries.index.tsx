import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { InquiriesListPage } from "../pages/inquiries";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`, D-21 —
// 새 admin 라우트는 이 신형을 따른다. `notices.index.tsx` 동형).
const inquiriesSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  status: z.enum(["pending", "answered"]).optional().catch(undefined),
  category: z.enum(["account", "bug", "content", "suggestion", "other"]).optional().catch(undefined),
});

export const Route = createFileRoute("/inquiries/")({
  validateSearch: inquiriesSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, status, category } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <InquiriesListPage
      page={page}
      status={status}
      category={category}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onStatusChange={(nextStatus) =>
        void navigate({ search: (prev) => ({ ...prev, status: nextStatus, page: 1 }) })
      }
      onCategoryChange={(nextCategory) =>
        void navigate({ search: (prev) => ({ ...prev, category: nextCategory, page: 1 }) })
      }
    />
  );
}
