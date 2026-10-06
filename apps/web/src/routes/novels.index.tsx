import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "@/entities/session";
import { NovelsPage } from "@/pages/novels";

// 목록은 `.index.tsx`로 둔다 — `novels.tsx`로 두면 `novels.$novelId.tsx`가 그 자식으로 중첩돼 URL만 바뀌고
// 화면은 목록이 그대로 보인다(`inquiries.index.tsx`와 같은 이유).
// 허용 여부는 여기서 막지 않는다. 서버의 403 을 받아 페이지가 잠김 안내를 그린다(다른 곳으로 보내지 않는다).
export const Route = createFileRoute("/novels/")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: NovelsPage,
});
