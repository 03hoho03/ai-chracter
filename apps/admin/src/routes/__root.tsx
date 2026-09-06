import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet, useRouterState } from "@tanstack/react-router";

import { DeleteConfirmModal } from "../features/act-on-report";
import { ContentActionConfirmModal } from "../pages/content-detail";
import { AdminSidebar } from "../widgets/admin-sidebar";

export type RouterContext = {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});

// `/login`은 세션이 없는 유일한 비보호 라우트라 사이드바(세션 정보·로그아웃)를 그릴 수 없다.
// 라우트 파일을 pathless layout으로 쪼개는 대신 현재 경로로 분기한다.
function RootComponent() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isLoginPage = pathname === "/login";

  return (
    <>
      {isLoginPage ? (
        <Outlet />
      ) : (
        <div className="flex min-h-screen">
          <AdminSidebar />
          <div className="min-w-0 flex-1">
            <Outlet />
          </div>
        </div>
      )}
      <DeleteConfirmModal />
      <ContentActionConfirmModal />
    </>
  );
}
