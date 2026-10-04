import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { useRememberListSearch } from "../shared/lib/list-search-memory/listSearchMemory";
import { UsersListPage } from "../pages/users";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`,
// contents.index.tsx 동형). `suspended`는 라우터의 기본 파서(JSON.parse 시도)가 `?suspended=true`를
// 이미 boolean으로 변환해 주므로 별도 coerce가 필요 없다 — 파싱 실패(가비지 값)는 문자열로 남아
// `z.boolean()`이 거부하고 `.catch(undefined)`가 받는다.
const usersSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  q: z.string().optional().catch(undefined),
  suspended: z.boolean().optional().catch(undefined),
  // 화면의 필터는 "전체 / 베타만" 두 값의 셀렉트다. BE가 받는 `beta=false`(미지정만)를 URL로 통과시키면
  // 셀렉트는 "전체"로 보이는데 목록은 걸러진 채라 화면과 결과가 어긋난다 — `true`만 받고 나머지는 삼킨다.
  beta: z.literal(true).optional().catch(undefined),
});

export const Route = createFileRoute("/users/")({
  validateSearch: usersSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const { page = 1, q, suspended, beta } = search;
  const navigate = Route.useNavigate();
  useRememberListSearch("/users/", search);

  return (
    <UsersListPage
      page={page}
      q={q}
      suspended={suspended}
      beta={beta}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onFilterChange={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch, page: 1 }) })}
    />
  );
}
