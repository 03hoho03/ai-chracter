import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { MyPagePage } from "../pages/mypage";

export const Route = createFileRoute("/mypage")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: MyPagePage,
});
