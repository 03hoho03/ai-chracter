import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { CreatorPayoutPage } from "@/pages/creator-payout";

// 정산 스위치가 꺼져 있어도 여기서 막지 않는다. 진입점(프로필 메뉴)이 숨고, 주소로 직접 오면 서버의 503 을 받아 페이지가
// "이용할 수 없어요"를 그린다(`/novels` 와 같은 방식).
export const Route = createFileRoute("/creator-payout")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: CreatorPayoutPage,
});
