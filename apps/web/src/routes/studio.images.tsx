import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { StudioImagesPage } from "../pages/studio-images";

// techspec-builder-story.md §2 — 빌더 이미지 필드 피커의 "새로 생성하기"가 새 탭으로 여는 목적지.
// 실제 생성 UX(프롬프트 입력, 결과 개수 등)는 별도 범위(§4 Open Items)라 아직 스텁이다.
export const Route = createFileRoute("/studio/images")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: StudioImagesPage,
});
