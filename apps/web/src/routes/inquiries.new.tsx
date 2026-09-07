import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { InquiryNewPage } from "../pages/inquiry-new";

// techspec.md §5-2 — `new`(정적)와 `$inquiryId`(동적)가 같은 깊이에서 경합한다. TanStack Router의
// 랭킹 규칙상 정적 세그먼트가 먼저 매칭되지만, 이 저장소엔 같은 깊이의 선례가 없어 검증되지
// 않은 전제였다 — `/inquiries/new`를 직접 열어 폼이 뜨는 것을 확인했다(inquiryId === "new"로
// 상세 조회가 나가지 않는다).
export const Route = createFileRoute("/inquiries/new")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: InquiryNewPage,
});
