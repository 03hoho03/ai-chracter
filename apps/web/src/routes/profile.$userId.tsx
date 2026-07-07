import { createFileRoute } from "@tanstack/react-router";

import { ProfilePage } from "../pages/profile";

// techspec-global-nav-profile.md §3 — 본인/타인 조회 모두 같은 라우트를 쓰고, 로그인 여부와 무관하게 열람 가능하다.
export const Route = createFileRoute("/profile/$userId")({
  component: RouteComponent,
});

function RouteComponent() {
  const { userId } = Route.useParams();
  return <ProfilePage userId={userId} />;
}
