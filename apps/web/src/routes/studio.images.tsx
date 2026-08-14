import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { StudioImagesPage } from "@/pages/studio-images";

// prd-image-library US-003 — 선택 탭은 URL search param(?tab=)으로 관리해 새로고침/뒤로가기에도
// 유지한다. 생략 시 '생성' 탭: 헤더 진입점(아이콘 "이미지 생성")과 빌더 피커의 "새로 생성하기"
// 링크가 param 없이 도착하므로 진입 의도와 일치한다.
const studioImagesSearchSchema = z.object({
  tab: z.enum(["generate", "library"]).optional(),
});

export const Route = createFileRoute("/studio/images")({
  validateSearch: studioImagesSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { tab = "generate" } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <StudioImagesPage
      tab={tab}
      onTabChange={(nextTab) => void navigate({ search: (prev) => ({ ...prev, tab: nextTab }) })}
    />
  );
}
