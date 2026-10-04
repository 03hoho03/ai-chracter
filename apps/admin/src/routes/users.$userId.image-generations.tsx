import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { ImageGenerationViewPage } from "../pages/image-generation-view";

// 전역 이미지 생성 목록에서 들어왔다는 표시. 라우터 state 가 아니라 URL 에 두어 새 탭·새로고침에서도 내비 활성 항목과
// "목록으로" 행선지가 같게 난다. 다른 값은 표시 없음으로 삼킨다.
const imageGenerationViewSearchSchema = z.object({
  from: z.enum(["image-generations"]).optional().catch(undefined),
});

export const Route = createFileRoute("/users/$userId/image-generations")({
  validateSearch: imageGenerationViewSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { userId } = Route.useParams();
  const { from } = Route.useSearch();
  return <ImageGenerationViewPage userId={userId} isFromImageGenerations={from === "image-generations"} />;
}
