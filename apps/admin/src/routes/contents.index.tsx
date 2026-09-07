import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { CONTENT_SORT_OPTIONS } from "../entities/admin-content";
import { requireSession } from "../entities/session";
import { ContentsListPage } from "../pages/contents";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`,
// apps/web/src/routes/login.tsx:9-13 관례).
const contentsSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  type: z.enum(["character", "story"]).optional().catch(undefined),
  visibility: z.enum(["public", "link", "private"]).optional().catch(undefined),
  moderationStatus: z.enum(["normal", "restricted", "deleted"]).optional().catch(undefined),
  q: z.string().optional().catch(undefined),
  sort: z.enum(CONTENT_SORT_OPTIONS).optional().catch(undefined),
});

export const Route = createFileRoute("/contents/")({
  validateSearch: contentsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, type, visibility, moderationStatus, q, sort } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <ContentsListPage
      page={page}
      type={type}
      visibility={visibility}
      moderationStatus={moderationStatus}
      q={q}
      sort={sort}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onFilterChange={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch, page: 1 }) })}
    />
  );
}
