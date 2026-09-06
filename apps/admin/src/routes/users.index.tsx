import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { UsersListPage } from "../pages/users";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`,
// contents.index.tsx 동형). `suspended`는 라우터의 기본 파서(JSON.parse 시도)가 `?suspended=true`를
// 이미 boolean으로 변환해 주므로 별도 coerce가 필요 없다 — 파싱 실패(가비지 값)는 문자열로 남아
// `z.boolean()`이 거부하고 `.catch(undefined)`가 받는다.
const usersSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  q: z.string().optional().catch(undefined),
  suspended: z.boolean().optional().catch(undefined),
});

export const Route = createFileRoute("/users/")({
  validateSearch: usersSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, q, suspended } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <UsersListPage
      page={page}
      q={q}
      suspended={suspended}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onFilterChange={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch, page: 1 }) })}
    />
  );
}
