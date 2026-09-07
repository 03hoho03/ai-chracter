import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { NoticesListPage } from "../pages/notices";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`, D-21 —
// 새 admin 라우트는 이 신형을 따른다. `contents.index.tsx`·`users.index.tsx` 동형).
const noticesSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
});

export const Route = createFileRoute("/notices/")({
  validateSearch: noticesSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1 } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <NoticesListPage
      page={page}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
    />
  );
}
