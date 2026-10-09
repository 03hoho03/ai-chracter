import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet, useRouterState } from "@tanstack/react-router";

import { NovelCommentDeleteConfirmModal } from "../features/act-on-novel-comment-report";
import { DeleteConfirmModal, LiftRestrictionConfirmModal } from "../features/act-on-report";
import { ApproveApplicationModal, DecisionReasonModal } from "../features/decide-creator-payout-application";
import { ContentActionConfirmModal, HomeCurationConfirmModal } from "../pages/content-detail";
import { PublishDialog } from "../pages/legal";
import {
  HomeNovelCurationConfirmModal,
  NovelCommentActionConfirmModal,
  NovelModerationConfirmModal,
} from "../pages/novel-detail";
import { PublishNoticeDialog } from "../pages/notice-detail";
import { PublishPromptSetDialog, RestorePromptSetDialog } from "../pages/prompt-sets";
import { RefundPaymentModal, UserActionConfirmModal } from "../pages/user-detail";
import { AdminShell } from "../widgets/admin-shell";

export type RouterContext = {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});

// `/login`은 세션이 없는 유일한 비보호 라우트라 셸(내비·세션 정보·로그아웃)을 그릴 수 없다.
// 라우트 파일을 pathless layout으로 쪼개는 대신 현재 경로로 분기한다.
function RootComponent() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isLoginPage = pathname === "/login";

  return (
    <>
      {isLoginPage ? (
        <Outlet />
      ) : (
        <AdminShell>
          <Outlet />
        </AdminShell>
      )}
      <DeleteConfirmModal />
      <LiftRestrictionConfirmModal />
      <ContentActionConfirmModal />
      <HomeCurationConfirmModal />
      <NovelModerationConfirmModal />
      <NovelCommentActionConfirmModal />
      <HomeNovelCurationConfirmModal />
      <NovelCommentDeleteConfirmModal />
      <UserActionConfirmModal />
      <RefundPaymentModal />
      <PublishDialog />
      <PublishNoticeDialog />
      <PublishPromptSetDialog />
      <RestorePromptSetDialog />
      <ApproveApplicationModal />
      <DecisionReasonModal />
    </>
  );
}
