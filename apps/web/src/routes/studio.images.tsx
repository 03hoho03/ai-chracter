import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "@/entities/session";
import { StudioImagesPage } from "@/pages/studio-images";
import { IMAGE_STUDIO_TABS } from "@/widgets/image-studio";

// 선택 탭은 URL search param(?tab=)으로 관리해 새로고침/뒤로가기에도
// 유지한다. 생략 시 '생성' 탭: 좌측 패널(좁은 화면은 드로어)의 "이미지 생성" 링크와 빌더 피커의 "새로 생성하기"
// 링크가 param 없이 도착하므로 진입 의도와 일치한다.
// 탭 값은 지금 generate 하나다(library는 탭이 아니다). 모르는 값은 그 축만 기본값(= 파라미터의
// 부재)으로 흘려보낸다 — 예전에 있던 `?tab=transform`·`?tab=inpaint` 주소도 enum 밖이라
// .catch(undefined)가 받아 생성 탭으로 연다. `validateSearch` 8곳 공통 처방이라 이 모양을 유지한다.
const studioImagesSearchSchema = z.object({
  tab: z.enum(IMAGE_STUDIO_TABS).optional().catch(undefined),
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
