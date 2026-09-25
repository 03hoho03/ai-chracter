import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { IMAGE_GENERATION_STATUS_VALUES, IMAGE_STYLE_VALUES } from "../entities/admin-image-generation";
import { requireSession } from "../entities/session";
import { ImageGenerationsListPage } from "../pages/image-generations";

const isoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다(`.optional().catch(undefined)`,
// `contents.index.tsx` 동형). 멤버는 entities가 Record 키에서 도출한 목록을 그대로 쓴다 — 여기
// 손으로 또 적으면 서버에 값이 늘어도 이 라우트만 조용히 걸러낸다.
const imageGenerationsSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  q: z.string().optional().catch(undefined),
  status: z.enum(IMAGE_GENERATION_STATUS_VALUES).optional().catch(undefined),
  style: z.enum(IMAGE_STYLE_VALUES).optional().catch(undefined),
  from: isoDateSchema.optional().catch(undefined),
  to: isoDateSchema.optional().catch(undefined),
});

// apps/admin/CLAUDE.md — 목록과 상세를 형제로 두려면
// `.index.tsx`여야 한다. 옆에 `image-generations.tsx`를 두면 상세가 자식으로 중첩돼 URL만
// 바뀌고 화면이 그대로인 조용한 실패가 난다. 열람 화면(유저 단위)은 `users.$userId.image-generations.tsx`다.
export const Route = createFileRoute("/image-generations/")({
  validateSearch: imageGenerationsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, q, status, style, from, to } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <ImageGenerationsListPage
      page={page}
      q={q}
      status={status}
      style={style}
      from={from}
      to={to}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onFilterChange={(patch) => void navigate({ search: (prev) => ({ ...prev, ...patch, page: 1 }) })}
    />
  );
}
